from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.database import get_db
from app.schemas.common import ok
from app.schemas.transfer_stok import TransferStokCreateRequest, TransferStokRespondRequest
from app.services.transfer_stok_service import (
    list_transfers,
    create_transfer,
    respond_transfer,
    count_pending_for_cabang,
    list_pending_for_cabang,
)
from app.middlewares.auth import require_kepala_or_owner, require_any

router = APIRouter(prefix="/transfer-stok", tags=["Transfer Stok"])


def _actor(user: dict) -> str:
    return user.get("name") or user.get("username") or "unknown"


@router.get("")
async def get_transfers(
    status: Optional[str] = Query(None, description="Filter: Pending | Diterima | Ditolak"),
    limit:  int = Query(100, ge=1, le=500),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kepala_or_owner),
):
    """
    List semua transfer.
    - Owner    : lihat semua cabang
    - Kepala   : hanya transfer yang melibatkan cabangnya (asal atau tujuan)
    """
    cab = None if user.get("role") == "owner" else user.get("cabang")
    items = await list_transfers(db, cabang=cab, status=status, limit=limit)
    return ok([i.model_dump() for i in items])


@router.post("", status_code=201)
async def buat_transfer(
    body: TransferStokCreateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kepala_or_owner),
):
    """
    Buat transfer baru.
    - Hanya kepala_cabang yang bisa (owner tidak, karena owner tidak punya cabang tertentu).
    - Body: cabang_tujuan, unit_ids (list), catatan (opsional).
    """
    if user.get("role") != "kepala_cabang":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Hanya Kepala Cabang yang bisa membuat transfer stok")

    cabang_asal = user.get("cabang")
    if not cabang_asal:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Akun kamu tidak terhubung ke cabang manapun")

    item = await create_transfer(
        db,
        payload=body,
        actor=_actor(user),
        cabang_asal=cabang_asal,
    )
    return ok(item.model_dump(), message=f"{item.transfer_id} berhasil diajukan ({item.jumlah} unit)")


@router.patch("/{transfer_id}")
async def respon_transfer(
    transfer_id: str,
    body:        TransferStokRespondRequest,
    db:          AsyncIOMotorDatabase = Depends(get_db),
    user:        dict = Depends(require_kepala_or_owner),
):
    """
    Terima atau Tolak transfer.
    - Kepala cabang TUJUAN: bisa terima/tolak transfer ke cabangnya.
    - Owner: bisa terima/tolak semua transfer.
    - Kepala cabang ASAL: tidak bisa (conflict of interest).
    """
    item = await respond_transfer(
        db,
        transfer_id=transfer_id,
        payload=body,
        actor=_actor(user),
        user_role=user.get("role", ""),
        user_cabang=user.get("cabang"),
    )
    return ok(item.model_dump(), message=f"Transfer {transfer_id} {item.status}")


# ── Cabang list untuk form transfer (kepala_cabang tidak bisa akses GET /cabang) ──

@router.get("/cabang-list")
async def list_cabang_for_transfer(
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kepala_or_owner),
):
    """
    List cabang aktif — dipakai form transfer.
    Kepala cabang tidak bisa akses GET /cabang (owner only),
    jadi endpoint ini sebagai alternatif yang aman.
    """
    docs = await db.cabang.find({"aktif": {"$ne": False}}).to_list(length=None)
    return ok([{"kode": d["kode"], "nama": d.get("nama", d["kode"])} for d in docs])


# ── Notifikasi polling endpoint ───────────────────────────────────────────────

@router.get("/notif/count")
async def notif_count(
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_any),
):
    """
    Jumlah transfer Pending yang ditujukan ke cabang user.
    Dipakai frontend untuk badge notifikasi (polling 30 detik).
    Owner: hitung semua Pending dari semua cabang.
    """
    if user.get("role") == "owner":
        # Owner lihat total semua pending
        from app.services.transfer_stok_service import list_transfers
        all_pending = await list_transfers(db, cabang=None, status="Pending", limit=500)
        return ok({"count": len(all_pending)})

    cabang = user.get("cabang")
    if not cabang:
        return ok({"count": 0})

    count = await count_pending_for_cabang(db, cabang)
    return ok({"count": count})


@router.get("/notif/pending")
async def notif_pending(
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kepala_or_owner),
):
    """
    List transfer Pending untuk cabang user — dipakai panel notif saat dibuka.
    """
    if user.get("role") == "owner":
        items = await list_transfers(db, cabang=None, status="Pending", limit=50)
    else:
        cabang = user.get("cabang")
        items = await list_pending_for_cabang(db, cabang, limit=50)
    return ok([i.model_dump() for i in items])
