from datetime import datetime, timezone, timedelta
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException

from app.schemas.service import (
    ServiceUpdateRequest, ServiceResponse, StatusServiceEnum, ServiceUseSparepartRequest
)
from app.utils.formatters import fmt_waktu
from app.services.sparepart import kurangi_stok_batch as sp_kurangi_stok_batch
from app.services.log_service import write_log


def _fmt(doc: dict) -> ServiceResponse:
    # Pakai .get(field) or default di semua field — bukan .get(field, default),
    # karena .get(field, default) hanya fallback kalau field-nya BENAR-BENAR TIDAK ADA;
    # kalau field ada tapi nilainya None (mis. teknisi belum ditugaskan dan tersimpan
    # sebagai null bukan ""), .get() tetap mengembalikan None dan bikin ServiceResponse
    # (yang mewajibkan str/list, bukan Optional) gagal validasi -> 500 untuk seluruh list.
    return ServiceResponse(
        id=str(doc["_id"]),
        service_id=doc.get("service_id") or str(doc["_id"]),
        unit_id=doc.get("unit_id") or "",
        unit_label=doc.get("unit_label") or "",
        nama_customer=doc.get("nama_customer") or "",
        kontak_customer=doc.get("kontak_customer") or "",
        keluhan=doc.get("keluhan") or "",
        catatan_kerusakan=doc.get("catatan_kerusakan") or "",
        status=doc.get("status") or "Antrian",
        teknisi=doc.get("teknisi") or "",
        foto_urls=doc.get("foto_urls") or [],
        cabang=doc.get("cabang") or "",
        estimasi_selesai=doc.get("estimasi_selesai"),
        created_at=fmt_waktu(doc["created_at"]) if doc.get("created_at") else "",
        updated_at=fmt_waktu(doc["updated_at"]) if doc.get("updated_at") else None,
        foto_before_urls=doc.get("foto_before_urls") or [],
        foto_after_urls=doc.get("foto_after_urls") or [],
        sparepart_items=doc.get("sparepart_items") or [],
    )


async def list_service(
    db,
    cabang: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
) -> List[ServiceResponse]:
    query: dict = {}
    if cabang:
        query["cabang"] = cabang
    if status:
        query["status"] = status
    if date_from or date_to:
        wf: dict = {}
        if date_from:
            wf["$gte"] = datetime.fromisoformat(date_from.replace("Z", "")).replace(tzinfo=timezone.utc)
        if date_to:
            # Make date_to inclusive by adding 1 day
            dt = datetime.fromisoformat(date_to.replace("Z", "")).replace(tzinfo=timezone.utc) + timedelta(days=1)
            wf["$lt"] = dt
        query["created_at"] = wf
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
    user_cabang: str = "",
) -> ServiceResponse:
    doc = await db.service.find_one({"service_id": service_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Service {service_id} tidak ditemukan")

    # Non-owner hanya bisa update service milik cabangnya sendiri
    if actor_role != "owner":
        if doc.get("cabang") != user_cabang:
            raise HTTPException(status_code=403, detail="Bukan hak anda untuk update service ini")

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

        if new_status == "Proses" and not payload.estimasi_selesai:
            raise HTTPException(status_code=422, detail="Estimasi selesai wajib diisi saat mengubah status ke Proses")

        # Atomic claim on the transition: only one concurrent request can move
        # this ticket out of `current_status`. The loser gets a 409 instead of
        # both proceeding to decrement sparepart stock for the same repair.
        claimed = await db.service.find_one_and_update(
            {"service_id": service_id, "status": current_status},
            {"$set": {"status": new_status, "updated_at": updates["updated_at"]}},
        )
        if not claimed:
            raise HTTPException(
                status_code=409,
                detail="Status service sudah berubah oleh proses lain, silakan refresh.",
            )
        updates["status"] = new_status

        # Kalau Ditolak → update unit kembali ke status khusus
        if new_status == "Ditolak":
            await db.units.update_one(
                {"unit_id": doc["unit_id"]},
                {"$set": {"status": "Ditolak", "updated_at": datetime.now(timezone.utc)}}
            )

        # Kalau Selesai → kurangi stok sparepart yang dipakai, dan tambahkan
        # biayanya ke harga_modal unit (konvensi sama seperti approve_request
        # di request_sparepart_service.py: delta = harga_jual x jumlah).
        if new_status == "Selesai":
            sp_items = doc.get("sparepart_items", [])
            if sp_items:
                # Only the items kurangi_stok_batch actually deducted count
                # toward the unit's modal cost — billing for a deduction that
                # was logged as failed (insufficient stock, e.g. another
                # ticket already claimed it) would overstate the unit's cost
                # against inventory that was never actually taken.
                deducted_items = await sp_kurangi_stok_batch(
                    db, items=sp_items, actor=actor, cabang=doc.get("cabang", "")
                )
                total_delta = 0
                for item in deducted_items:
                    sp = await db.sparepart.find_one({"sp_id": item["sp_id"], "cabang": doc.get("cabang", "")})
                    if sp:
                        total_delta += sp.get("harga_jual", 0) * item["jumlah"]
                if total_delta:
                    await db.units.update_one(
                        {"unit_id": doc["unit_id"]},
                        {"$inc": {"harga_modal": total_delta}, "$set": {"updated_at": datetime.now(timezone.utc)}}
                    )
                    await write_log(
                        db, actor, "Update Modal Sparepart (Servis)",
                        f"Unit {doc['unit_id']} modal +Rp{total_delta:,} dari {len(deducted_items)} sparepart servis {service_id}",
                        doc.get("cabang", "")
                    )

    if payload.catatan_kerusakan is not None:
        updates["catatan_kerusakan"] = payload.catatan_kerusakan

    if payload.foto_before_urls is not None:
        updates["foto_before_urls"] = payload.foto_before_urls

    if payload.foto_after_urls is not None:
        updates["foto_after_urls"] = payload.foto_after_urls

    if payload.estimasi_selesai:
        updates["estimasi_selesai"] = payload.estimasi_selesai

    if payload.teknisi is not None:
        updates["teknisi"] = payload.teknisi
    elif not doc.get("teknisi") and actor_role == "teknisi":
        # Auto-assign teknisi yang pertama ambil
        updates["teknisi"] = actor

    if payload.link_shopee is not None:
        updates["link_shopee"] = payload.link_shopee

    await db.service.update_one({"service_id": service_id}, {"$set": updates})
    updated = await db.service.find_one({"service_id": service_id})

    await write_log(
        db, actor, "Update Service",
        f"{service_id} → {updates.get('status', 'update catatan')}",
        doc.get("cabang", "")
    )
    return _fmt(updated)


async def use_sparepart(
    db, service_id: str, payload: ServiceUseSparepartRequest, actor: str, actor_role: str,
) -> ServiceResponse:
    """Teknisi pakai sparepart yang sudah ada di stok cabang selagi servis
    masih Proses — dicatat di sparepart_items, stok baru benar-benar
    dikurangi (dan modal unit ditambah) saat tiket ini di-set Selesai
    (lihat update_service di atas), supaya konsisten dengan satu titik
    pengurangan stok yang sudah ada, dan gampang di-'remove_sparepart' lagi
    kalau teknisi salah pilih sebelum servis selesai.
    """
    doc = await db.service.find_one({"service_id": service_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Service {service_id} tidak ditemukan")
    if actor_role != "owner" and doc.get("teknisi") != actor:
        raise HTTPException(status_code=403, detail="Hanya teknisi yang mengerjakan servis ini yang bisa pakai sparepart")
    if doc.get("status") != "Proses":
        raise HTTPException(status_code=400, detail="Sparepart hanya bisa dipakai selagi servis berstatus Proses")

    sp = await db.sparepart.find_one({"sp_id": payload.sp_id, "cabang": doc.get("cabang", "")})
    if not sp:
        raise HTTPException(status_code=404, detail=f"Sparepart {payload.sp_id} tidak ditemukan di cabang ini")

    # Early feedback against stok yang sekarang tersedia, dikurangi dulu
    # dengan apa yang sudah "dijatah" tiket ini sendiri untuk sp_id yang
    # sama — pengecekan final &amp; atomik yang sebenarnya tetap di
    # kurangi_stok_batch saat status berubah ke Selesai.
    already_used = sum(i["jumlah"] for i in doc.get("sparepart_items", []) if i["sp_id"] == payload.sp_id)
    if sp.get("stok", 0) - already_used < payload.jumlah:
        raise HTTPException(
            status_code=400,
            detail=f"Stok {sp['nama']} tidak cukup. Tersedia: {sp.get('stok', 0) - already_used}, diminta: {payload.jumlah}"
        )

    # Merge into the existing line for this sp_id (if any) instead of
    # pushing a duplicate entry, so each sparepart appears at most once and
    # removing it later is unambiguous.
    items = doc.get("sparepart_items", [])
    existing = next((i for i in items if i["sp_id"] == sp["sp_id"]), None)
    if existing:
        existing["jumlah"] += payload.jumlah
    else:
        items.append({"sp_id": sp["sp_id"], "nama": sp["nama"], "jumlah": payload.jumlah, "harga_jual": sp.get("harga_jual", 0)})
    await db.service.update_one(
        {"service_id": service_id},
        {"$set": {"sparepart_items": items, "updated_at": datetime.now(timezone.utc)}}
    )
    await write_log(db, actor, "Pakai Sparepart Servis", f"{service_id} → {sp['nama']} x{payload.jumlah}", doc.get("cabang", ""))
    updated = await db.service.find_one({"service_id": service_id})
    return _fmt(updated)


async def remove_sparepart(
    db, service_id: str, sp_id: str, actor: str, actor_role: str,
) -> ServiceResponse:
    """Batalkan satu pemakaian sparepart yang salah pilih, sebelum tiket Selesai."""
    doc = await db.service.find_one({"service_id": service_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Service {service_id} tidak ditemukan")
    if actor_role != "owner" and doc.get("teknisi") != actor:
        raise HTTPException(status_code=403, detail="Hanya teknisi yang mengerjakan servis ini yang bisa mengubah pemakaian sparepart")
    if doc.get("status") != "Proses":
        raise HTTPException(status_code=400, detail="Pemakaian sparepart hanya bisa diubah selagi servis berstatus Proses")

    items = doc.get("sparepart_items", [])
    idx = next((i for i, it in enumerate(items) if it["sp_id"] == sp_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"{sp_id} tidak ada di daftar pemakaian tiket ini")
    items.pop(idx)
    await db.service.update_one(
        {"service_id": service_id},
        {"$set": {"sparepart_items": items, "updated_at": datetime.now(timezone.utc)}}
    )
    await write_log(db, actor, "Batalkan Pakai Sparepart Servis", f"{service_id} → {sp_id}", doc.get("cabang", ""))
    updated = await db.service.find_one({"service_id": service_id})
    return _fmt(updated)
