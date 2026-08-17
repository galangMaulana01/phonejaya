from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.config.database import get_db
from app.schemas.transaksi import TransaksiCreateRequest, TransaksiSparepartRequest, TransaksiVoidRequest
from app.schemas.common import ok
from app.services import transaksi_service
from app.middlewares.auth import require_kepala_or_owner, require_kasir_teknisi_or_owner, require_any

router = APIRouter(prefix="/transaksi", tags=["Transaksi"])


@router.get("")
async def list_transaksi(
    cabang:    Optional[str] = Query(None),
    limit:     int = Query(100, ge=1, le=500),
    skip:      int = Query(0, ge=0),
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    db:        AsyncIOMotorDatabase = Depends(get_db),
    user:      dict = Depends(require_kepala_or_owner),
):
    cab = cabang if user.get("role") == "owner" else user.get("cabang")
    items, total = await transaksi_service.list_transaksi(db, cabang=cab, limit=limit, skip=skip, date_from=date_from, date_to=date_to)
    return ok([i.model_dump() for i in items], total=total, skip=skip, limit=limit)


@router.post("", status_code=201)
async def create_transaksi(
    body: TransaksiCreateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    trx = await transaksi_service.create_transaksi(
        db, payload=body,
        kasir_name=user.get("name", user.get("username", "")),
        cabang=user.get("cabang", ""),
        poin_dipakai=body.poin_dipakai,
    )
    return ok(trx.model_dump(), message=f"Transaksi {trx.trx_id} berhasil dicatat")


@router.get("/{trx_id}/detail")
async def transaksi_detail(
    trx_id: str,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    """Return transaction with financial breakdown (harga_modal, harga_jual, profit, margin)."""
    from fastapi import HTTPException
    doc = await db.transaksi.find_one({"trx_id": trx_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Transaksi {trx_id} tidak ditemukan")
    if user.get("role") != "owner" and doc.get("cabang") != user.get("cabang"):
        raise HTTPException(status_code=403, detail="Bukan hak anda untuk melihat transaksi ini")
    trx = transaksi_service._fmt(doc)
    data = trx.model_dump()
    # Calculate margin percentage
    margin = round((data["profit"] / data["harga_jual"]) * 100, 1) if data["harga_jual"] else 0
    data["margin_pct"] = margin
    return ok(data)


# PATCH /transaksi/{trx_id}/void - Kasir/kepala cabang/owner batalkan
# transaksi yang sudah tercatat (mengembalikan unit/stok/poin). require_any
# di sini karena tiga role berbeda boleh memicu ini; void_transaksi sendiri
# yang menolak role di luar itu dan yang membatasi kasir ke transaksinya
# sendiri / KC ke cabangnya sendiri.
@router.patch("/{trx_id}/void")
async def void_transaksi(
    trx_id: str,
    body:   TransaksiVoidRequest,
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_any),
):
    trx = await transaksi_service.void_transaksi(
        db, trx_id,
        actor=user.get("name", user.get("username", "")),
        actor_role=user.get("role", ""),
        reason=body.alasan,
        actor_cabang=user.get("cabang", ""),
    )
    return ok(trx.model_dump(), message=f"Transaksi {trx_id} dibatalkan")


# Legacy endpoint — tetap dipertahankan untuk backward compat
@router.post("/sparepart", status_code=201)
async def create_transaksi_sparepart(
    body: TransaksiSparepartRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    trx = await transaksi_service.create_transaksi_sparepart(
        db, payload=body,
        kasir_name=user.get("name", user.get("username", "")),
        cabang=user.get("cabang", ""),
    )
    return ok(trx.model_dump(), message=f"Transaksi {trx.trx_id} berhasil dicatat")
