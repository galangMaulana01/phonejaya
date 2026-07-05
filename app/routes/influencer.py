from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase
from datetime import datetime, timezone

from app.config.database import get_db
from app.schemas.influencer import (
    VideoCreateRequest, VideoUpdateMetricsRequest,
    InfluencerDashboardStats, CatalogItem,
    VideoResponse, InfluencerProfileResponse,
    OwnerInfluencerSummary, OwnerInfluencerDashboard
)
from app.schemas.common import ok
from app.services import influencer_service
from app.middlewares.auth import require_influencer, require_influencer_or_owner

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


@router.patch("/videos/{video_id}", response_model=dict)
async def update_video_metrics(
    video_id: str,
    payload: VideoUpdateMetricsRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_influencer),
):
    """Update metrics video (views, likes, comments, shares)."""
    influencer_id = user.get("sub") or user.get("username", "")
    actor = user.get("name") or user.get("username", "")

    video = await influencer_service.update_video_metrics(
        db, video_id, payload, influencer_id, actor
    )
    return ok(video.model_dump(), message="Metrics video berhasil diupdate")


@router.get("/profile", response_model=dict)
async def get_profile(
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_influencer),
):
    """Profil influencer (basic info only)."""
    influencer_id = user.get("sub") or user.get("username", "")
    profile = await influencer_service.get_profile(db, influencer_id)
    return ok(profile.model_dump())


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