from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.schemas.cabang import (
    CabangCreateRequest, CabangUpdateRequest,
    AssignKepalaCabangRequest, CabangResponse
)
from app.utils.security import hash_password
from app.services.log_service import write_log


def _fmt(doc: dict) -> CabangResponse:
    from app.utils.formatters import fmt_waktu
    return CabangResponse(
        id               = str(doc["_id"]),
        nama             = doc.get("nama", ""),
        kode             = doc.get("kode", ""),
        alamat           = doc.get("alamat", ""),
        telp             = doc.get("telp", ""),
        aktif            = doc.get("aktif", True),
        kepala_cabang    = doc.get("kepala_cabang"),
        kepala_username  = doc.get("kepala_username"),
        jumlah_karyawan  = doc.get("jumlah_karyawan", 0),
        created_at       = fmt_waktu(doc["created_at"]) if doc.get("created_at") else "",
    )


async def list_cabang(db: AsyncIOMotorDatabase) -> List[CabangResponse]:
    docs = await db.cabang.find().sort("nama", 1).to_list(length=None)
    result = []
    for d in docs:
        # Hitung jumlah karyawan aktif per cabang
        count = await db.karyawan.count_documents({"cabang": d["kode"], "aktif": True})
        d["jumlah_karyawan"] = count
        result.append(_fmt(d))
    return result


async def create_cabang(
    db: AsyncIOMotorDatabase,
    payload: CabangCreateRequest,
    actor: str,
) -> CabangResponse:
    # Cek kode unik
    if await db.cabang.find_one({"kode": payload.kode}):
        raise HTTPException(status_code=409, detail=f"Kode cabang '{payload.kode}' sudah ada")

    now = datetime.now(timezone.utc)
    doc = {
        "nama":            payload.nama,
        "kode":            payload.kode,
        "alamat":          payload.alamat,
        "telp":            payload.telp,
        "aktif":           True,
        "kepala_cabang":   None,
        "kepala_username": None,
        "created_at":      now,
        "created_by":      actor,
    }
    result = await db.cabang.insert_one(doc)
    doc["_id"] = result.inserted_id
    await write_log(db, actor, "Tambah Cabang", f"{payload.kode} • {payload.nama}", "PUSAT")
    return _fmt(doc)


async def update_cabang(
    db: AsyncIOMotorDatabase,
    kode: str,
    payload: CabangUpdateRequest,
    actor: str,
) -> CabangResponse:
    cab = await db.cabang.find_one({"kode": kode})
    if not cab:
        raise HTTPException(status_code=404, detail=f"Cabang {kode} tidak ditemukan")

    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc)
    await db.cabang.update_one({"kode": kode}, {"$set": update})
    updated = await db.cabang.find_one({"kode": kode})
    await write_log(db, actor, "Update Cabang", kode, "PUSAT")
    return _fmt(updated)


async def assign_kepala_cabang(
    db: AsyncIOMotorDatabase,
    kode: str,
    payload: AssignKepalaCabangRequest,
    actor: str,
) -> CabangResponse:
    cab = await db.cabang.find_one({"kode": kode})
    if not cab:
        raise HTTPException(status_code=404, detail=f"Cabang {kode} tidak ditemukan")

    # Cek username belum dipakai
    if await db.users.find_one({"username": payload.username}):
        raise HTTPException(status_code=409, detail=f"Username '{payload.username}' sudah digunakan")

    if len(payload.password) < 6:
        raise HTTPException(status_code=422, detail="Password minimal 6 karakter")

    now = datetime.now(timezone.utc)

    # Nonaktifkan kepala cabang lama kalau ada
    if cab.get("kepala_username"):
        await db.users.update_one(
            {"username": cab["kepala_username"]},
            {"$set": {"aktif": False, "updated_at": now}}
        )

    # Buat akun kepala cabang baru
    # Buat akun kepala cabang baru - handle race condition dengan try/except DuplicateKeyError
    try:
        await db.users.insert_one({
            "name":       payload.nama,
            "username":   payload.username,
            "password_hash": hash_password(payload.password),
            "role":       "kepala_cabang",
            "cabang":     kode,
            "aktif":      True,
            "created_at": now,
            "created_by": actor,
        })
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail=f"Username '{payload.username}' baru saja digunakan (race condition)")

    # Simpan juga ke karyawan
    await db.karyawan.insert_one({
        "nama":       payload.nama,
        "username":   payload.username,
        "jabatan":    "Kepala Cabang",
        "cabang":     kode,
        "gaji":       0,
        "aktif":      True,
        "bergabung":  now.date().isoformat(),
        "created_at": now,
        "created_by": actor,
    })

    # Update cabang doc
    await db.cabang.update_one(
        {"kode": kode},
        {"$set": {
            "kepala_cabang":   payload.nama,
            "kepala_username": payload.username,
            "updated_at":      now,
        }}
    )
    updated = await db.cabang.find_one({"kode": kode})
    await write_log(db, actor, "Assign Kepala Cabang",
        f"{kode} → {payload.nama} ({payload.username})", "PUSAT")
    return _fmt(updated)


async def pecat_karyawan(
    db: AsyncIOMotorDatabase,
    karyawan_id: str,
    actor: str,
) -> dict:
    from bson import ObjectId
    from bson.errors import InvalidId
    try:
        oid = ObjectId(karyawan_id)
    except (InvalidId, Exception):
        raise HTTPException(status_code=400, detail="ID karyawan tidak valid")
    kar = await db.karyawan.find_one({"_id": oid})
    if not kar:
        raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan")

    now = datetime.now(timezone.utc)
    # Nonaktifkan di karyawan
    await db.karyawan.update_one(
        {"_id": ObjectId(karyawan_id)},
        {"$set": {"aktif": False, "updated_at": now}}
    )
    # Nonaktifkan login di users
    if kar.get("username"):
        await db.users.update_one(
            {"username": kar["username"]},
            {"$set": {"aktif": False, "updated_at": now}}
        )
    await write_log(db, actor, "Pecat Karyawan",
        f"{kar['nama']} ({kar.get('jabatan','')}) • {kar.get('cabang','')}", "PUSAT")
    return {"nama": kar["nama"], "cabang": kar.get("cabang", "")}
