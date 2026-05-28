from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.unit import UnitCreateRequest, UnitUpdateRequest
from app.schemas.common import ok
from app.services import unit_service
from app.middlewares.auth import require_owner, require_kasir_or_owner, require_any

router = APIRouter(prefix="/units", tags=["Units"])


@router.get("")
async def list_units(
    cabang: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    _user:  dict = Depends(require_any),
):
    units = await unit_service.list_units(db, cabang=cabang, status_filter=status)
    return ok([u.model_dump() for u in units])


@router.post("", status_code=201)
async def create_unit(
    body: UnitCreateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_or_owner),
):
    unit = await unit_service.create_unit(db, body, actor=user["name"])
    return ok(unit.model_dump(), message="Unit berhasil ditambahkan")


@router.put("/{unit_id}")
async def update_unit(
    unit_id: str,
    body:    UnitUpdateRequest,
    db:      AsyncIOMotorDatabase = Depends(get_db),
    user:    dict = Depends(require_kasir_or_owner),
):
    # Kasir tidak bisa edit harga modal
    if user.get("role") == "kasir" and body.harga_modal is not None:
        raise HTTPException(status_code=403, detail="Kasir tidak bisa mengubah harga modal.")
    unit = await unit_service.update_unit(db, unit_id, body, actor=user["name"])
    return ok(unit.model_dump(), message="Unit berhasil diupdate")
