from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException
from app.schemas.unit import UnitCreateRequest, UnitUpdateRequest, UnitResponse
from app.utils.id_generator import next_unit_id, resolve_kategori, resolve_kondisi
from app.services.log_service import write_log


def _fmt(doc: dict) -> UnitResponse:
    return UnitResponse(
        id=str(doc["_id"]), unit_id=doc["unit_id"],
        merk=doc["merk"], tipe=doc["tipe"], storage=doc["storage"],
        warna=doc["warna"], imei=doc["imei"],
        harga_modal=doc["harga_modal"], harga_jual=doc["harga_jual"],
        kondisi=doc["kondisi"], battery=doc["battery"],
        status=doc["status"], kategori=doc["kategori"],
        catatan=doc.get("catatan",""), cabang=doc["cabang"],
    )


async def list_units(db, cabang: Optional[str]=None, status_filter: Optional[str]=None) -> List[UnitResponse]:
    query: dict = {}
    if cabang: query["cabang"] = cabang
    if status_filter and status_filter != "Semua": query["status"] = status_filter
    docs = await db.units.find(query).sort("_id", -1).to_list(length=None)
    return [_fmt(d) for d in docs]


async def create_unit(db, payload: UnitCreateRequest, actor: str) -> UnitResponse:
    if payload.imei and payload.imei != "-":
        existing = await db.units.find_one({"imei": payload.imei, "status": {"$ne": "Sold"}})
        if existing:
            raise HTTPException(status_code=409, detail=f"IMEI {payload.imei} sudah terdaftar")

    unit_id = await next_unit_id(db, payload.kat_kode, payload.kondisi_kode, payload.cabang)
    doc = {
        "unit_id": unit_id, "merk": payload.merk, "tipe": payload.tipe,
        "storage": payload.storage, "warna": payload.warna, "imei": payload.imei,
        "harga_modal": payload.harga_modal, "harga_jual": payload.harga_jual,
        "kondisi": resolve_kondisi(payload.kondisi_kode),
        "battery": payload.battery, "status": "Tersedia",
        "kategori": resolve_kategori(payload.kat_kode),
        "catatan": payload.catatan, "cabang": payload.cabang,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.units.insert_one(doc)
    doc["_id"] = result.inserted_id
    await write_log(db, actor, "Tambah Unit", f"{unit_id} • {payload.merk} {payload.tipe}", payload.cabang)
    return _fmt(doc)


async def update_unit(db, unit_id: str, payload: UnitUpdateRequest, actor: str) -> UnitResponse:
    unit = await db.units.find_one({"unit_id": unit_id})
    if not unit:
        raise HTTPException(status_code=404, detail=f"Unit {unit_id} tidak ditemukan")

    updates: dict = {"updated_at": datetime.now(timezone.utc)}
    if payload.harga_modal is not None: updates["harga_modal"] = payload.harga_modal
    if payload.harga_jual  is not None: updates["harga_jual"]  = payload.harga_jual
    if payload.battery     is not None: updates["battery"]     = payload.battery
    if payload.status      is not None: updates["status"]      = payload.status.value
    if payload.catatan     is not None: updates["catatan"]     = payload.catatan

    await db.units.update_one({"unit_id": unit_id}, {"$set": updates})
    updated = await db.units.find_one({"unit_id": unit_id})
    await write_log(db, actor, "Edit Unit", f"{unit_id} • Update data", unit.get("cabang",""))
    return _fmt(updated)
