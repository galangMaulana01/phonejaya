from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.request_sparepart import (
    RequestSparepartCreateRequest, RequestSparepartResponseRequest,
    RequestSparepartApproveRequest
)
from app.schemas.common import ok
from app.services.request_sparepart_service import (
    list_requests, create_request, respond_request, approve_request as approve_request_service
)
from app.middlewares.auth import require_kasir_teknisi_or_owner, require_kepala_or_owner, require_kasir

router = APIRouter(prefix="/request-sparepart", tags=["Request Sparepart"])


# GET /request-sparepart - List requests (filter by role and status)
@router.get("")
async def get_requests(
    status: Optional[str] = Query(None),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kasir_teknisi_or_owner),
):
    cab = None if user.get("role") == "owner" else user.get("cabang")
    items = await list_requests(db, cabang=cab, status=status)
    return ok([i.model_dump() for i in items])


# POST /request-sparepart - Create request (Teknisi/Kasir/KC)
@router.post("", status_code=201)
async def buat_request(
    body: RequestSparepartCreateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    # Only Teknisi can create requests; Kasir no longer creates
    if user.get("role") == "kasir":
        from fastapi import HTTPException
        raise HTTPException(403, "Kasir tidak bisa membuat request sparepart. Gunakan menu Approval Sparepart.")
    
    body.cabang = user.get("cabang", body.cabang)
    item = await create_request(db, payload=body, actor=user.get("name", user.get("username","")))
    return ok(item.model_dump(), message=f"{item.req_id} berhasil diajukan")


# PATCH /request-sparepart/{req_id}/respond - Kepala Cabang respond
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


# PATCH /request-sparepart/{req_id}/approve - Kasir final approval
@router.patch("/{req_id}/approve")
async def approve_request(
    req_id: str,
    body:   RequestSparepartApproveRequest,
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kasir),
):
    item = await approve_request_service(
        db, req_id=req_id, payload=body,
        actor=user.get("name", user.get("username","")),
        actor_role=user.get("role",""),
        actor_cabang=user.get("cabang",""),
    )
    return ok(item.model_dump(), message=f"Request {req_id} {item.status}")