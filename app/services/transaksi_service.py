from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException, status
from app.schemas.transaksi import TransaksiCreateRequest, TransaksiResponse
from app.utils.id_generator import next_trx_id
from app.utils.formatters import fmt_waktu
from app.services.log_service import write_log


def _fmt(doc: dict) -> TransaksiResponse:
    return TransaksiResponse(
        id=str(doc["_id"]), trx_id=doc["trx_id"],
        unit_id=doc["unit_id"], unit_label=doc["unit_label"],
        kasir=doc["kasir"], harga_jual=doc["harga_jual"],
        harga_modal=doc["harga_modal"], profit=doc["profit"],
        waktu=fmt_waktu(doc.get("waktu", datetime.now(timezone.utc))),
        catatan=doc.get("catatan",""), cabang=doc["cabang"],
    )


async def list_transaksi(db, cabang: Optional[str]=None, limit: int=100) -> List[TransaksiResponse]:
    query = {}
    if cabang: query["cabang"] = cabang
    docs = await db.transaksi.find(query).sort("waktu", -1).limit(limit).to_list(length=limit)
    return [_fmt(d) for d in docs]


async def create_transaksi(db, payload: TransaksiCreateRequest, kasir_name: str, cabang: str) -> TransaksiResponse:
    unit = await db.units.find_one({"unit_id": payload.unit_id})
    if not unit:
        raise HTTPException(status_code=404, detail="Unit tidak ditemukan")
    if unit["status"] != "Tersedia":
        raise HTTPException(status_code=409, detail=f"Unit tidak tersedia (status: {unit['status']})")
    if unit.get("imei") and unit["imei"] != "-":
        if payload.imei.strip() != unit["imei"]:
            raise HTTPException(status_code=422, detail="IMEI tidak sesuai. Periksa kembali.")

    await db.units.update_one({"unit_id": payload.unit_id}, {"$set": {"status": "Sold", "updated_at": datetime.now(timezone.utc)}})

    trx_id = await next_trx_id(db)
    profit = unit["harga_jual"] - unit["harga_modal"]
    now = datetime.now(timezone.utc)
    unit_label = f"{unit['merk']} {unit['tipe']} {unit['storage']}"

    doc = {
        "trx_id": trx_id, "unit_id": payload.unit_id, "unit_label": unit_label,
        "kasir": kasir_name, "harga_jual": unit["harga_jual"],
        "harga_modal": unit["harga_modal"], "profit": profit,
        "waktu": now, "catatan": payload.catatan, "cabang": cabang,
    }
    result = await db.transaksi.insert_one(doc)
    doc["_id"] = result.inserted_id
    await write_log(db, kasir_name, "Input Transaksi", f"{trx_id} • {unit_label}", cabang)
    return _fmt(doc)
