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
        sp_items      = doc.get("sp_items"),
        foto_serah_terima=doc.get("foto_serah_terima"),
    )


async def list_transaksi(db, cabang=None, limit=100, date_from=None, date_to=None):
    from datetime import datetime, timezone, timedelta
    query: dict = {}
    if cabang: query["cabang"] = cabang
    if date_from or date_to:
        wf: dict = {}
        if date_from: wf["$gte"] = datetime.fromisoformat(date_from.replace("Z","")).replace(tzinfo=timezone.utc)
        if date_to:   
            # Make date_to inclusive by adding 1 day
            dt = datetime.fromisoformat(date_to.replace("Z","")).replace(tzinfo=timezone.utc) + timedelta(days=1)
            wf["$lt"] = dt
        query["waktu"] = wf
    docs = await db.transaksi.find(query).sort("waktu", -1).limit(limit).to_list(length=limit)
    return [_fmt(d) for d in docs]


async def create_transaksi(
    db, payload: TransaksiCreateRequest, kasir_name: str, cabang: str,
    poin_dipakai: int = 0,
) -> TransaksiResponse:
    """Transaksi gabungan: HP dan/atau sparepart."""
    has_unit = bool(payload.unit_id and payload.unit_id.strip())
    has_sp = bool(payload.sparepart_items and len(payload.sparepart_items) > 0)

    if not has_unit and not has_sp:
        raise HTTPException(status_code=422, detail="Pilih minimal 1 unit atau sparepart")

    unit = None
    unit_label_parts = []
    total_jual_unit = 0
    total_modal_unit = 0
    sp_labels = []
    sp_total_jual = 0
    sp_total_modal = 0
    sp_items_doc = []

    # ── Process unit (if any) ──
    if has_unit:
        # Atomic claim with cabang — prevents cross-branch sale + double-click
        unit = await db.units.find_one_and_update(
            {"unit_id": payload.unit_id, "cabang": cabang, "status": "Tersedia"},
            {"$set": {"status": "Sold", "tgl_terjual": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}},
            return_document=False,
        )
        if not unit:
            existing = await db.units.find_one({"unit_id": payload.unit_id})
            if not existing:
                raise HTTPException(status_code=404, detail="Unit tidak ditemukan")
            if existing.get("cabang") != cabang:
                raise HTTPException(status_code=403, detail="Unit bukan milik cabang kamu")
            raise HTTPException(status_code=409, detail=f"Unit tidak tersedia (status: {existing['status']})")

        # Validate IMEI (after claim, before proceeding)
        if unit.get("imei") and unit["imei"] != "-":
            if payload.imei.strip() != unit["imei"]:
                # Safe rollback: only if still Sold (our claim)
                await db.units.update_one(
                    {"_id": unit["_id"], "status": "Sold"},
                    {"$set": {"status": "Tersedia"}}
                )
                raise HTTPException(status_code=422, detail="IMEI tidak sesuai. Periksa kembali.")

        total_jual_unit = unit["harga_jual"] + payload.biaya_garansi
        total_modal_unit = unit["harga_modal"]
        unit_label_parts.append(f"{unit['merk']} {unit['tipe']} {unit['storage']}")

    # ── Process spareparts (if any) ──
    if has_sp:
        for item in payload.sparepart_items:
            sp = await db.sparepart.find_one({"sp_id": item.sp_id})
            if not sp:
                raise HTTPException(status_code=404, detail=f"Sparepart {item.sp_id} tidak ditemukan")
            if sp.get("cabang") != cabang:
                raise HTTPException(status_code=403, detail=f"Sparepart {sp['nama']} bukan milik cabangmu")

            # Atomic check-and-decrement to prevent race condition
            result = await db.sparepart.find_one_and_update(
                {"sp_id": item.sp_id, "stok": {"$gte": item.jumlah}},
                {"$inc": {"stok": -item.jumlah}, "$set": {"updated_at": datetime.now(timezone.utc)}},
                return_document=False,
            )
            if not result:
                raise HTTPException(
                    status_code=400,
                    detail=f"Stok {sp['nama']} tidak cukup. Tersedia: {sp['stok']}, diminta: {item.jumlah}"
                )

            sp_jual = sp["harga_jual"] * item.jumlah
            sp_modal = sp["harga_beli"] * item.jumlah
            sp_total_jual += sp_jual
            sp_total_modal += sp_modal
            sp_labels.append(f"{sp['nama']} x{item.jumlah}")
            sp_items_doc.append({"sp_id": item.sp_id, "jumlah": item.jumlah, "nama": sp["nama"], "harga": sp["harga_jual"]})

    # ── Calculate totals ──
    harga_jual_base = total_jual_unit + sp_total_jual
    harga_modal_total = total_modal_unit + sp_total_modal
    all_labels = unit_label_parts + sp_labels
    label_combined = " + ".join(all_labels) if all_labels else "Transaksi"

    # ── Auto-create customer ──
    customer_id = None
    customer_doc = None
    if payload.customer_nama and payload.customer_nama.strip():
        # Per-cabang: lookup by nama + cabang (same customer name in different branches = different customers)
        customer_doc = await db.customers.find_one({"nama": payload.customer_nama.strip(), "cabang": cabang})
        if customer_doc:
            customer_id = str(customer_doc["_id"])
        else:
            new_customer = await create_customer(db,
                __import__("app.schemas.customer", fromlist=["CustomerCreateRequest"]).CustomerCreateRequest(
                    nama=payload.customer_nama.strip(),
                    kontak=payload.customer_kontak.strip() if payload.customer_kontak else "",
                    cabang=cabang
                ),
                actor=kasir_name
            )
            customer_id = new_customer.id
            # Re-query to get raw document with ObjectId (create_customer returns string id)
            customer_doc = await db.customers.find_one({"nama": payload.customer_nama.strip(), "cabang": cabang})

    # ── Points logic ──
    trx_id = await next_trx_id(db)
    if customer_doc and poin_dipakai > 0:
        if poin_dipakai > customer_doc.get("points", 0):
            raise HTTPException(status_code=400, detail="Poin customer tidak cukup")
        diskon_poin = poin_dipakai * 1000
        harga_jual_final = harga_jual_base - diskon_poin
        if harga_jual_final < 0:
            raise HTTPException(status_code=400, detail="Poin terlalu banyak, harga tidak boleh negatif")
    else:
        harga_jual_final = harga_jual_base
        poin_dipakai = 0

    poin_baru = int(harga_jual_final // 100000)

    if customer_doc:
        net_poin = -poin_dipakai + poin_baru
        if net_poin != 0:
            await db.customers.update_one(
                {"_id": customer_doc["_id"]},
                {"$inc": {"points": net_poin}}
            )

    profit = harga_jual_final - harga_modal_total
    now = datetime.now(timezone.utc)

    # ── Determine tipe ──
    if has_unit and has_sp:
        tipe = "gabungan"
    elif has_unit:
        tipe = "unit"
    else:
        tipe = "sparepart"

    doc = {
        "trx_id":        trx_id,
        "tipe":          tipe,
        "unit_id":       payload.unit_id if has_unit else None,
        "unit_label":    label_combined,
        "kasir":         kasir_name,
        "harga_jual":    harga_jual_final,
        "harga_modal":   harga_modal_total,
        "profit":        profit,
        "garansi_hari":  payload.garansi_hari if has_unit else 0,
        "biaya_garansi": payload.biaya_garansi if has_unit else 0,
        "poin_dipakai":  poin_dipakai,
        "poin_dapat":    poin_baru,
        "waktu":         now,
        "catatan":       payload.catatan,
        "cabang":        cabang,
        "customer_nama":  payload.customer_nama.strip() if payload.customer_nama else "",
        "customer_kontak": payload.customer_kontak.strip() if payload.customer_kontak else "",
        "customer_id":    customer_id,
        "sp_items":      sp_items_doc if has_sp else None,
        "foto_serah_terima": payload.foto_serah_terima,
    }
    result = await db.transaksi.insert_one(doc)
    doc["_id"] = result.inserted_id
    await write_log(db, kasir_name, "Input Transaksi", f"{trx_id} • {label_combined}", cabang)
    return _fmt(doc)


async def create_transaksi_sparepart(
    db, payload: TransaksiSparepartRequest, kasir_name: str, cabang: str
) -> TransaksiResponse:
    """Legacy: jual sparepart saja via endpoint /sparepart."""
    if not payload.items:
        raise HTTPException(status_code=422, detail="Minimal 1 item sparepart")

    total_jual  = 0
    total_modal = 0
    labels      = []

    for item in payload.items:
        sp = await db.sparepart.find_one({"sp_id": item.sp_id})
        if not sp:
            raise HTTPException(status_code=404, detail=f"Sparepart {item.sp_id} tidak ditemukan")
        if sp.get("cabang") != cabang:
            raise HTTPException(status_code=403, detail=f"Sparepart {sp['nama']} bukan milik cabangmu")

        # Atomic check-and-decrement to prevent race condition
        result = await db.sparepart.find_one_and_update(
            {"sp_id": item.sp_id, "stok": {"$gte": item.jumlah}},
            {"$inc": {"stok": -item.jumlah}, "$set": {"updated_at": datetime.now(timezone.utc)}},
            return_document=False,
        )
        if not result:
            raise HTTPException(
                status_code=400,
                detail=f"Stok {sp['nama']} tidak cukup. Tersedia: {sp['stok']}, diminta: {item.jumlah}"
            )

        total_jual  += sp["harga_jual"]  * item.jumlah
        total_modal += sp["harga_beli"]  * item.jumlah
        labels.append(f"{sp['nama']} x{item.jumlah}")

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
