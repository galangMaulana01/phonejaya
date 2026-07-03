from datetime import datetime, timezone, date
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException
from app.schemas.karyawan import KaryawanCreateRequest, KaryawanResponse
from app.services.log_service import write_log
from app.utils.security import hash_password


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
    if not payload.username.strip():
        raise HTTPException(status_code=422, detail="Username tidak boleh kosong")
    if not payload.password.strip():
        raise HTTPException(status_code=422, detail="Password tidak boleh kosong")

    # Cek username belum dipakai di users maupun karyawan
    if await db.users.find_one({"username": payload.username}):
        raise HTTPException(status_code=409, detail=f"Username '{payload.username}' sudah digunakan")
    if await db.karyawan.find_one({"username": payload.username}):
        raise HTTPException(status_code=409, detail=f"Username '{payload.username}' sudah digunakan")

    now = datetime.now(timezone.utc)

    # Simpan data karyawan
    doc = {
        "nama": payload.nama, "username": payload.username,
        "jabatan": payload.jabatan, "cabang": payload.cabang,
        "gaji": payload.gaji, "aktif": True,
        "bergabung": date.today().isoformat(),
        "created_at": now,
    }
    result = await db.karyawan.insert_one(doc)
    doc["_id"] = result.inserted_id

    # Buat akun login di users collection
    role_map = {
        "Kasir":   "kasir",
        "Teknisi": "teknisi",
        "Owner":   "owner",
        "Admin":   "owner",
    }
    role = role_map.get(payload.jabatan, "kasir")
    await db.users.insert_one({
        "name":       payload.nama,
        "username":   payload.username,
        "password_hash":   hash_password(payload.password),
        "role":       role,
        "cabang":     payload.cabang,
        "aktif":      True,
        "created_at": now,
    })

    await write_log(db, actor, "Tambah Karyawan",
        f"{payload.nama} ({payload.username}) • {payload.jabatan}", payload.cabang)
    return _fmt(doc)


async def reset_password(db, karyawan_id: str, new_password: str, actor: str) -> dict:
    """Owner reset password karyawan berdasarkan karyawan_id."""
    from bson import ObjectId

    if len(new_password) < 6:
        raise HTTPException(status_code=422, detail="Password minimal 6 karakter")

    kar = await db.karyawan.find_one({"_id": ObjectId(karyawan_id)})
    if not kar:
        raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan")

    if not kar.get("username"):
        raise HTTPException(status_code=400, detail="Karyawan ini tidak memiliki akun login")

    hashed = hash_password(new_password)
    now = datetime.now(timezone.utc)

    await db.users.update_one(
        {"username": kar["username"]},
        {"$set": {"password_hash": hashed, "updated_at": now}}
    )

    await write_log(db, actor, "Reset Password Karyawan",
        f"{kar['nama']} ({kar['username']})", kar.get("cabang", ""))

    return {"nama": kar["nama"], "username": kar["username"]}
