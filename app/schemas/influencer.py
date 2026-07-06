from pydantic import BaseModel, field_validator, HttpUrl
from typing import Optional, List
from enum import Enum
from datetime import datetime


class PlatformEnum(str, Enum):
    tiktok = "tiktok"
    instagram = "instagram"
    facebook = "facebook"
    youtube = "youtube"


class VideoCreateRequest(BaseModel):
    unit_id: str
    platform: PlatformEnum
    url: HttpUrl

    @field_validator("unit_id")
    @classmethod
    def unit_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Unit ID tidak boleh kosong")
        return v.strip()

    @field_validator("url")
    @classmethod
    def url_to_str(cls, v: HttpUrl) -> str:
        return str(v)


class VideoUpdateMetricsRequest(BaseModel):
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None

    @field_validator("views", "likes", "comments", "shares", mode="before")
    @classmethod
    def non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Harus >= 0")
        return v


class VideoResponse(BaseModel):
    id: str
    video_id: str
    influencer_id: str
    influencer_name: str
    cabang: str
    unit_id: str
    unit_label: str
    platform: str
    url: str
    views: int
    likes: int
    comments: int
    shares: int
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
    video_id: Optional[str] = None


class InfluencerProfileResponse(BaseModel):
    id: str
    name: str
    username: str
    cabang: str


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