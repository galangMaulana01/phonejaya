"""
TikTok feed scraper used by the hourly cron sync (influencer_sync_service.py).

This used to be a second, independent implementation of the same broken
logic as tiktok_scraper.py (empty secUid, wrong script-tag id, silent
zero-fallback) - two copies of the same bug that could drift apart over
time. It now delegates to the single, fixed TikTokDirectScraper so there is
one source of truth for TikTok scraping logic.

Public function signatures (fetch_tiktok_feed, fetch_tiktok_video_metrics)
are kept identical so influencer_sync_service.py doesn't need any changes.
"""
from typing import Optional, List, Dict, Any

from app.services.tiktok_scraper import TikTokDirectScraper, TikTokScraperError

__all__ = ["fetch_tiktok_feed", "fetch_tiktok_video_metrics", "TikTokScraperError"]


async def fetch_tiktok_feed(
    username: str, count: int = 30, ms_token: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Fetch TikTok feed for @username with real engagement metrics.

    Raises TikTokScraperError with a specific reason on failure - callers
    (influencer_sync_service.py) already catch this and log it, which is
    correct. What changed is that a failure now actually raises instead of
    silently returning empty/zeroed data, so real problems show up in logs
    instead of looking like "0 views on every video".
    """
    async with TikTokDirectScraper(ms_token) as scraper:
        videos = await scraper.get_user_feed(username, count)
        return [v.__dict__ for v in videos]


async def fetch_tiktok_video_metrics(
    username: str, video_id: str, ms_token: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Fetch metrics for a single TikTok video, given username + video_id."""
    async with TikTokDirectScraper(ms_token) as scraper:
        video_url = f"{scraper.BASE_URL}/@{username}/video/{video_id}"
        video = await scraper.get_video_by_url(video_url)
        return video.__dict__ if video else None
