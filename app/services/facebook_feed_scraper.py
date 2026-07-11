"""
Facebook feed scraper - cron auto-detect path (influencer_sync_service.py).
Delegates to facebook_direct_scraper.py - see that file's docstring for
the cookie/login handling this adds on top of the facebook-scraper library.
"""
from typing import Optional, List, Dict, Any

from app.services.facebook_direct_scraper import (
    get_page_feed as _get_page_feed,
    get_post_by_url as _get_post_by_url,
    FacebookScraperError as FacebookFeedScraperError,
)

__all__ = [
    "fetch_page_feed",
    "fetch_facebook_post_metrics",
    "fetch_facebook_video_metrics",
    "FacebookFeedScraperError",
]


async def fetch_page_feed(page_name: str, count: int = 30) -> List[Dict[str, Any]]:
    """
    Fetch latest posts from a Facebook page's feed with real engagement metrics.
    Raises FacebookFeedScraperError with a specific reason on failure - callers
    already catch this per-influencer so one broken page doesn't stop the sync.
    """
    return await _get_page_feed(page_name, count)


async def fetch_facebook_post_metrics(page_name: str, post_id: str) -> Optional[Dict[str, Any]]:
    """Fetch metrics for a single Facebook post by post_id from the page feed."""
    posts = await _get_page_feed(page_name, count=50)
    for post in posts:
        if post.get("post_id") == post_id:
            return post
    return None


async def fetch_facebook_video_metrics(page_name: str, video_id: str) -> Optional[Dict[str, Any]]:
    """Fetch metrics for a single Facebook video by video_id from the page feed."""
    posts = await _get_page_feed(page_name, count=50)
    for post in posts:
        if post.get("video_id") == video_id or post.get("post_id") == video_id:
            return post
    return None
