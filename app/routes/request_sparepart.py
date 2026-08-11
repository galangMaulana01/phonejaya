from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.request_sparepart import (
    RequestSparepartCreateRequest, RequestSparepartResponseRequest,
    RequestSparepartBeliRequest, RequestSparepartTerimaRequest,
)
from app.schemas.common import ok
from app.services.request_sparepart_service import (
    list_requests, create_request, respond_request, beli_request, terima_request, get_request_detail
)
from app.middlewares.auth import require_kepala_or_owner, require_kasir, require_any

router = APIRouter(prefix="/request-sparepart", tags=["Request Sparepart"])


# GET /request-sparepart - List requests (filter by role and status)
@router.get("")
async def get_requests(
    status: Optional[str] = Query(None),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_any),
):
    cab = None if user.get("role") == "owner" else user.get("cabang")
    items = await list_requests(db, cabang=cab, status=status)
    return ok([i.model_dump() for i in items])


# GET /request-sparepart/{req_id} - Get request detail
@router.get("/{req_id}")
async def get_request(
    req_id: str,
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_any),
):
    item = await get_request_detail(db, req_id)
    # Validate cabang ownership for non-owner
    if user.get("role") != "owner" and item.cabang != user.get("cabang"):
        from fastapi import HTTPException
        raise HTTPException(403, "Request bukan milik cabang Anda")
    return ok(item.model_dump())


# POST /request-sparepart - Create request (Teknisi only)
@router.post("", status_code=201)
async def buat_request(
    body: RequestSparepartCreateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_any),
):
    # Only teknisi can create requests
    if user.get("role") != "teknisi":
        from fastapi import HTTPException
        raise HTTPException(403, "Hanya Teknisi yang bisa membuat request sparepart. Gunakan menu Approval Sparepart untuk Kasir/Kepala Cabang.")

    body.cabang = user.get("cabang", body.cabang)
    item = await create_request(db, payload=body, actor=user.get("name", user.get("username","")))
    return ok(item.model_dump(), message=f"{item.req_id} berhasil diajukan")


# PATCH /request-sparepart/{req_id}/respond - Kepala Cabang review & approve harga
@router.patch("/{req_id}/respond")
async def respon_request(
    req_id: str,
    body:   RequestSparepartResponseRequest,
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kepala_or_owner),
):
    item = await respond_request(
        db, req_id=req_id, payload=body,
        actor=user.get("name", user.get("username","")),
        actor_role=user.get("role",""),
        actor_cabang=user.get("cabang",""),
    )
    return ok(item.model_dump(), message=f"Request {req_id} {item.status}")


# PATCH /request-sparepart/{req_id}/beli - Kasir catat pembelian
@router.patch("/{req_id}/beli")
async def catat_pembelian(
    req_id: str,
    body:   RequestSparepartBeliRequest,
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kasir),
):
    item = await beli_request(
        db, req_id, body,
        actor=user.get("name", user.get("username", "")),
        actor_role=user.get("role", ""),
        actor_cabang=user.get("cabang", ""),
    )
    return ok(item.model_dump(), message=f"Request {req_id} {item.status}")


# PATCH /request-sparepart/{req_id}/terima - Kasir konfirmasi barang diterima & masuk inventory
@router.patch("/{req_id}/terima")
async def konfirmasi_terima(
    req_id: str,
    body:   RequestSparepartTerimaRequest,
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kasir),
):
    item = await terima_request(
        db, req_id, body,
        actor=user.get("name", user.get("username", "")),
        actor_role=user.get("role", ""),
        actor_cabang=user.get("cabang", ""),
    )
    return ok(item.model_dump(), message=f"Request {req_id} {item.status}")
