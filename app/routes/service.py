from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel
from app.config.database import get_db
from app.schemas.service import ServiceCreateRequest, ServiceUpdateRequest
from app.schemas.common import ok
from app.services import service_service
from app.middlewares.auth import require_teknisi_or_owner, require_any

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
    items = await service_service.list_service(db, cabang=cabang, status=status, limit=limit)
    return ok([i.model_dump() for i in items])


@router.get("/{service_id}")
async def get_service(
    service_id: str,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    _user: dict = Depends(require_any),
):
    item = await service_service.get_service(db, service_id)
    return ok(item.model_dump())


@router.post("", status_code=201)
async def create_service(
    body:  ServiceCreateRequest,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    user:  dict = Depends(require_teknisi_or_owner),
):
    item = await service_service.create_service(db, body, actor=user["name"])
    return ok(item.model_dump(), message="Service berhasil dicatat")


@router.put("/{service_id}")
async def update_service(
    service_id: str,
    body:  ServiceUpdateRequest,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    user:  dict = Depends(require_teknisi_or_owner),
):
    item = await service_service.update_service(db, service_id, body, actor=user["name"])
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
    return ok(item.model_dump(), message="Foto URL berhasil ditambahkan")
