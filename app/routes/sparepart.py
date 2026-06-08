from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.sparepart import SparepartCreateRequest, SparepartUpdateStokRequest
from app.schemas.common import ok
from app.services import sparepart as sparepart_service
from app.middlewares.auth import require_kasir_or_owner, require_kepala_or_owner

router = APIRouter(prefix="/sparepart", tags=["Sparepart"])


@router.get("")
async def list_sparepart(
    cabang:   Optional[str] = Query(None),
    kategori: Optional[str] = Query(None),
    db:       AsyncIOMotorDatabase = Depends(get_db),
    user:     dict = Depends(require_kasir_or_owner),
):
    cab = cabang if user.get("role") == "owner" else user.get("cabang")
    items = await sparepart_service.list_sparepart(db, cabang=cab, kategori=kategori)
    return ok([i.model_dump() for i in items])


@router.post("", status_code=201)
async def create_sparepart(
    body: SparepartCreateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kepala_or_owner),
):
    # Force cabang sesuai user
    if user.get("role") == "kepala_cabang":
        body.cabang = user.get("cabang", body.cabang)
    sp = await sparepart_service.create_sparepart(db, payload=body, actor=user.get("name", user.get("username", "")))
    return ok(sp.model_dump(), message=f"{sp.sp_id} berhasil ditambahkan")


@router.patch("/{sp_id}/stok")
async def update_stok(
    sp_id: str,
    body:  SparepartUpdateStokRequest,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    user:  dict = Depends(require_kepala_or_owner),
):
    sp = await sparepart_service.update_stok(db, sp_id=sp_id, payload=body, actor=user.get("name", user.get("username", "")))
    return ok(sp.model_dump(), message="Stok berhasil diupdate")
