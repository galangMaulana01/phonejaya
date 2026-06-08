from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.customer import CustomerCreateRequest
from app.schemas.common import ok
from app.services import customer_service
from app.middlewares.auth import require_kasir_or_owner

router = APIRouter(prefix="/customers", tags=["Customer"])


@router.get("")
async def list_customer(
    cabang: Optional[str] = Query(None),
    q:      Optional[str] = Query(None),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    _user:  dict = Depends(require_kasir_or_owner),
):
    cab = cabang if _user.get("role") == "owner" else _user.get("cabang")
    items = await customer_service.list_customer(db, cabang=cab, q=q)
    return ok([i.model_dump() for i in items])


@router.post("", status_code=201)
async def create_customer(
    body:  CustomerCreateRequest,
    db:    AsyncIOMotorDatabase = Depends(get_db),
    user:  dict = Depends(require_kasir_or_owner),
):
    item = await customer_service.create_customer(db, body, actor=user.get("name", user.get("username", "")))
    return ok(item.model_dump(), message="Customer berhasil ditambahkan")
