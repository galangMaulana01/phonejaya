"""
Instagram service - manual "paste link" upload path.
Delegates to instagram_scraper.py (single source of truth for IG scraping
logic - see that file's docstring for why the old __a=1 / RapidAPI approach
was replaced).
"""
from typing import Optional, Dict, Any

from app.services.instagram_scraper import (
    fetch_post_metrics as _fetch_post_metrics,
    extract_shortcode as extract_instagram_shortcode,
    InstagramScraperError as InstagramAPIError,
)

__all__ = ["fetch_post_metrics", "extract_instagram_shortcode", "InstagramAPIError"]


async def fetch_post_metrics(post_url: str) -> Dict[str, Any]:
    """
    Fetch Instagram post metrics.
    Returns: {shortcode, views, likes, comments, is_video, caption, owner, url}
    Raises InstagramAPIError with a specific reason on failure.
    """
    return await _fetch_post_metrics(post_url)
