from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.request_sparepart import RequestSparepartCreateRequest, RequestSparepartResponseRequest
from app.schemas.common import ok
from app.services.request_sparepart_service import list_requests, create_request, respond_request
from app.middlewares.auth import require_kasir_or_owner, require_kepala_or_owner

router = APIRouter(prefix="/request-sparepart", tags=["Request Sparepart"])


@router.get("")
async def get_requests(
    status: Optional[str] = Query(None),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kasir_or_owner),
):
    cab = None if user.get("role") == "owner" else user.get("cabang")
    items = await list_requests(db, cabang=cab, status=status)
    return ok([i.model_dump() for i in items])


@router.post("", status_code=201)
async def buat_request(
    body: RequestSparepartCreateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_or_owner),
):
    body.cabang = user.get("cabang", body.cabang)
    item = await create_request(db, payload=body, actor=user.get("name", user.get("username","")))
    return ok(item.model_dump(), message=f"{item.req_id} berhasil diajukan")


@router.patch("/{req_id}")
async def respon_request(
    req_id: str,
    body:   RequestSparepartResponseRequest,
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kepala_or_owner),
):
    item = await respond_request(db, req_id=req_id, payload=body, actor=user.get("name", user.get("username","")))
    return ok(item.model_dump(), message=f"Request {req_id} {item.status}")
