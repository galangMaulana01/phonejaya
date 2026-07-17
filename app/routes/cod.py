from fastapi import APIRouter, Depends, Query, HTTPException, status
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone

from app.config.database import get_db
from app.schemas.cod import (
    CODRequestCreate, CODStatusUpdate, CODRequestResponse,
    CODRequestList, CODRequestDetail, KurirListItem
)
from app.schemas.common import ok
from app.services import cod_service
from app.services.log_service import write_log
from app.utils.id_generator import next_unit_id
from app.middlewares.auth import get_current_user, require_kasir_teknisi_or_owner, require_kurir

router = APIRouter(prefix="/cod", tags=["COD"])


# ════════════════════════════════════════════════════════════════
# KASIR ENDPOINTS
# ════════════════════════════════════════════════════════════════

@router.post("", response_model=dict, status_code=201)
async def create_cod_request(
    payload: CODRequestCreate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    """Kasir buat request COD (Beli/Jual)."""
    kasir_id = user.get("sub") or user.get("username")
    kasir_name = user.get("name") or user.get("username")
    cabang = user.get("cabang")
    actor = kasir_name
    
    if not kasir_id or not cabang:
        raise HTTPException(status_code=400, detail="Data kasir tidak lengkap")
    
    cod = await cod_service.create_cod_request(db, payload, kasir_id, kasir_name, cabang, actor)
    return ok(cod.model_dump(), message=f"COD Request {cod.cod_id} berhasil dibuat")


@router.get("/kurir-list", response_model=dict)
async def get_kurir_list(
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    """List kurir aktif di cabang (untuk dropdown)."""
    cabang = user.get("cabang")
    if not cabang:
        raise HTTPException(status_code=400, detail="Cabang tidak ditemukan")
    
    kurirs = await cod_service.get_kurir_list(db, cabang)
    return ok([k.model_dump() for k in kurirs])


@router.get("", response_model=dict)
async def list_cod_requests(
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    """List COD requests untuk Kasir/KC/Owner (filter by cabang)."""
    cabang = user.get("cabang")
    role = user.get("role", "kasir")
    
    # Kasir hanya lihat miliknya sendiri
    if role == "kasir":
        kurir_id = user.get("sub") or user.get("username")
        # Kasir tidak punya kurir_id, filter by kasir_id di service
        pass  # service handles this
    
    cods = await cod_service.list_cod_requests_all(
        db, cabang, status, type, date_from, date_to, limit
    )
    return ok([c.model_dump() for c in cods])


@router.get("/{cod_id}", response_model=dict)
async def get_cod_detail(
    cod_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    """Detail COD request."""
    cod = await cod_service.get_cod_detail(db, cod_id)
    return ok(cod.model_dump())


# ════════════════════════════════════════════════════════════════
# KURIR ENDPOINTS
# ════════════════════════════════════════════════════════════════

@router.get("/kurir/dashboard", response_model=dict)
async def kurir_dashboard(
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kurir),
):
    """Dashboard Kurir: list COD assigned ke kurir ini."""
    kurir_id = user.get("sub") or user.get("username")
    kurir_name = user.get("name") or user.get("username")
    cabang = user.get("cabang")
    
    if not kurir_id or not cabang:
        raise HTTPException(status_code=400, detail="Data kurir tidak lengkap")
    
    cods = await cod_service.list_cod_requests(db, cabang, kurir_id, kurir_name, status, type)
    return ok([c.model_dump() for c in cods])


@router.post("/kurir/{cod_id}/accept", response_model=dict)
async def kurir_accept(
    cod_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kurir),
):
    """Kurir terima COD request."""
    kurir_id = user.get("sub") or user.get("username")
    kurir_name = user.get("name") or user.get("username")
    
    cod = await cod_service.update_cod_status(db, cod_id, "diterima", kurir_id, kurir_name)
    return ok(cod.model_dump(), message=f"COD {cod_id} diterima")


@router.post("/kurir/{cod_id}/reject", response_model=dict)
async def kurir_reject(
    cod_id: str,
    note: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kurir),
):
    """Kurir tolak COD request."""
    kurir_id = user.get("sub") or user.get("username")
    kurir_name = user.get("name") or user.get("username")
    
    cod = await cod_service.update_cod_status(db, cod_id, "ditolak", kurir_id, kurir_name, note)
    return ok(cod.model_dump(), message=f"COD {cod_id} ditolak")


@router.post("/kurir/{cod_id}/status", response_model=dict)
async def kurir_update_status(
    cod_id: str,
    payload: CODStatusUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kurir),
):
    """Kurir update status COD (menuju lokasi, sudah bertemu, dll)."""
    kurir_id = user.get("sub") or user.get("username")
    kurir_name = user.get("name") or user.get("username")
    
    cod = await cod_service.update_cod_status(db, cod_id, payload.status, kurir_id, kurir_name, payload.note)
    return ok(cod.model_dump(), message=f"Status COD {cod_id} diperbarui ke {payload.status}")


# ════════════════════════════════════════════════════════════════
# INPUT STOK (Kurir) - Clone dari Kasir tapi tanpa harga
# ════════════════════════════════════════════════════════════════

@router.post("/kurir/input-stok", response_model=dict, status_code=201)
async def kurir_input_stok(
    payload: dict,  # Same as unit create but without harga
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kurir),
):
    """Kurir input stok HP (tanpa harga). Serahkan ke Kasir untuk harga."""
    kurir_id = user.get("sub") or user.get("username")
    kurir_name = user.get("name") or user.get("username")
    cabang = user.get("cabang")
    
    # Validasi required fields
    required = ["imei", "merk", "tipe", "ram", "storage", "warna", "kondisi"]
    for field in required:
        if not payload.get(field):
            raise HTTPException(status_code=400, detail=f"Field {field} wajib diisi")
    
    # Generate unit_id
    merk = payload["merk"]
    kondisi = payload["kondisi"]
    unit_id = await next_unit_id(db, merk, kondisi, cabang)
    
    now = datetime.now(timezone.utc)
    doc = {
        "unit_id": unit_id,
        "imei": payload["imei"],
        "merk": payload["merk"],
        "tipe": payload["tipe"],
        "ram": payload["ram"],
        "storage": payload["storage"],
        "warna": payload["warna"],
        "kondisi": payload["kondisi"],
        "grade": payload.get("grade", "B"),
        "baterai": payload.get("baterai"),
        "kelengkapan": payload.get("kelengkapan", []),
        "catatan": payload.get("catatan"),
        "status": "Tersedia",
        "cabang": cabang,
        "created_by": kurir_id,
        "created_by_name": kurir_name,
        "created_by_role": "Kurir",
        "harga_beli": None,  # Kurir TIDAK input harga
        "harga_jual": None,
        "created_at": now,
        "updated_at": now,
    }
    
    await db.units.insert_one(doc)
    
    await write_log(
        db, kurir_id, "Input Stok (Kurir)",
        f"Unit {unit_id} → {payload['merk']} {payload['tipe']} (tanpa harga)",
        cabang
    )
    
    return ok({"unit_id": unit_id}, message="Stok berhasil ditambahkan, serahkan ke Kasir untuk input harga")


# ════════════════════════════════════════════════════════════════
# LOG KURIR
# ════════════════════════════════════════════════════════════════

@router.get("/kurir/log", response_model=dict)
async def kurir_log(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kurir),
):
    """Log aktivitas Kurir."""
    kurir_id = user.get("sub") or user.get("username")
    cabang = user.get("cabang")
    
    if not kurir_id or not cabang:
        raise HTTPException(status_code=400, detail="Data kurir tidak lengkap")
    
    query = {"cabang": cabang, "user": kurir_id}
    if date_from or date_to:
        wf = {}
        if date_from:
            wf["$gte"] = datetime.fromisoformat(date_from.replace("Z", "")).replace(tzinfo=timezone.utc)
        if date_to:
            wf["$lte"] = datetime.fromisoformat(date_to.replace("Z", "")).replace(tzinfo=timezone.utc)
        query["created_at"] = wf
    if action:
        query["aksi"] = {"$regex": action, "$options": "i"}
    
    cursor = db.logs.find(query).sort("created_at", -1).limit(limit)
    logs = await cursor.to_list(length=limit)
    
    return ok([
        {
            "id": str(log["_id"]),
            "waktu": log["created_at"].isoformat() if isinstance(log["created_at"], datetime) else str(log["created_at"]),
            "user": log.get("user"),
            "aksi": log.get("aksi"),
            "detail": log.get("detail"),
        }
        for log in logs
    ])