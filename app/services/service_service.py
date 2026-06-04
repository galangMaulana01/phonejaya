from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException

from app.schemas.service import (
    ServiceUpdateRequest, ServiceResponse, StatusServiceEnum
)
from app.utils.formatters import fmt_waktu
from app.services import sparepart_service
from app.services.log_service import write_log


def _fmt(doc: dict) -> ServiceResponse:
    # Pakai .get() dengan fallback di semua field
    # agar dokumen lama yang tidak punya field tertentu tidak crash KeyError
    return ServiceResponse(
        id=str(doc["_id"]),
        service_id=doc.get("service_id", str(doc["_id"])),
        unit_id=doc.get("unit_id", ""),
        unit_label=doc.get("unit_label", ""),
        nama_customer=doc.get("nama_customer", ""),
        kontak_customer=doc.get("kontak_customer", ""),
        keluhan=doc.get("keluhan", ""),
        catatan_kerusakan=doc.get("catatan_kerusakan", ""),
        status=doc.get("status", "Antrian"),
        teknisi=doc.get("teknisi", ""),
        foto_urls=doc.get("foto_urls", []),
        cabang=doc.get("cabang", ""),
        created_at=fmt_waktu(doc["created_at"]) if doc.get("created_at") else "",
        updated_at=fmt_waktu(doc["updated_at"]) if doc.get("updated_at") else None,
    )


async def list_service(
    db,
    cabang: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[ServiceResponse]:
    query: dict = {}
    if cabang:
        query["cabang"] = cabang
    if status:
        query["status"] = status
    docs = await db.service.find(query).sort("created_at", -1).limit(limit).to_list(length=limit)
    return [_fmt(d) for d in docs]


async def get_service(db, service_id: str) -> ServiceResponse:
    doc = await db.service.find_one({"service_id": service_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Service {service_id} tidak ditemukan")
    return _fmt(doc)


async def update_service(
    db,
    service_id: str,
    payload: ServiceUpdateRequest,
    actor: str,
    actor_role: str,
) -> ServiceResponse:
    """
    Hanya teknisi yang bisa update status & catatan.
    Status yang bisa diset teknisi: Proses, Selesai.
    Status Approved hanya bisa dari endpoint approve_repair di unit.
    Status Ditolak bisa teknisi set (hp tidak bisa diperbaiki).
    """
    doc = await db.service.find_one({"service_id": service_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Service {service_id} tidak ditemukan")

    # Approved hanya bisa lewat endpoint approve_repair
    if payload.status == StatusServiceEnum.approved:
        raise HTTPException(
            status_code=403,
            detail="Status Approved hanya bisa di-set lewat proses approval kasir/owner."
        )

    # Cek status saat ini
    current_status = doc.get("status")
    if current_status == "Approved":
        raise HTTPException(
            status_code=400,
            detail="Tiket sudah Approved dan unit sudah masuk stok. Tidak bisa diubah."
        )

    updates: dict = {"updated_at": datetime.now(timezone.utc)}

    if payload.status is not None:
        new_status = payload.status.value

        # Validasi transisi status yang valid
        valid_transitions = {
            "Antrian": ["Proses", "Ditolak"],
            "Proses":  ["Selesai", "Ditolak"],
            "Selesai": [],          # hanya bisa Approved lewat approve_repair
            "Ditolak": [],
        }
        allowed = valid_transitions.get(current_status, [])
        if new_status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Tidak bisa pindah dari '{current_status}' ke '{new_status}'. "
                       f"Transisi yang diizinkan: {allowed if allowed else 'tidak ada'}"
            )

        updates["status"] = new_status

        # Kalau Ditolak → update unit kembali ke status khusus
        if new_status == "Ditolak":
            await db.units.update_one(
                {"unit_id": doc["unit_id"]},
                {"$set": {"status": "Ditolak", "updated_at": datetime.now(timezone.utc)}}
            )

        # Kalau Selesai → kurangi stok sparepart yang dipakai
        if new_status == "Selesai":
            sp_items = doc.get("sparepart_items", [])
            if sp_items:
                await sparepart_service.kurangi_stok_batch(
                    db, items=sp_items, actor=actor, cabang=doc.get("cabang", "")
                )

    if payload.catatan_kerusakan is not None:
        updates["catatan_kerusakan"] = payload.catatan_kerusakan

    if payload.teknisi is not None:
        updates["teknisi"] = payload.teknisi
    elif not doc.get("teknisi") and actor_role == "teknisi":
        # Auto-assign teknisi yang pertama ambil
        updates["teknisi"] = actor

    await db.service.update_one({"service_id": service_id}, {"$set": updates})
    updated = await db.service.find_one({"service_id": service_id})

    await write_log(
        db, actor, "Update Service",
        f"{service_id} → {updates.get('status', 'update catatan')}",
        doc.get("cabang", "")
    )
    return _fmt(updated)


async def add_foto_url(
    db,
    service_id: str,
    url: str,
    actor: str,
) -> ServiceResponse:
    doc = await db.service.find_one({"service_id": service_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Service {service_id} tidak ditemukan")

    if doc.get("status") in ("Approved", "Ditolak"):
        raise HTTPException(
            status_code=400,
            detail="Tidak bisa upload foto untuk tiket yang sudah selesai."
        )

    await db.service.update_one(
        {"service_id": service_id},
        {
            "$push": {"foto_urls": url},
            "$set":  {"updated_at": datetime.now(timezone.utc)},
        },
    )
    updated = await db.service.find_one({"service_id": service_id})
    await write_log(db, actor, "Upload Foto Service", service_id, doc.get("cabang", ""))
    return _fmt(updated)
