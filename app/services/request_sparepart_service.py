from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from fastapi import HTTPException

from app.schemas.request_sparepart import (
    RequestSparepartCreateRequest, RequestSparepartResponseRequest, RequestSparepartResponse,
)
from app.services.log_service import write_log
from app.utils.formatters import fmt_waktu


def _fmt(doc: dict) -> RequestSparepartResponse:
    return RequestSparepartResponse(
        id=str(doc["_id"]), req_id=doc.get("req_id", str(doc["_id"])),
        tipe=doc.get("tipe",""), sp_id=doc.get("sp_id"),
        nama_sp=doc.get("nama_sp",""), jumlah=doc.get("jumlah",1),
        keterangan=doc.get("keterangan",""), status=doc.get("status","Pending"),
        estimasi_tiba=doc.get("estimasi_tiba"), catatan_kc=doc.get("catatan_kc",""),
        cabang=doc.get("cabang",""), dibuat_oleh=doc.get("dibuat_oleh",""),
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
        "cabang": payload.cabang, "dibuat_oleh": actor,
        "created_at": now, "updated_at": None,
    }
    res = await db.request_sparepart.insert_one(doc)
    doc["_id"] = res.inserted_id
    await write_log(db, actor, "Request Sparepart", f"{req_id} • {payload.nama_sp} x{payload.jumlah}", payload.cabang)
    return _fmt(doc)


async def respond_request(db, req_id: str, payload: RequestSparepartResponseRequest, actor: str, actor_role: str = '', actor_cabang: str = '') -> RequestSparepartResponse:
    doc = await db.request_sparepart.find_one({"req_id": req_id})
    if not doc: raise HTTPException(404, f"Request {req_id} tidak ditemukan")
    if doc["status"] != "Pending": raise HTTPException(400, "Request sudah direspon")
    if actor_role == 'kepala_cabang' and doc.get('cabang') != actor_cabang:
        raise HTTPException(status_code=403, detail='Kamu tidak bisa respon request cabang lain')

    now    = datetime.now(timezone.utc)
    update = {"status": payload.status.value, "catatan_kc": payload.catatan, "updated_at": now}
    if payload.estimasi_tiba: update["estimasi_tiba"] = payload.estimasi_tiba

    if payload.status.value == "Diterima" and doc["tipe"] == "item_baru":
        from app.services.sparepart_service import create_sparepart
        from app.schemas.sparepart import SparepartCreateRequest
        await create_sparepart(db, SparepartCreateRequest(nama=doc["nama_sp"], stok=0, cabang=doc["cabang"]), actor=actor)

    await db.request_sparepart.update_one({"req_id": req_id}, {"$set": update})
    updated = await db.request_sparepart.find_one({"req_id": req_id})
    await write_log(db, actor, "Respon Request Sparepart", f"{req_id} → {payload.status.value}", doc.get("cabang",""))
    return _fmt(updated)
