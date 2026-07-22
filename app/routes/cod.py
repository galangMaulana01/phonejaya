from fastapi import APIRouter, Depends, Query, HTTPException, status
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone

from app.config.database import get_db
from app.schemas.cod import (
    CODRequestCreate, CODStatusUpdate, CODRequestResponse,
    CODRequestList, CODRequestDetail, KurirListItem, ApproveBeliRequest
)
from app.schemas.common import ok
from app.services import cod_service
from app.services.log_service import write_log
from app.utils.id_generator import next_unit_id, resolve_kategori
from app.middlewares.auth import get_current_user, require_kasir_teknisi_or_owner, require_kurir, require_kepala_or_owner

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
    """Kasir buat request COD (Beli/Jual/Delivery)."""
    kasir_id = user.get("sub") or user.get("username")
    kasir_name = user.get("name") or user.get("username")
    cabang = user.get("cabang")
    actor = kasir_name
    role = user.get("role", "kasir")
    
    if not kasir_id or not cabang:
        raise HTTPException(status_code=400, detail="Data kasir tidak lengkap")
    
    cod = await cod_service.create_cod_request(db, payload, kasir_id, kasir_name, cabang, actor, role)
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


@router.post("/kurir/{cod_id}/reject-beli", response_model=dict)
async def kurir_reject_beli(
    cod_id: str,
    payload: dict,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kurir),
):
    """Kurir tolak COD beli setelah bertemu penjual (status sudah_bertemu_penjual)."""
    kurir_id = user.get("sub") or user.get("username")
    kurir_name = user.get("name") or user.get("username")
    reason = payload.get("reason", "")
    
    if not reason:
        raise HTTPException(status_code=400, detail="Alasan reject wajib diisi")
    
    cod = await cod_service.reject_beli_by_kurir(db, cod_id, kurir_id, kurir_name, reason)
    return ok(cod.model_dump(), message=f"COD {cod_id} ditolak oleh kurir")


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
    required = ["imei", "merk", "tipe", "storage", "warna"]
    for field in required:
        if not payload.get(field):
            raise HTTPException(status_code=400, detail=f"Field {field} wajib diisi")
    
    # Derive kat_kode and kondisi_kode from payload (with safe defaults)
    kat_kode = payload.get("kat_kode", "AI")  # Default: Android
    kondisi_kode = payload.get("kondisi_kode", "BN")  # Default: Normal
    kondisi_hp = payload.get("kondisi_hp", "Mulus")
    
    # Generate unit_id with proper kat_kode
    unit_id = await next_unit_id(db, kat_kode, kondisi_kode, cabang)
    
    now = datetime.now(timezone.utc)
    doc = {
        "unit_id": unit_id,
        "merk": payload["merk"],
        "tipe": payload["tipe"],
        "storage": payload.get("storage", "-"),
        "ram": payload.get("ram", "-"),
        "warna": payload["warna"],
        "imei": payload["imei"],
        "imei2": "-",
        "tipe_sim": "Single SIM",
        "keamanan": "Tidak Ada",
        "speaker": "Normal",
        "lcd": "Original",
        "harga_modal": 0,
        "harga_jual": 0,
        "kondisi": kondisi_kode,
        "kondisi_hp": kondisi_hp,
        "battery": payload.get("battery", 100),
        "battery_health": 0,
        "status": "Tersedia",
        "kategori": resolve_kategori(kat_kode),
        "catatan": payload.get("catatan", ""),
        "cabang": cabang,
        "locked": False,
        "garansi_toko": 7,
        "created_at": now,
        "created_by": kurir_name,
        "tgl_terjual": None,
        "service_id": None,
        "foto_url": payload.get("foto_url"),
        "input_by_role": "Kurir",
    }
    
    await db.units.insert_one(doc)
    
    await write_log(
        db, kurir_id, "Input Stok (Kurir)",
        f"Unit {unit_id} → {payload['merk']} {payload['tipe']} (tanpa harga)",
        cabang
    )
    
    return ok({"unit_id": unit_id}, message="Stok berhasil ditambahkan, serahkan ke Kasir untuk input harga")


# ════════════════════════════════════════════════════════════════
# KURIR SUBMIT BELI (setelah bertemu penjual)
# ════════════════════════════════════════════════════════════════

@router.post("/kurir/{cod_id}/submit-beli", response_model=dict)
async def kurir_submit_beli(
    cod_id: str,
    payload: dict,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kurir),
):
    """Kurir submit data HP setelah nego deal (type=beli)."""
    kurir_id = user.get("sub") or user.get("username")
    kurir_name = user.get("name") or user.get("username")
    
    deal_price = payload.get("deal_price")
    unit_data = payload.get("unit_data")
    if not deal_price or not unit_data:
        raise HTTPException(status_code=400, detail="deal_price dan unit_data wajib diisi")
    
    cod = await cod_service.submit_kurir_beli(db, cod_id, kurir_id, kurir_name, deal_price, unit_data)
    return ok(cod.model_dump(), message=f"COD {cod_id} menunggu approval kasir")


# ════════════════════════════════════════════════════════════════
# KASIR APPROVE/REJECT BELI
# ════════════════════════════════════════════════════════════════

@router.post("/{cod_id}/approve", response_model=dict)
async def approve_beli(
    cod_id: str,
    body: ApproveBeliRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    """Kasir approve COD beli — unit masuk inventory/teknisi."""
    kasir_name = user.get("name") or user.get("username")
    cabang = user.get("cabang")
    harga_jual = body.harga_jual
    
    cod = await cod_service.approve_beli_cod(db, cod_id, kasir_name, cabang, harga_jual=harga_jual, unit_data=body.unit_data, garansi_toko=body.garansi_toko, catatan=body.catatan)
    return ok(cod.model_dump(), message=f"COD {cod_id} disetujui — unit masuk inventory")


@router.post("/{cod_id}/reject", response_model=dict)
async def reject_beli(
    cod_id: str,
    payload: dict,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kasir_teknisi_or_owner),
):
    """Kasir reject COD beli dengan alasan."""
    kasir_name = user.get("name") or user.get("username")
    cabang = user.get("cabang")
    reason = payload.get("reason", "")
    
    if not reason:
        raise HTTPException(status_code=400, detail="Alasan reject wajib diisi")
    
    cod = await cod_service.reject_beli_cod(db, cod_id, reason, kasir_name, cabang)
    return ok(cod.model_dump(), message=f"COD {cod_id} ditolak")


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
        query["waktu"] = wf
    if action:
        query["aksi"] = {"$regex": action, "$options": "i"}
    
    cursor = db.log.find(query).sort("waktu", -1).limit(limit)
    logs = await cursor.to_list(length=limit)
    
    return ok([
        {
            "id": str(log["_id"]),
            "waktu": log["waktu"].isoformat() if isinstance(log["waktu"], datetime) else str(log["waktu"]),
            "user": log.get("user"),
            "aksi": log.get("aksi"),
            "detail": log.get("detail"),
        }
        for log in logs
    ])


# ════════════════════════════════════════════════════════════════
# KURIR MONITORING (Owner/Kepala Cabang)
# ════════════════════════════════════════════════════════════════

@router.get("/kurir/monitoring", response_model=dict)
async def kurir_monitoring(
    cabang: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kepala_or_owner),
):
    """Monitoring Kurir: statistik COD per kurir untuk Owner/Kepala Cabang."""
    # Owner bisa filter cabang, KC hanya cabang sendiri
    if user.get("role") == "kepala_cabang":
        cabang = user.get("cabang")
    elif not cabang and user.get("role") != "owner":
        raise HTTPException(status_code=400, detail="Cabang tidak ditemukan")
    
    kurirs = await cod_service.get_kurir_monitoring(db, cabang, date_from, date_to)
    return ok(kurirs)