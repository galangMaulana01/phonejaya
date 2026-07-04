from fastapi import APIRouter, Depends, Query
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.database import get_db
from app.schemas.influencer import (
    OwnerInfluencerDashboard, VideoResponse, OwnerInfluencerSummary
)
from app.schemas.common import ok
from app.services import influencer_service
from app.middlewares.auth import require_owner

router = APIRouter(prefix="/owner/influencers", tags=["Owner Influencer Monitor"])


@router.get("/dashboard", response_model=dict)
async def owner_dashboard(
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """Dashboard owner: agregat semua influencer."""
    dashboard = await influencer_service.get_owner_dashboard(db)
    return ok(dashboard.model_dump())


@router.get("/videos", response_model=dict)
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


@router.get("/influencers", response_model=dict)
async def owner_list_influencers(
    db: AsyncIOMotorDatabase = Depends(get_db),
    user: dict = Depends(require_owner),
):
    """List semua influencer untuk dropdown filter."""
    items = await influencer_service.list_influencers(db)
    return ok(items)