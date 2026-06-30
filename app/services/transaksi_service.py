from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException
from datetime import datetime, timezone
from app.schemas.transaksi import (
    TransaksiCreateRequest, TransaksiSparepartRequest, TransaksiResponse
)
from app.utils.id_generator import next_trx_id
from app.utils.formatters import fmt_waktu
from app.services.log_service import write_log
from app.services.customer_service import create_customer


def _fmt(doc: dict) -> TransaksiResponse:
    return TransaksiResponse(
        id          = str(doc["_id"]),
        trx_id      = doc["trx_id"],
        tipe        = doc.get("tipe", "unit"),
        unit_id     = doc.get("unit_id"),
        unit_label  = doc.get("unit_label", ""),
        kasir       = doc["kasir"],
        harga_jual  = doc["harga_jual"],
        harga_modal = doc["harga_modal"],
        profit      = doc["profit"],
        waktu       = fmt_waktu(doc.get("waktu", datetime.now(timezone.utc))),
        catatan       = doc.get("catatan", ""),
        garansi_hari  = doc.get("garansi_hari", 7),
        biaya_garansi = doc.get("biaya_garansi", 0),
        poin_dipakai  = doc.get("poin_dipakai", 0),
        poin_dapat    = doc.get("poin_dapat", 0),
        cabang        = doc["cabang"],
    )


async def list_transaksi(db, cabang=None, limit=100, date_from=None, date_to=None):
    from datetime import datetime, timezone
    query: dict = {}
    if cabang: query["cabang"] = cabang
    if date_from or date_to:
        wf: dict = {}
        if date_from: wf["$gte"] = datetime.fromisoformat(date_from.replace("Z","")).replace(tzinfo=timezone.utc)
        if date_to:   wf["$lte"] = datetime.fromisoformat(date_to.replace("Z","")).replace(tzinfo=timezone.utc)
        query["waktu"] = wf
    docs = await db.transaksi.find(query).sort("waktu", -1).limit(limit).to_list(length=limit)
    return [_fmt(d) for d in docs]


async def create_transaksi(
    db, payload: TransaksiCreateRequest, kasir_name: str, cabang: str,
    poin_dipakai: int = 0,
) -> TransaksiResponse:
    """Jual HP."""
    # Atomic check-and-lock: only matches if status is still "Tersedia"
    unit = await db.units.find_one_and_update(
        {"unit_id": payload.unit_id, "status": "Tersedia"},
        {"$set": {"status": "Sold", "tgl_terjual": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}},
        return_document=False,
    )
    if not unit:
        existing = await db.units.find_one({"unit_id": payload.unit_id})
        if not existing:
            raise HTTPException(status_code=404, detail="Unit tidak ditemukan")
        raise HTTPException(status_code=409, detail=f"Unit tidak tersedia (status: {existing['status']})")

    # Post-lock validation — rollback (Tersedia) if checks fail
    if unit.get("cabang") != cabang:
        await db.units.update_one({"unit_id": payload.unit_id}, {"$set": {"status": "Tersedia"}})
        raise HTTPException(status_code=403, detail="Unit bukan milik cabang kamu")
    if unit.get("imei") and unit["imei"] != "-":
        if payload.imei.strip() != unit["imei"]:
            await db.units.update_one({"unit_id": payload.unit_id}, {"$set": {"status": "Tersedia"}})
            raise HTTPException(status_code=422, detail="IMEI tidak sesuai. Periksa kembali.")

    # Auto-create customer jika nama diisi
    customer_id = None
    if payload.customer_nama and payload.customer_nama.strip():
        # Cek apakah customer sudah ada (by nama + kontak atau nama saja)
        existing_customer = await db.customers.find_one({
            "nama": payload.customer_nama.strip(),
            "cabang": cabang
        })
        if existing_customer:
            customer_id = str(existing_customer["_id"])
        else:
            # Create new customer
            new_customer = await create_customer(db, 
                __import__("app.schemas.customer", fromlist=["CustomerCreateRequest"]).CustomerCreateRequest(
                    nama=payload.customer_nama.strip(),
                    kontak=payload.customer_kontak.strip() if payload.customer_kontak else "",
                    cabang=cabang
                ),
                actor=kasir_name
            )
            customer_id = new_customer.id

    trx_id = await next_trx_id(db)
    biaya_garansi = payload.biaya_garansi

    # ── Points logic ──
    customer_doc = None
    if payload.customer_nama and payload.customer_nama.strip():
        customer_doc = await db.customers.find_one({"nama": payload.customer_nama.strip(), "cabang": cabang})

    harga_jual_base = unit["harga_jual"] + biaya_garansi

    if customer_doc and poin_dipakai > 0:
        if poin_dipakai > customer_doc.get("points", 0):
            raise HTTPException(status_code=400, detail="Poin customer tidak cukup")
        diskon_poin = poin_dipakai * 1000
        harga_jual_final = harga_jual_base - diskon_poin
        if harga_jual_final < 0:
            raise HTTPException(status_code=400, detail="Poin terlalu banyak, harga tidak boleh negatif")
    else:
        harga_jual_final = harga_jual_base
        poin_dipakai = 0  # pastikan 0 jika tidak ada customer

    poin_baru = int(harga_jual_final // 100000)

    # Update customer points (deduct used + add earned)
    if customer_doc:
        net_poin = -poin_dipakai + poin_baru
        if net_poin != 0:
            await db.customers.update_one(
                {"_id": customer_doc["_id"]},
                {"$inc": {"points": net_poin}}
            )
    # ── End points logic ──

    profit = harga_jual_final - unit["harga_modal"]
    now    = datetime.now(timezone.utc)
    unit_label = f"{unit['merk']} {unit['tipe']} {unit['storage']}"

    doc = {
        "trx_id":      trx_id,
        "tipe":        "unit",
        "unit_id":     payload.unit_id,
        "unit_label":  unit_label,
        "kasir":       kasir_name,
        "harga_jual":  harga_jual_final,
        "harga_modal": unit["harga_modal"],
        "profit":      profit,
        "garansi_hari": payload.garansi_hari,
        "biaya_garansi": biaya_garansi,
        "poin_dipakai":  poin_dipakai,
        "poin_dapat":    poin_baru,
        "waktu":       now,
        "catatan":     payload.catatan,
        "cabang":      cabang,
        "customer_nama":  payload.customer_nama.strip() if payload.customer_nama else "",
        "customer_kontak": payload.customer_kontak.strip() if payload.customer_kontak else "",
        "customer_id":    customer_id,
    }
    result = await db.transaksi.insert_one(doc)
    doc["_id"] = result.inserted_id
    await write_log(db, kasir_name, "Input Transaksi", f"{trx_id} • {unit_label}", cabang)
    return _fmt(doc)


async def create_transaksi_sparepart(
    db, payload: TransaksiSparepartRequest, kasir_name: str, cabang: str
) -> TransaksiResponse:
    """Jual sparepart/aksesoris."""
    if not payload.items:
        raise HTTPException(status_code=422, detail="Minimal 1 item sparepart")

    total_jual  = 0
    total_modal = 0
    labels      = []

    for item in payload.items:
        sp = await db.sparepart.find_one({"sp_id": item.sp_id})
        if not sp:
            raise HTTPException(status_code=404, detail=f"Sparepart {item.sp_id} tidak ditemukan")
        if sp["stok"] < item.jumlah:
            raise HTTPException(
                status_code=400,
                detail=f"Stok {sp['nama']} tidak cukup. Tersedia: {sp['stok']}, diminta: {item.jumlah}"
            )
        if sp.get("cabang") != cabang:
            raise HTTPException(status_code=403, detail=f"Sparepart {sp['nama']} bukan milik cabangmu")
        total_jual  += sp["harga_jual"]  * item.jumlah
        total_modal += sp["harga_beli"]  * item.jumlah
        labels.append(f"{sp['nama']} x{item.jumlah}")

        # Kurangi stok
        await db.sparepart.update_one(
            {"sp_id": item.sp_id},
            {"$set": {
                "stok":       sp["stok"] - item.jumlah,
                "updated_at": datetime.now(timezone.utc),
            }}
        )

    trx_id = await next_trx_id(db, cabang=cabang)
    now    = datetime.now(timezone.utc)
    label  = ", ".join(labels)
    profit = total_jual - total_modal

    doc = {
        "trx_id":      trx_id,
        "tipe":        "sparepart",
        "unit_id":     None,
        "unit_label":  label,
        "kasir":       kasir_name,
        "harga_jual":  total_jual,
        "harga_modal": total_modal,
        "profit":      profit,
        "waktu":       now,
        "catatan":     payload.catatan,
        "cabang":      cabang,
        "sp_items":    [i.model_dump() for i in payload.items],
    }
    result = await db.transaksi.insert_one(doc)
    doc["_id"] = result.inserted_id
    await write_log(db, kasir_name, "Jual Sparepart", f"{trx_id} • {label}", cabang)
    return _fmt(doc)
