from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.transaksi import TransaksiCreateRequest, TransaksiSparepartRequest
from app.schemas.common import ok
from app.services import transaksi_service
from app.middlewares.auth import require_owner, require_kasir_or_owner

router = APIRouter(prefix="/transaksi", tags=["Transaksi"])


@router.get("")
async def list_transaksi(
    cabang: Optional[str] = Query(None),
    limit:  int = Query(100, ge=1, le=500),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kasir_or_owner),
):
    items = await transaksi_service.list_transaksi(db, cabang=cabang, limit=limit)
    role  = user.get("role")
    data  = []
    for i in items:
        d = i.model_dump()
        if role == "kasir":
            d.pop("harga_modal", None)
            d.pop("profit", None)
        data.append(d)
    return ok(data)


@router.post("", status_code=201)
async def create_transaksi(
    body: TransaksiCreateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_or_owner),
):
    """Jual HP."""
    trx = await transaksi_service.create_transaksi(
        db, payload=body, kasir_name=user["name"], cabang=user["cabang"],
    )
    return ok(trx.model_dump(), message=f"Transaksi {trx.trx_id} berhasil dicatat")


@router.post("/sparepart", status_code=201)
async def create_transaksi_sparepart(
    body: TransaksiSparepartRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_or_owner),
):
    """Jual sparepart / aksesoris."""
    trx = await transaksi_service.create_transaksi_sparepart(
        db, payload=body, kasir_name=user["name"], cabang=user["cabang"],
    )
    return ok(trx.model_dump(), message=f"Transaksi {trx.trx_id} berhasil dicatat")
