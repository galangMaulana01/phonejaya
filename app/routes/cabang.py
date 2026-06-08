from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.cabang import CabangCreateRequest, CabangUpdateRequest, AssignKepalaCabangRequest
from app.schemas.common import ok
from app.services.cabang_service import (
    list_cabang, create_cabang, update_cabang,
    assign_kepala_cabang, pecat_karyawan
)
from app.middlewares.auth import require_owner

router = APIRouter(prefix="/cabang", tags=["Cabang"])


@router.get("")
async def get_list_cabang(
    db:   AsyncIOMotorDatabase = Depends(get_db),
    _:    dict = Depends(require_owner),
):
    items = await list_cabang(db)
    return ok([i.model_dump() for i in items])


@router.post("", status_code=201)
async def tambah_cabang(
    body: CabangCreateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_owner),
):
    cab = await create_cabang(db, payload=body, actor=user.get("name", user.get("username", "")))
    return ok(cab.model_dump(), message=f"Cabang {cab.kode} berhasil ditambahkan")


@router.patch("/{kode}")
async def edit_cabang(
    kode: str,
    body: CabangUpdateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_owner),
):
    cab = await update_cabang(db, kode=kode.upper(), payload=body, actor=user.get("name", user.get("username", "")))
    return ok(cab.model_dump(), message="Cabang berhasil diupdate")


@router.post("/{kode}/kepala")
async def set_kepala_cabang(
    kode: str,
    body: AssignKepalaCabangRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_owner),
):
    cab = await assign_kepala_cabang(db, kode=kode.upper(), payload=body, actor=user.get("name", user.get("username", "")))
    return ok(cab.model_dump(), message=f"Kepala cabang {kode} berhasil diset")


@router.delete("/karyawan/{karyawan_id}")
async def fire_karyawan(
    karyawan_id: str,
    db:          AsyncIOMotorDatabase = Depends(get_db),
    user:        dict = Depends(require_owner),
):
    result = await pecat_karyawan(db, karyawan_id=karyawan_id, actor=user.get("name", user.get("username", "")))
    return ok(result, message=f"{result['nama']} telah dinonaktifkan")
