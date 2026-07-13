from fastapi import APIRouter, Depends, Query, HTTPException, Header, status
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone
import os

from app.config.database import get_db
from app.schemas.influencer import (
    VideoCreateRequest,
    InfluencerDashboardStats, CatalogItem,
    VideoResponse, InfluencerProfileResponse,
    OwnerInfluencerSummary, OwnerInfluencerDashboard,
    InfluencerSocialUpdate
)
from app.schemas.common import ok
from app.services import influencer_service
from app.middlewares.auth import require_influencer, require_influencer_or_owner
from app.services.log_service import write_log

router = APIRouter(prefix="/influencer", tags=["Influencer"])

# ════════════════════════════════════════════════════════════════
# INFLUENCER ENDPOINTS
# ════════════════════════════════════════════════════════════════

@router.get("/dashboard/stats", response_model=dict)
async def dashboard_stats(
    hari: int = Query(90, ge=7, le=365),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_influencer),
):
    """Stats dashboard influencer: total video, views, likes, produk, trend, top 5."""
    influencer_id = user.get("sub") or user.get("username")
    cabang = user.get("cabang")
    if not influencer_id or not cabang:
        raise HTTPException(status_code=400, detail="Data influencer tidak lengkap")

    stats = await influencer_service.get_dashboard_stats(db, influencer_id, cabang, hari)
    return ok(stats.model_dump())


@router.get("/catalog", response_model=dict)
async def catalog(
    kategori: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_influencer),
):
    """Katalog produk Tersedia cabang influencer + flag has_video."""
    influencer_id = user.get("sub") or user.get("username")
    cabang = user.get("cabang")
    if not influencer_id or not cabang:
        raise HTTPException(status_code=400, detail="Data influencer tidak lengkap")

    items = await influencer_service.get_catalog(db, cabang, influencer_id, kategori, q)
    return ok([item.model_dump() for item in items])


@router.post("/videos", status_code=201, response_model=dict)
async def create_video(
    payload: VideoCreateRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_influencer),
):
    """Buat video baru untuk unit. Auto-fetch metrics jika TikTok."""
    influencer_id = user.get("sub") or user.get("username", "")
    influencer_name = user.get("name") or user.get("username", "")
    cabang = user.get("cabang", "")
    actor = user.get("name") or user.get("username", "")

    if not influencer_id or not cabang:
        raise HTTPException(status_code=400, detail="Data influencer tidak lengkap")

    video = await influencer_service.create_video(
        db, payload, influencer_id, influencer_name, cabang, actor
    )
    return ok(video.model_dump(), message=f"Video {video.video_id} berhasil dibuat")


@router.get("/videos", response_model=dict)
async def list_videos(
    platform: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_influencer),
):
    """List video influencer dengan filter."""
    influencer_id = user.get("sub") or user.get("username")
    cabang = user.get("cabang")
    if not influencer_id or not cabang:
        raise HTTPException(status_code=400, detail="Data influencer tidak lengkap")

    items = await influencer_service.list_videos(
        db, influencer_id, cabang, platform, date_from, date_to, limit
    )
    return ok([item.model_dump() for item in items])


@router.get("/log", response_model=dict)
async def list_log(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_influencer),
):
    """List log aktivitas influencer."""
    influencer_id = user.get("sub") or user.get("username")
    cabang = user.get("cabang")
    
    # Build query
    query = {"cabang": cabang}
    
    # Date filter
    if date_from and date_to:
        try:
            df = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            dt = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            query["waktu"] = {"$gte": df, "$lte": dt}
        except ValueError:
            pass
    
    # Get logs, limit 100
    logs = await db.log.find(query).sort("waktu", -1).limit(100).to_list(None)
    
    # Format response
    result = []
    for doc in logs:
        # Filter only influencer-related logs for this cabang
        aksi = doc.get("aksi", "")
        if any(x in aksi for x in ["Video", "Influencer", "TikTok", "Instagram", "Auto-Fetch", "Sync", "Upload"]):
            result.append({
                "waktu": doc.get("waktu", "").isoformat() if isinstance(doc.get("waktu"), datetime) else str(doc.get("waktu", "")),
                "user": doc.get("user", ""),
                "aksi": aksi,
                "detail": doc.get("detail", ""),
                "cabang": doc.get("cabang", ""),
            })
    
    return ok(result)


# ════════════════════════════════════════════════════════════════
# DEPRECATED ENDPOINTS (no longer used in frontend)
# ════════════════════════════════════════════════════════════════

@router.get("/profile", response_model=dict)
async def get_profile(
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_influencer),
):
    """Profil influencer (basic info + social media). DEPRECATED - social profile page removed."""
    influencer_id = user.get("sub") or user.get("username", "")
    profile = await influencer_service.get_profile(db, influencer_id)
    return ok(profile.model_dump())


@router.patch("/social", response_model=dict)
async def update_social(
    payload: InfluencerSocialUpdate,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_influencer),
):
    """Update social media usernames (TikTok and Instagram only). DEPRECATED - social profile page removed."""
    influencer_id = user.get("sub") or user.get("username", "")
    actor = user.get("name") or user.get("username", "")
    profile = await influencer_service.update_influencer_social(db, influencer_id, payload, actor)
    return ok(profile.model_dump(), message="Social media updated")


# ════════════════════════════════════════════════════════════════
# OWNER INFLUENCER MONITOR ENDPOINTS
# ════════════════════════════════════════════════════════════════

from app.middlewares.auth import require_owner

@router.get("/owner/dashboard", response_model=dict)
async def owner_dashboard(
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """Dashboard owner: agregat semua influencer."""
    dashboard = await influencer_service.get_owner_dashboard(db)
    return ok(dashboard.model_dump())


@router.get("/owner/videos", response_model=dict)
async def owner_list_videos(
    cabang: Optional[str] = Query(None),
    influencer_id: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """Owner lihat semua video dengan filter."""
    items = await influencer_service.list_all_videos_owner(
        db, cabang, influencer_id, platform, date_from, date_to, limit
    )
    return ok([item.model_dump() for item in items])


@router.get("/owner/influencers", response_model=dict)
async def owner_list_influencers(
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """List semua influencer untuk dropdown filter owner."""
    items = await influencer_service.list_influencers(db)
    return ok(items)


# ════════════════════════════════════════════════════════════════
# CRON SYNC ENDPOINT (dipanggil via cron tiap 1 jam)
# ════════════════════════════════════════════════════════════════

from fastapi import Header, HTTPException, status
from app.config.settings import settings


async def verify_cron_secret(x_cron_secret: str = Header(...)):
    """Verify cron secret for automated calls."""
    cron_secret = getattr(settings, "CRON_SECRET", None) or os.getenv("CRON_SECRET")
    if not cron_secret or x_cron_secret != cron_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid cron secret")


@router.post("/sync", response_model=dict)
async def sync_influencers(
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_owner),  # Hanya owner bisa trigger manual
):
    """Manual trigger untuk sync semua influencer (dipakai cron tiap 1 jam)."""
    from app.services.influencer_sync_service import sync_all_influencers
    result = await sync_all_influencers(db)
    return ok(result, message="Influencer sync completed")


@router.post("/sync/cron", response_model=dict)
async def sync_influencers_cron(
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: None = Depends(verify_cron_secret),
):
    """Cron endpoint untuk sync semua influencer (tiap jam via Vercel Cron)."""
    from app.services.influencer_sync_service import sync_all_influencers
    result = await sync_all_influencers(db)
    return ok(result, message="Influencer cron sync completed")
