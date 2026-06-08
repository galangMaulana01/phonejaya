from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.karyawan import KaryawanCreateRequest
from app.schemas.common import ok
from app.services import karyawan_service
from app.middlewares.auth import require_owner, require_kepala_or_owner

router = APIRouter(prefix="/karyawan", tags=["Karyawan"])


@router.get("")
async def list_karyawan(
    cabang: Optional[str] = Query(None),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kepala_or_owner),   # owner + kepala_cabang bisa lihat
):
    # Owner bisa lihat semua / filter bebas
    # Kepala cabang hanya lihat cabangnya
    if user.get("role") == "owner":
        cab = cabang
    else:
        cab = user.get("cabang")

    items = await karyawan_service.list_karyawan(db, cabang=cab)
    return ok([i.model_dump() for i in items])


@router.post("", status_code=201)
async def create_karyawan(
    body: KaryawanCreateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kepala_or_owner),   # kepala_cabang yang tambah karyawan
):
    # Force cabang sesuai kepala cabang yang login
    if user.get("role") == "kepala_cabang":
        body.cabang = user.get("cabang", body.cabang)
    item = await karyawan_service.create_karyawan(db, body, actor=user.get("name", user.get("username", "")))
    return ok(item.model_dump(), message="Karyawan berhasil ditambahkan")
