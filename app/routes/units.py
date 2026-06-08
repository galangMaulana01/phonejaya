from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.database import get_db
from app.schemas.unit import UnitCreateRequest, ApproveRepairRequest
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
    """List semua unit. Bisa filter by status & cabang."""
    units = await unit_service.list_units(db, cabang=cabang, status_filter=status)
    return ok([u.model_dump() for u in units])


@router.post("", status_code=201)
async def create_unit(
    body: UnitCreateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_or_owner),
):
    """
    Input HP baru dari penjual.
    - kondisi_hp = Mulus  → langsung ke stok Tersedia
    - kondisi_hp = Repair → masuk antrian service teknisi

    Unit LANGSUNG di-lock setelah posting.
    Tidak ada endpoint edit unit.
    """
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
    user:    dict = Depends(require_kasir_or_owner),
):
    """
    Kasir / Owner menetapkan harga jual setelah teknisi selesai repair.
    Unit akan pindah ke stok Tersedia.
    Syarat: status tiket service harus 'Selesai' dulu.
    """
    unit = await unit_service.approve_repair(db, unit_id, body, actor=user.get("name", user.get("username", "")))
    return ok(
        unit.model_dump(),
        message=f"Unit {unit_id} disetujui → masuk stok Tersedia"
    )


# ─────────────────────────────────────────────────────────────────
# TIDAK ADA endpoint PUT/PATCH/DELETE untuk unit.
# Unit bersifat immutable setelah diposting (locked=True).
# Perubahan hanya melalui alur bisnis resmi:
#   - Penjualan  → POST /transaksi
#   - Repair     → POST /service (auto) → POST /units/{id}/approve-repair
# ─────────────────────────────────────────────────────────────────
