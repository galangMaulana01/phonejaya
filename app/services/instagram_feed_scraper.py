"""
Instagram feed scraper - cron auto-detect path (influencer_sync_service.py).
Delegates to instagram_scraper.py - see that file's docstring for why the
old __a=1 / window._sharedData approach was replaced and what
INSTAGRAM_SESSIONID is needed for.

NOTE ON `count`: Instagram's web_profile_info endpoint only returns the
~12 most recent posts (there is no simple pagination without a rotating
GraphQL query_hash). If `count` > 12, you'll just get up to 12 back - this
is an Instagram platform limitation, not a bug here. For a polling-based
"detect new posts" cron this is normally fine as long as the sync runs
often enough that a page never has more than ~12 new posts between runs.
"""
from typing import Optional, List, Dict, Any

from app.services.instagram_scraper import (
    fetch_user_feed as _fetch_user_feed,
    fetch_post_metrics as _fetch_post_metrics,
    extract_shortcode,
    InstagramScraperError,
)

__all__ = ["fetch_instagram_feed", "fetch_instagram_post_metrics", "InstagramScraperError"]


async def fetch_instagram_feed(username: str, count: int = 30) -> List[Dict[str, Any]]:
    """
    Fetch latest Instagram posts for @username with real engagement metrics.
    Raises InstagramScraperError with a specific reason on failure (e.g. no
    session configured, private account, login wall) - callers already
    catch this and log it per influencer, so one broken account doesn't
    stop the whole sync run.
    """
    return await _fetch_user_feed(username, count=min(count, 12))


async def fetch_instagram_post_metrics(username: str, shortcode: str) -> Optional[Dict[str, Any]]:
    """Fetch metrics for a single Instagram post by shortcode."""
    post_url = f"https://www.instagram.com/p/{shortcode}/"
    return await _fetch_post_metrics(post_url)
