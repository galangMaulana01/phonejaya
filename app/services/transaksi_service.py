from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException
from app.schemas.transaksi import (
    TransaksiCreateRequest, TransaksiSparepartRequest, TransaksiResponse
)
from app.utils.id_generator import next_trx_id
from app.utils.formatters import fmt_waktu
from app.services.log_service import write_log


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
    db, payload: TransaksiCreateRequest, kasir_name: str, cabang: str
) -> TransaksiResponse:
    """Jual HP."""
    unit = await db.units.find_one({"unit_id": payload.unit_id})
    if not unit:
        raise HTTPException(status_code=404, detail="Unit tidak ditemukan")
    if unit["status"] != "Tersedia":
        raise HTTPException(status_code=409, detail=f"Unit tidak tersedia (status: {unit['status']})")
    if unit.get("imei") and unit["imei"] != "-":
        if payload.imei.strip() != unit["imei"]:
            raise HTTPException(status_code=422, detail="IMEI tidak sesuai. Periksa kembali.")

    await db.units.update_one(
        {"unit_id": payload.unit_id},
        {"$set": {"status": "Sold", "tgl_terjual": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}}
    )

    trx_id = await next_trx_id(db)
    biaya_garansi = payload.biaya_garansi
    profit = unit["harga_jual"] + biaya_garansi - unit["harga_modal"]
    now    = datetime.now(timezone.utc)
    unit_label = f"{unit['merk']} {unit['tipe']} {unit['storage']}"

    doc = {
        "trx_id":      trx_id,
        "tipe":        "unit",
        "unit_id":     payload.unit_id,
        "unit_label":  unit_label,
        "kasir":       kasir_name,
        "harga_jual":  unit["harga_jual"] + biaya_garansi,
        "harga_modal": unit["harga_modal"],
        "profit":      profit,
        "garansi_hari": payload.garansi_hari,
        "biaya_garansi": biaya_garansi,
        "waktu":       now,
        "catatan":     payload.catatan,
        "cabang":      cabang,
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
