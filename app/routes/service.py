from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

from app.config.database import get_db
from app.schemas.service import ServiceUpdateRequest, ServiceUseSparepartRequest
from app.schemas.common import ok
from app.services import service_service
from app.middlewares.auth import require_teknisi_or_owner, require_any, require_kasir_teknisi_or_owner, require_kepala_or_owner

router = APIRouter(prefix="/service", tags=["Service"])


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
    # Tabel Antrian teknisi menampilkan IMEI di kolom "HP/IMEI" — di-join di
    # sini (bulk, satu query) daripada menambah field ke ServiceResponse,
    # supaya schema list tetap ringan dan tidak dipakai endpoint lain.
    unit_ids = [i.unit_id for i in items if i.unit_id]
    units_by_id: dict = {}
    if unit_ids:
        async for u in db.units.find({"unit_id": {"$in": unit_ids}}, {"unit_id": 1, "imei": 1}):
            units_by_id[u["unit_id"]] = u.get("imei", "")
    dumped = []
    for i in items:
        d = i.model_dump()
        d["imei"] = units_by_id.get(i.unit_id, "")
        dumped.append(d)
    return ok(dumped)


@router.get("/riwayat")
async def service_riwayat(
    cabang: Optional[str] = Query(None),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_any),
):
    """Riwayat servis Selesai — sudut pandang tiket, tidak transien. Rute ini
    HARUS terdaftar sebelum /{service_id} supaya "riwayat" tidak ketangkap
    sebagai path param."""
    cab = _cabang_filter(user, cabang)
    items = await service_service.list_service_riwayat(db, cabang=cab)
    return ok([i.model_dump() for i in items])


@router.get("/pending-approval")
async def pending_approval(
    cabang: Optional[str] = Query(None),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kasir_teknisi_or_owner),
):
    cab = _cabang_filter(user, cabang)
    items = await service_service.list_service(db, cabang=cab, status="Selesai", limit=500)
    return ok([i.model_dump() for i in items])


@router.get("/{service_id}")
async def get_service(
    service_id: str,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_any),
):
    item = await service_service.get_service(db, service_id)
    if user.get("role") != "owner" and item.cabang != user.get("cabang"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Bukan hak anda untuk melihat service ini")
    return ok(item.model_dump())


@router.put("/{service_id}")
async def update_service(
    service_id: str,
    body:  ServiceUpdateRequest,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    user:  dict = Depends(require_teknisi_or_owner),
):
    # Kurir tidak boleh update service — role mereka adalah COD delivery
    if user.get("role") == "kurir":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Kurir tidak bisa update service")
    item = await service_service.update_service(
        db, service_id, body,
        actor=user.get("name", user.get("username", "")),
        actor_role=user.get("role", ""),
        user_cabang=user.get("cabang", ""),
    )
    return ok(item.model_dump(), message="Service berhasil diupdate")


@router.post("/{service_id}/sparepart")
async def use_sparepart(
    service_id: str,
    body:  ServiceUseSparepartRequest,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    user:  dict = Depends(require_teknisi_or_owner),
):
    """Teknisi pakai sparepart yang sudah ada di stok cabang, langsung, selagi servis Proses."""
    item = await service_service.use_sparepart(
        db, service_id, body,
        actor=user.get("name", user.get("username", "")),
        actor_role=user.get("role", ""),
    )
    return ok(item.model_dump(), message=f"{body.sp_id} ditambahkan ke servis {service_id}")


@router.delete("/{service_id}/sparepart/{sp_id}")
async def remove_sparepart(
    service_id: str,
    sp_id: str,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    user:  dict = Depends(require_teknisi_or_owner),
):
    """Batalkan satu pemakaian sparepart yang salah pilih, sebelum servis Selesai."""
    item = await service_service.remove_sparepart(
        db, service_id, sp_id,
        actor=user.get("name", user.get("username", "")),
        actor_role=user.get("role", ""),
    )
    return ok(item.model_dump(), message=f"{sp_id} dibatalkan dari servis {service_id}")


@router.get("/{service_id}/detail")
async def service_detail(
    service_id: str,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    user:  dict = Depends(require_any),
):
    """Return service with before/after photos and timeline."""
    from fastapi import HTTPException
    doc = await db.service.find_one({"service_id": service_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Service {service_id} tidak ditemukan")
    if user.get("role") != "owner" and doc.get("cabang") != user.get("cabang"):
        raise HTTPException(status_code=403, detail="Bukan hak anda untuk melihat service ini")
    item = service_service._fmt(doc)
    data = item.model_dump()
    # Layar detail read-only (Pilih HP) butuh warna/kondisi/kelengkapan unit —
    # field itu tidak ada di ServiceResponse, jadi di-join manual di sini saja
    # (bukan di list_service, supaya list tetap ringan).
    unit = await db.units.find_one({"unit_id": doc.get("unit_id", "")}) if doc.get("unit_id") else None
    data["warna"] = unit.get("warna", "-") if unit else "-"
    data["kondisi"] = unit.get("kondisi", "-") if unit else "-"
    data["kelengkapan"] = unit.get("kelengkapan", "-") if unit else "-"
    data["imei"] = unit.get("imei", "-") if unit else "-"
    # Add timeline from status history if available
    data["timeline"] = []
    if doc.get("created_at"):
        data["timeline"].append({"event": "Dibuat", "waktu": str(doc["created_at"])})
    if doc.get("updated_at"):
        data["timeline"].append({"event": f"Status → {doc.get('status', '')}", "waktu": str(doc["updated_at"])})
    return ok(data)
