from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException
from app.schemas.service import ServiceCreateRequest, ServiceUpdateRequest, ServiceResponse
from app.utils.id_generator import next_service_id
from app.utils.formatters import fmt_waktu
from app.services.log_service import write_log


def _fmt(doc: dict) -> ServiceResponse:
    return ServiceResponse(
        id=str(doc["_id"]), service_id=doc["service_id"],
        nama_customer=doc["nama_customer"], kontak_customer=doc["kontak_customer"],
        merk=doc["merk"], tipe=doc["tipe"], keluhan=doc["keluhan"],
        catatan_kerusakan=doc.get("catatan_kerusakan",""),
        estimasi_biaya=doc.get("estimasi_biaya",0),
        status=doc["status"], teknisi=doc.get("teknisi",""),
        foto_urls=doc.get("foto_urls",[]),
        cabang=doc["cabang"],
        created_at=fmt_waktu(doc["created_at"]),
        updated_at=fmt_waktu(doc["updated_at"]) if doc.get("updated_at") else None,
    )


async def list_service(db, cabang: Optional[str]=None, status: Optional[str]=None, limit: int=100) -> List[ServiceResponse]:
    query: dict = {}
    if cabang: query["cabang"] = cabang
    if status: query["status"] = status
    docs = await db.service.find(query).sort("created_at", -1).limit(limit).to_list(length=limit)
    return [_fmt(d) for d in docs]


async def get_service(db, service_id: str) -> ServiceResponse:
    doc = await db.service.find_one({"service_id": service_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Service {service_id} tidak ditemukan")
    return _fmt(doc)


async def create_service(db, payload: ServiceCreateRequest, actor: str) -> ServiceResponse:
    service_id = await next_service_id(db)
    now = datetime.now(timezone.utc)
    doc = {
        "service_id": service_id,
        "nama_customer": payload.nama_customer,
        "kontak_customer": payload.kontak_customer,
        "merk": payload.merk, "tipe": payload.tipe,
        "keluhan": payload.keluhan,
        "catatan_kerusakan": payload.catatan_kerusakan,
        "estimasi_biaya": payload.estimasi_biaya,
        "status": "Masuk", "teknisi": actor,
        "foto_urls": [],
        "cabang": payload.cabang,
        "created_at": now, "updated_at": None,
    }
    result = await db.service.insert_one(doc)
    doc["_id"] = result.inserted_id
    await write_log(db, actor, "Input Service", f"{service_id} • {payload.merk} {payload.tipe}", payload.cabang)
    return _fmt(doc)


async def update_service(db, service_id: str, payload: ServiceUpdateRequest, actor: str) -> ServiceResponse:
    doc = await db.service.find_one({"service_id": service_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Service {service_id} tidak ditemukan")

    updates: dict = {"updated_at": datetime.now(timezone.utc)}
    if payload.status            is not None: updates["status"]            = payload.status.value
    if payload.catatan_kerusakan is not None: updates["catatan_kerusakan"] = payload.catatan_kerusakan
    if payload.estimasi_biaya    is not None: updates["estimasi_biaya"]    = payload.estimasi_biaya
    if payload.teknisi           is not None: updates["teknisi"]           = payload.teknisi

    await db.service.update_one({"service_id": service_id}, {"$set": updates})
    updated = await db.service.find_one({"service_id": service_id})
    await write_log(db, actor, "Update Service", f"{service_id} • {updates.get('status','update')}", doc.get("cabang",""))
    return _fmt(updated)


async def add_foto_url(db, service_id: str, url: str, actor: str) -> ServiceResponse:
    """Tambah URL foto eksternal (Cloudinary/ImgBB) ke service."""
    doc = await db.service.find_one({"service_id": service_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Service {service_id} tidak ditemukan")

    await db.service.update_one(
        {"service_id": service_id},
        {"$push": {"foto_urls": url}, "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    updated = await db.service.find_one({"service_id": service_id})
    await write_log(db, actor, "Tambah Foto Service", f"{service_id}", doc.get("cabang",""))
    return _fmt(updated)
