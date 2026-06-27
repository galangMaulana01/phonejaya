from fastapi import APIRouter, Depends, Query
from typing import Optional
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.database import get_db
from app.schemas.karyawan import KaryawanCreateRequest
from app.schemas.common import ok
from app.services import karyawan_service
from app.middlewares.auth import require_owner, require_kepala_or_owner

router = APIRouter(prefix="/karyawan", tags=["Karyawan"])


@router.get("")
async def list_karyawan(
    cabang: Optional[str] = Query(None),
    db:     AsyncIOMotorDatabase = Depends(get_db),
    user:   dict = Depends(require_kepala_or_owner),
):
    if user.get("role") == "owner":
        cab = cabang
    else:
        cab = user.get("cabang")

    items = await karyawan_service.list_karyawan(db, cabang=cab)
    return ok([i.model_dump() for i in items])


@router.post("", status_code=201)
async def tambah_karyawan(
    body: KaryawanCreateRequest,
    db:   AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_kepala_or_owner),
):
    kar = await karyawan_service.create_karyawan(
        db, payload=body,
        actor=user.get("name", user.get("username", "")),
    )
    return ok(kar.model_dump(), message=f"Karyawan {kar.nama} berhasil ditambahkan")


@router.get("/{karyawan_id}/stats")
async def get_karyawan_stats(
    karyawan_id: str,
    date_from:   Optional[str] = Query(None),
    date_to:     Optional[str] = Query(None),
    hari:        Optional[int] = Query(None),
    db:          AsyncIOMotorDatabase = Depends(get_db),
    user:        dict = Depends(require_kepala_or_owner),
):
    """
    Statistik kontribusi karyawan (kasir / teknisi).
    - Kasir   : jumlah transaksi, total omzet, total profit, trend harian
    - Teknisi : jumlah service selesai per status, rata2 per hari, trend harian
    """
    from fastapi import HTTPException

    # Fetch karyawan
    try:
        kar = await db.karyawan.find_one({"_id": ObjectId(karyawan_id)})
    except Exception:
        kar = None
    if not kar:
        raise HTTPException(status_code=404, detail="Karyawan tidak ditemukan")

    # Guard: kepala_cabang hanya bisa lihat karyawan cabangnya
    if user.get("role") == "kepala_cabang" and kar.get("cabang") != user.get("cabang"):
        raise HTTPException(status_code=403, detail="Akses ditolak")

    # Hitung rentang tanggal
    now = datetime.now(timezone.utc)
    if date_from and date_to:
        dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        dt_to   = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)
    else:
        days    = hari or 30
        dt_from = now - timedelta(days=days)
        dt_to   = now

    nama    = kar.get("nama", "")
    jabatan = kar.get("jabatan", "")

    stats: dict = {
        "karyawan_id": karyawan_id,
        "nama":        nama,
        "jabatan":     jabatan,
        "cabang":      kar.get("cabang", ""),
        "periode": {
            "dari":   dt_from.strftime("%Y-%m-%d"),
            "sampai": dt_to.strftime("%Y-%m-%d"),
        },
    }

    if jabatan == "Kasir":
        trx_list = await db.transaksi.find({
            "kasir": nama,
            "waktu": {"$gte": dt_from, "$lte": dt_to},
        }).sort("waktu", 1).to_list(length=None)

        total_omzet  = sum(t.get("harga_jual", 0) for t in trx_list)
        total_profit = sum(t.get("profit", 0) for t in trx_list)

        trend: dict = {}
        for t in trx_list:
            waktu = t.get("waktu")
            if waktu:
                day = waktu.strftime("%Y-%m-%d")
                if day not in trend:
                    trend[day] = {"omzet": 0, "jumlah": 0}
                trend[day]["omzet"]  += t.get("harga_jual", 0)
                trend[day]["jumlah"] += 1

        stats["kasir"] = {
            "jumlah_transaksi": len(trx_list),
            "total_omzet":      total_omzet,
            "total_profit":     total_profit,
            "rata_per_hari":    round(len(trx_list) / max((dt_to - dt_from).days, 1), 1),
            "trend_harian": [
                {"tanggal": d, "omzet": v["omzet"], "jumlah": v["jumlah"]}
                for d, v in sorted(trend.items())
            ],
        }

    elif jabatan == "Teknisi":
        svc_list = await db.service.find({
            "teknisi":    nama,
            "updated_at": {"$gte": dt_from, "$lte": dt_to},
        }).sort("updated_at", 1).to_list(length=None)

        svc_created = await db.service.find({
            "teknisi":    nama,
            "created_at": {"$gte": dt_from, "$lte": dt_to},
        }).sort("created_at", 1).to_list(length=None)

        all_ids: set = set()
        all_svc = []
        for s in svc_list + svc_created:
            sid = str(s["_id"])
            if sid not in all_ids:
                all_ids.add(sid)
                all_svc.append(s)

        status_count: dict = {}
        for s in all_svc:
            st = s.get("status", "unknown")
            status_count[st] = status_count.get(st, 0) + 1

        selesai_count = status_count.get("Selesai", 0) + status_count.get("Approved", 0)

        trend2: dict = {}
        for s in all_svc:
            if s.get("status") in ("Selesai", "Approved"):
                waktu = s.get("updated_at") or s.get("created_at")
                if waktu:
                    day = waktu.strftime("%Y-%m-%d")
                    trend2[day] = trend2.get(day, 0) + 1

        stats["teknisi"] = {
            "total_service":          len(all_svc),
            "jumlah_selesai":         selesai_count,
            "status_breakdown":       status_count,
            "rata_selesai_per_hari":  round(selesai_count / max((dt_to - dt_from).days, 1), 1),
            "trend_harian": [
                {"tanggal": d, "selesai": v}
                for d, v in sorted(trend2.items())
            ],
        }

    return {"success": True, "data": stats}
