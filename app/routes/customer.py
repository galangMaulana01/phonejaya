from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.customer import (
    CustomerCreateRequest, CustomerVerifyRequest, CustomerRejectRequest,
    CustomerResubmitRequest
)
from app.schemas.common import ok
from app.services import customer_service
from app.middlewares.auth import get_current_user, require_kasir_teknisi_or_owner, require_kepala_or_owner, require_owner
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/customers", tags=["Customer"])


@router.post("", status_code=201)
async def create_customer(
    body: CustomerCreateRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    """Kasir membuat customer baru (status: Pending)."""
    cabang = user.get("cabang")
    if not cabang:
        raise HTTPException(status_code=400, detail="User tidak memiliki cabang")
    try:
        item = await customer_service.create_customer(
            db,
            payload=body,
            actor_id=user.get("sub", ""),
            actor_name=user.get("name", user.get("username", "")),
            actor_role=user.get("role", ""),
            cabang=cabang,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to create customer: %s", str(e))
        raise HTTPException(status_code=500, detail="Gagal membuat customer")
    return ok(item.model_dump(), message=f"Customer {item.nama} dibuat (Pending approval)")


@router.get("")
async def list_customers(
    status: Optional[str] = Query(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    """List customer dengan filter status (Pending/Verified/Rejected)."""
    cabang = None if user.get("role") == "owner" else user.get("cabang")
    items = await customer_service.list_customers(db, cabang=cabang, status=status)
    return ok([i.model_dump() for i in items])


@router.patch("/{customer_id}/approve")
async def approve_customer(
    customer_id: str,
    body: CustomerVerifyRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kepala_or_owner),
):
    """Kepala Cabang approve customer: Pending → Verified."""
    item = await customer_service.approve_customer(
        db,
        customer_id=customer_id,
        actor_id=user.get("sub", ""),
        actor_name=user.get("name", user.get("username", "")),
        actor_role=user.get("role", ""),
    )
    return ok(item.model_dump(), message=f"Customer {item.nama} diverifikasi")


@router.patch("/{customer_id}/reject")
async def reject_customer(
    customer_id: str,
    body: CustomerRejectRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kepala_or_owner),
):
    """Kepala Cabang reject customer: Pending → Rejected."""
    item = await customer_service.reject_customer(
        db,
        customer_id=customer_id,
        reason=body.reason,
        actor_id=user.get("sub", ""),
        actor_name=user.get("name", user.get("username", "")),
        actor_role=user.get("role", ""),
    )
    return ok(item.model_dump(), message=f"Customer {item.nama} ditolak")


@router.patch("/{customer_id}/resubmit")
async def resubmit_customer(
    customer_id: str,
    body: CustomerResubmitRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    """Kasir/Teknisi/KeCabang/Owner resubmit: Rejected → Pending."""
    item = await customer_service.resubmit_customer(
        db,
        customer_id=customer_id,
        actor_id=user.get("sub", ""),
        actor_name=user.get("name", user.get("username", "")),
        actor_role=user.get("role", ""),
        actor_cabang=user.get("cabang"),
    )
    return ok(item.model_dump(), message=f"Customer {item.nama} diajukan ulang")


@router.get("/pending-count")
async def get_pending_count(
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kepala_or_owner),
):
    """Jumlah customer Pending untuk dashboard KeCabang/Owner."""
    cabang = user.get("cabang") if user.get("role") == "kepala_cabang" else None
    count = await customer_service.get_pending_count(db, cabang=cabang)
    return ok({"count": count})