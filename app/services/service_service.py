from datetime import datetime, timezone, timedelta
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException

from app.schemas.service import (
    ServiceUpdateRequest, ServiceResponse, StatusServiceEnum, ServiceUseSparepartRequest
)
from app.utils.formatters import fmt_waktu
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

        # Kalau Selesai → tambahkan biaya sparepart yang dipakai ke harga_modal
        # unit (konvensi sama seperti approve_request di
        # request_sparepart_service.py: delta = harga_jual x jumlah). Stoknya
        # sendiri SUDAH dipotong atomik sejak teknisi memilihnya lewat
        # use_sparepart — tidak ada lagi pengurangan stok di titik ini.
        if new_status == "Selesai":
            sp_items = doc.get("sparepart_items", [])
            if sp_items:
                total_delta = 0
                for item in sp_items:
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
                        f"Unit {doc['unit_id']} modal +Rp{total_delta:,} dari {len(sp_items)} sparepart servis {service_id}",
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
    """Teknisi ambil sparepart dari stok cabang untuk servis ini selagi servis
    masih Proses. Stok dipotong ATOMIK DAN LANGSUNG di sini — bukan ditunda
    sampai tiket di-set Selesai — supaya dua tiket yang rebutan sisa stok
    yang sama saling ditolak tepat di titik pemilihan (dapat error stok
    tidak cukup seketika), bukan salah satunya diam-diam gagal dipotong
    belakangan sementara modal unit tetap kena tagihan (lihat audit
    multi-role: bug overcommit sparepart).
    """
    doc = await db.service.find_one({"service_id": service_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Service {service_id} tidak ditemukan")
    if actor_role != "owner" and doc.get("teknisi") != actor:
        raise HTTPException(status_code=403, detail="Hanya teknisi yang mengerjakan servis ini yang bisa pakai sparepart")
    if doc.get("status") != "Proses":
        raise HTTPException(status_code=400, detail="Sparepart hanya bisa dipakai selagi servis berstatus Proses")

    cabang = doc.get("cabang", "")
    now = datetime.now(timezone.utc)

    existing_sp = await db.sparepart.find_one({"sp_id": payload.sp_id, "cabang": cabang})
    if not existing_sp:
        raise HTTPException(status_code=404, detail=f"Sparepart {payload.sp_id} tidak ditemukan di cabang ini")
    if existing_sp.get("jenis") not in (None, "repair"):
        raise HTTPException(
            status_code=400,
            detail=f"{existing_sp['nama']} adalah sparepart untuk dijual, bukan untuk repair — tidak bisa dipakai di sini"
        )

    # Atomic claim: only succeeds if real stok >= jumlah right now.
    sp = await db.sparepart.find_one_and_update(
        {"sp_id": payload.sp_id, "cabang": cabang, "stok": {"$gte": payload.jumlah}},
        {"$inc": {"stok": -payload.jumlah}, "$set": {"updated_at": now}},
        return_document=True,
    )
    if not sp:
        raise HTTPException(
            status_code=400,
            detail=f"Stok {existing_sp['nama']} tidak cukup. Tersedia: {existing_sp.get('stok', 0)}, diminta: {payload.jumlah}"
        )

    # Merge into the existing line for this sp_id (if any) instead of
    # pushing a duplicate entry, so each sparepart appears at most once and
    # removing it later is unambiguous. Keep the ORIGINAL mulai_pakai when
    # merging — it reflects when this part was first picked, not the latest
    # top-up.
    items = doc.get("sparepart_items", [])
    existing = next((i for i in items if i["sp_id"] == sp["sp_id"]), None)
    if existing:
        existing["jumlah"] += payload.jumlah
    else:
        items.append({
            "sp_id": sp["sp_id"], "nama": sp["nama"], "jumlah": payload.jumlah,
            "harga_jual": sp.get("harga_jual", 0), "mulai_pakai": now,
        })
    await db.service.update_one(
        {"service_id": service_id},
        {"$set": {"sparepart_items": items, "updated_at": now}}
    )
    await write_log(db, actor, "Pakai Sparepart Servis", f"{service_id} → {sp['nama']} x{payload.jumlah} (stok tersisa: {sp['stok']})", cabang)
    updated = await db.service.find_one({"service_id": service_id})
    return _fmt(updated)


async def remove_sparepart(
    db, service_id: str, sp_id: str, actor: str, actor_role: str,
) -> ServiceResponse:
    """Batalkan satu pemakaian sparepart yang salah pilih, sebelum tiket
    Selesai — stok yang sudah dipotong atomik oleh use_sparepart dikembalikan
    penuh."""
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
    removed = items.pop(idx)
    now = datetime.now(timezone.utc)
    await db.sparepart.update_one(
        {"sp_id": sp_id, "cabang": doc.get("cabang", "")},
        {"$inc": {"stok": removed["jumlah"]}, "$set": {"updated_at": now}}
    )
    await db.service.update_one(
        {"service_id": service_id},
        {"$set": {"sparepart_items": items, "updated_at": now}}
    )
    await write_log(db, actor, "Batalkan Pakai Sparepart Servis", f"{service_id} → {sp_id} x{removed['jumlah']} (stok dikembalikan)", doc.get("cabang", ""))
    updated = await db.service.find_one({"service_id": service_id})
    return _fmt(updated)
