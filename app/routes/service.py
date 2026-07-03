from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config.database import get_db
from app.schemas.service import ServiceUpdateRequest
from app.schemas.common import ok
from app.services import service_service
from app.middlewares.auth import require_teknisi_or_owner, require_any, require_kasir_or_owner, require_kepala_or_owner

router = APIRouter(prefix="/service", tags=["Service"])


class FotoUrlRequest(BaseModel):
    url: str


def _cabang_filter(user: dict, cabang_param: Optional[str]) -> Optional[str]:
    if user.get("role") == "owner":
        return cabang_param
    return user.get("cabang")


@router.get("")
async def list_service(
    cabang: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    limit:  int = Query(100, ge=1, le=500),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_any),
):
    cab = _cabang_filter(user, cabang)
    items = await service_service.list_service(db, cabang=cab, status=status, date_from=date_from, date_to=date_to, limit=limit)
    return ok([i.model_dump() for i in items])


@router.get("/pending-approval")
async def pending_approval(
    cabang: Optional[str] = Query(None),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kasir_or_owner),
):
    cab = _cabang_filter(user, cabang)
    items = await service_service.list_service(db, cabang=cab, status="Selesai", limit=500)
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
    item = await service_service.update_service(
        db, service_id, body,
        actor=user.get("name", user.get("username", "")),
        actor_role=user.get("role", ""),
        user_cabang=user.get("cabang", ""),
    )
    return ok(item.model_dump(), message="Service berhasil diupdate")


@router.post("/{service_id}/foto")
async def add_foto_url(
    service_id: str,
    body:  FotoUrlRequest,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    user:  dict = Depends(require_teknisi_or_owner),
):
    item = await service_service.add_foto_url(db, service_id, body.url, actor=user.get("name", user.get("username", "")))
    return ok(item.model_dump(), message="Foto berhasil ditambahkan")
