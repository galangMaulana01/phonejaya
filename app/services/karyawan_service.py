from datetime import datetime, timezone, date
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException
from app.schemas.karyawan import KaryawanCreateRequest, KaryawanResponse
from app.services.log_service import write_log


def _fmt(doc: dict) -> KaryawanResponse:
    return KaryawanResponse(
        id=str(doc["_id"]), nama=doc["nama"], username=doc["username"],
        jabatan=doc["jabatan"], cabang=doc["cabang"], gaji=doc["gaji"],
        aktif=doc.get("aktif", True), bergabung=doc.get("bergabung",""),
    )


async def list_karyawan(db, cabang: Optional[str]=None) -> List[KaryawanResponse]:
    query = {}
    if cabang: query["cabang"] = cabang
    docs = await db.karyawan.find(query).sort("nama", 1).to_list(length=None)
    return [_fmt(d) for d in docs]


async def create_karyawan(db, payload: KaryawanCreateRequest, actor: str) -> KaryawanResponse:
    if payload.username:
        existing = await db.users.find_one({"username": payload.username})
        if existing:
            raise HTTPException(status_code=409, detail=f"Username '{payload.username}' sudah digunakan")

    doc = {
        "nama": payload.nama, "username": payload.username,
        "jabatan": payload.jabatan, "cabang": payload.cabang,
        "gaji": payload.gaji, "aktif": True,
        "bergabung": date.today().isoformat(),
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.karyawan.insert_one(doc)
    doc["_id"] = result.inserted_id
    await write_log(db, actor, "Tambah Karyawan", payload.nama, payload.cabang)
    return _fmt(doc)
