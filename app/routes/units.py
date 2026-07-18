from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.database import get_db
from app.schemas.unit import UnitCreateRequest, ApproveRepairRequest
from app.schemas.common import ok
from app.services import unit_service
from app.middlewares.auth import require_kasir_teknisi_or_owner, require_kepala_or_owner, require_any

router = APIRouter(prefix="/units", tags=["Units"])


def _cabang_filter(user: dict, cabang_param: Optional[str]) -> Optional[str]:
    """Owner bisa lihat semua/filter bebas. Kepala cabang hanya cabangnya."""
    if user.get("role") == "owner":
        return cabang_param  # bisa None (semua) atau spesifik
    return user.get("cabang")  # kepala_cabang, kasir, teknisi → paksa cabangnya


@router.get("")
async def list_units(
    cabang: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    q:      Optional[str] = Query(None),
    limit:  int = Query(200, ge=1, le=500),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kasir_teknisi_or_owner),
):
    cab = _cabang_filter(user, cabang)
    units = await unit_service.list_units(db, cabang=cab, status_filter=status, q=q, limit=limit)
    result = [u.model_dump() for u in units]
    if user.get('role') == 'teknisi':
        for item in result:
            item.pop('harga_modal', None)
    return ok(result)


@router.post("", status_code=201)
async def create_unit(
    body: UnitCreateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    unit = await unit_service.create_unit(db, body, actor=user.get("name", user.get("username", "")))
    msg = (
        f"Unit {unit.unit_id} berhasil diposting → Stok Tersedia"
        if unit.kondisi_hp == "Mulus"
        else f"Unit {unit.unit_id} berhasil diposting → Antrian Service ({unit.service_id})"
    )
    return ok(unit.model_dump(), message=msg)


@router.post("/{unit_id}/approve-repair", status_code=200)
async def approve_repair(
    unit_id: str,
    body:    ApproveRepairRequest,
    db:      AsyncIOMotorDatabase = Depends(get_db),
    user:    dict = Depends(require_kasir_teknisi_or_owner),
):
    # Only kasir, kepala_cabang, owner can approve — not teknisi
    if user.get("role") == "teknisi":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Teknisi tidak bisa approve repair")
    unit = await unit_service.approve_repair(db, unit_id, body, actor=user.get("name", user.get("username", "")))
    return ok(unit.model_dump(), message=f"Unit {unit_id} disetujui → masuk stok Tersedia")


@router.get("/{unit_id}/detail")
async def unit_detail(
    unit_id: str,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    """Return full unit info including photo URL."""
    from fastapi import HTTPException
    doc = await db.units.find_one({"unit_id": unit_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Unit {unit_id} tidak ditemukan")
    unit = unit_service._fmt(doc)
    data = unit.model_dump()
    # Hide harga_modal from teknisi
    if user.get("role") == "teknisi":
        data.pop("harga_modal", None)
    return ok(data)
