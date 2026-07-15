from pydantic import BaseModel, field_validator, HttpUrl
from typing import Optional, List
from enum import Enum
from datetime import datetime


class PlatformEnum(str, Enum):
    tiktok = "tiktok"
    instagram = "instagram"
    # Facebook support REMOVED - only TikTok and Instagram now
    # facebook = "facebook"  # DEPRECATED
    youtube = "youtube"


class VideoCreateRequest(BaseModel):
    unit_id: Optional[str] = None  # Optional: null/empty means general content, no product linked
    platform: PlatformEnum
    url: HttpUrl
    product_id: Optional[str] = None  # DEPRECATED - kept for backward compat, not used by backend logic

    @field_validator("unit_id", mode="before")
    @classmethod
    def empty_unit_id_to_none(cls, v):
        if v is not None and isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("url")
    @classmethod
    def url_to_str(cls, v: HttpUrl) -> str:
        return str(v)


class VideoCreateFetchRequest(BaseModel):
    unit_id: Optional[str] = None
    platform: PlatformEnum
    url: HttpUrl
    product_id: Optional[str] = None  # DEPRECATED - kept for backward compat, not used by backend logic


class VideoResponse(BaseModel):
    id: str
    video_id: str
    influencer_id: str
    influencer_name: str
    cabang: str
    unit_id: Optional[str] = None
    unit_label: str
    platform: str
    url: str
    views: int
    likes: int
    comments: int
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    uploaded_at: str
    updated_at: str


class InfluencerDashboardStats(BaseModel):
    total_video: int
    total_views: int
    total_likes: int
    produk_dipromosikan: int
    trend_views: List[dict]  # [{"periode": "2026-W01", "views": 1000}, ...]
    top_videos: List[VideoResponse]


class CatalogItem(BaseModel):
    unit_id: str
    merk: str
    tipe: str
    storage: str
    warna: str
    harga_jual: int
    kategori: str
    has_video: bool
    videos_count: int = 0  # NEW: how many videos already exist for this unit (many-per-product model)
    video_id: Optional[str] = None


class InfluencerProfileResponse(BaseModel):
    id: str
    name: str
    username: str
    cabang: str
    tiktok_username: Optional[str] = None
    instagram_username: Optional[str] = None
    facebook_page: Optional[str] = None


class InfluencerSocialUpdate(BaseModel):
    tiktok_username: Optional[str] = None
    instagram_username: Optional[str] = None
    facebook_page: Optional[str] = None

    @field_validator("tiktok_username", "instagram_username", "facebook_page", mode="before")
    @classmethod
    def strip_if_string(cls, v):
        if v is not None and isinstance(v, str):
            return v.strip() or None
        return v


# Owner monitor schemas
class OwnerInfluencerSummary(BaseModel):
    influencer_id: str
    influencer_name: str
    cabang: str
    total_video: int
    total_views: int
    total_likes: int
    produk_dipromosikan: int
    last_upload: Optional[str] = None


class OwnerInfluencerDashboard(BaseModel):
    total_influencers: int
    total_videos: int
    total_views: int
    total_likes: int
    by_cabang: List[dict]
    top_influencers: List[OwnerInfluencerSummary]
    recent_videos: List[VideoResponse]
