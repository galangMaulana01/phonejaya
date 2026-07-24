from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException

from app.schemas.request_sparepart import (
    RequestSparepartCreateRequest, RequestSparepartResponseRequest, RequestSparepartResponse,
    RequestSparepartApproveRequest, StatusRequestEnum
)
from app.services.log_service import write_log
from app.utils.formatters import fmt_waktu
from app.services.sparepart import create_sparepart
from app.schemas.sparepart import SparepartCreateRequest


def _fmt(doc: dict) -> RequestSparepartResponse:
    return RequestSparepartResponse(
        id=str(doc["_id"]), req_id=doc.get("req_id", str(doc["_id"])),
        tipe=doc.get("tipe",""), sp_id=doc.get("sp_id"),
        nama_sp=doc.get("nama_sp",""), jumlah=doc.get("jumlah",1),
        keterangan=doc.get("keterangan",""), status=doc.get("status","Pending"),
        estimasi_tiba=doc.get("estimasi_tiba"), catatan_kc=doc.get("catatan_kc",""),
        harga_jual=doc.get("harga_jual"),
        cabang=doc.get("cabang",""), dibuat_oleh=doc.get("dibuat_oleh",""),
        disetujui_oleh_kc=doc.get("disetujui_oleh_kc"),
        disetujui_at_kc=fmt_waktu(doc["disetujui_at_kc"]) if doc.get("disetujui_at_kc") else None,
        approved_by=doc.get("approved_by"),
        approved_at=fmt_waktu(doc["approved_at"]) if doc.get("approved_at") else None,
        created_at=fmt_waktu(doc["created_at"]) if doc.get("created_at") else "",
        updated_at=fmt_waktu(doc["updated_at"]) if doc.get("updated_at") else None,
    )


async def _next_req_id(db) -> str:
    res = await db.counters.find_one_and_update(
        {"_id": "REQ_SP"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True,
    )
    return f"REQ-SP-{str(res['seq']).zfill(3)}"


async def list_requests(db, cabang=None, status=None) -> List[RequestSparepartResponse]:
    query: dict = {}
    if cabang: query["cabang"] = cabang
    if status: query["status"] = status
    docs = await db.request_sparepart.find(query).sort("created_at", -1).to_list(length=100)
    return [_fmt(d) for d in docs]


async def create_request(db, payload: RequestSparepartCreateRequest, actor: str) -> RequestSparepartResponse:
    req_id = await _next_req_id(db)
    now    = datetime.now(timezone.utc)
    doc    = {
        "req_id": req_id, "tipe": payload.tipe, "sp_id": payload.sp_id,
        "nama_sp": payload.nama_sp, "jumlah": payload.jumlah,
        "keterangan": payload.keterangan, "status": "Pending",
        "estimasi_tiba": None, "catatan_kc": "",
        "harga_jual": None,
        "product_link": payload.product_link,
        "cabang": payload.cabang, "dibuat_oleh": actor,
        "disetujui_oleh_kc": None, "disetujui_at_kc": None,
        "approved_by": None, "approved_at": None,
        "created_at": now, "updated_at": None,
    }
    res = await db.request_sparepart.insert_one(doc)
    doc["_id"] = res.inserted_id
    await write_log(db, actor, "Request Sparepart", f"{req_id} • {payload.nama_sp} x{payload.jumlah}", payload.cabang)
    return _fmt(doc)


async def respond_request(
    db, req_id: str, payload: RequestSparepartResponseRequest,
    actor: str, actor_role: str = '', actor_cabang: str = ''
) -> RequestSparepartResponse:
    """Kepala Cabang respond: if Diterima -> status Menunggu_Kasir, if Ditolak -> Ditolak."""
    doc = await db.request_sparepart.find_one({"req_id": req_id})
    if not doc: raise HTTPException(404, f"Request {req_id} tidak ditemukan")
    if doc["status"] != "Pending": raise HTTPException(400, "Request sudah direspon")
    if actor_role == 'kepala_cabang' and doc.get('cabang') != actor_cabang:
        raise HTTPException(status_code=403, detail='Kamu tidak bisa respon request cabang lain')

    now    = datetime.now(timezone.utc)
    update = {
        "updated_at": now,
        "catatan_kc": payload.catatan,
    }

    if payload.status.value == "Diterima":
        update["status"] = "Menunggu_Kasir"
        update["disetujui_oleh_kc"] = actor
        update["disetujui_at_kc"] = now
        if payload.estimasi_tiba:
            update["estimasi_tiba"] = payload.estimasi_tiba
    elif payload.status.value == "Ditolak":
        update["status"] = "Ditolak"

    await db.request_sparepart.update_one({"req_id": req_id}, {"$set": update})
    updated = await db.request_sparepart.find_one({"req_id": req_id})
    await write_log(db, actor, "Respon Request Sparepart", f"{req_id} → {update.get('status', 'updated')}", doc.get("cabang",""))
    return _fmt(updated)


async def approve_request(
    db, req_id: str, payload: RequestSparepartApproveRequest,
    actor: str, actor_role: str = '', actor_cabang: str = ''
) -> RequestSparepartResponse:
    """Kasir final approval: if Selesai -> create sparepart with harga_jual; if Ditolak -> status Ditolak."""
    if actor_role != "kasir":
        raise HTTPException(403, "Hanya Kasir yang bisa melakukan approval akhir")
    
    doc = await db.request_sparepart.find_one({"req_id": req_id})
    if not doc: raise HTTPException(404, f"Request {req_id} tidak ditemukan")
    if doc["status"] != "Menunggu_Kasir": raise HTTPException(400, f"Request tidak dalam status Menunggu_Kasir (status: {doc['status']})")
    if doc.get("cabang") != actor_cabang:
        raise HTTPException(403, "Request bukan milik cabang Anda")

    now = datetime.now(timezone.utc)
    update = {
        "updated_at": now,
        "approved_by": actor,
        "approved_at": now,
        "catatan_kc": doc.get("catatan_kc", "") + (" | " + payload.catatan if payload.catatan else ""),
    }

    if payload.status == "Selesai":
            if payload.harga_jual <= 0:
                raise HTTPException(400, "Harga jual harus diisi untuk status Selesai")
            update["status"] = "Selesai"
            update["harga_jual"] = payload.harga_jual
            update["approved_by"] = actor
            update["approved_at"] = datetime.now(timezone.utc)

            # Create sparepart with harga_jual - provide all required fields
            from app.services.sparepart import create_sparepart
            from app.schemas.sparepart import SparepartCreateRequest
            await create_sparepart(db, SparepartCreateRequest(
                nama=doc["nama_sp"],
                stok=doc["jumlah"],
                cabang=doc["cabang"],
                harga_jual=payload.harga_jual,
                harga_beli=0,  # Default since we don't have it
                kategori="Sparepart",
                satuan="pcs",
                dimensi_p=None,
                dimensi_l=None,
                dimensi_t=None,
                catatan=f"Auto-created from request {req_id}",
            ), actor=actor)
    elif payload.status == "Ditolak":
        update["status"] = "Ditolak"

    await db.request_sparepart.update_one({"req_id": req_id}, {"$set": update})
    updated = await db.request_sparepart.find_one({"req_id": req_id})
    
    await write_log(db, actor, "Approval Sparepart Kasir", f"{req_id} → {update['status']}", doc.get("cabang",""))
    return _fmt(updated)