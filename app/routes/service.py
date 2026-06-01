from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config.database import get_db
from app.schemas.service import ServiceUpdateRequest
from app.schemas.common import ok
from app.services import service_service
from app.middlewares.auth import require_teknisi_or_owner, require_any, require_kasir_or_owner

router = APIRouter(prefix="/service", tags=["Service"])


class FotoUrlRequest(BaseModel):
    url: str


@router.get("")
async def list_service(
    cabang: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit:  int = Query(100, ge=1, le=500),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    _user:  dict = Depends(require_any),
):
    """
    List tiket service.
    - Owner/Kasir: lihat semua
    - Teknisi: lihat semua (filter by cabang di frontend)
    """
    items = await service_service.list_service(db, cabang=cabang, status=status, limit=limit)
    return ok([i.model_dump() for i in items])


@router.get("/pending-approval")
async def pending_approval(
    cabang: Optional[str] = Query(None),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    _user:  dict = Depends(require_kasir_or_owner),
):
    """
    Daftar tiket service yang sudah Selesai dan menunggu approval harga dari kasir/owner.
    """
    items = await service_service.list_service(db, cabang=cabang, status="Selesai", limit=500)
    return ok([i.model_dump() for i in items])


@router.get("/{service_id}")
async def get_service(
    service_id: str,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    _user: dict = Depends(require_any),
):
    item = await service_service.get_service(db, service_id)
    return ok(item.model_dump())


@router.put("/{service_id}")
async def update_service(
    service_id: str,
    body:  ServiceUpdateRequest,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    user:  dict = Depends(require_teknisi_or_owner),
):
    """
    Update tiket service oleh teknisi.
    - Antrian → Proses (teknisi ambil pekerjaan)
    - Proses  → Selesai (teknisi selesai, nunggu approval kasir/owner)
    - Proses  → Ditolak (HP tidak bisa diperbaiki)
    
    Teknisi TIDAK bisa set status Approved.
    Approved hanya lewat POST /units/{unit_id}/approve-repair
    """
    item = await service_service.update_service(
        db, service_id, body,
        actor=user["name"],
        actor_role=user.get("role", ""),
    )
    return ok(item.model_dump(), message="Service berhasil diupdate")


@router.post("/{service_id}/foto")
async def add_foto_url(
    service_id: str,
    body:  FotoUrlRequest,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    user:  dict = Depends(require_teknisi_or_owner),
):
    """Simpan URL foto dari layanan eksternal (ImgBB, Cloudinary, dll)."""
    item = await service_service.add_foto_url(db, service_id, body.url, actor=user["name"])
    return ok(item.model_dump(), message="Foto berhasil ditambahkan")
