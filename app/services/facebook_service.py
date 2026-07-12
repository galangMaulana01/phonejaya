"""
Facebook service - SIMPLE PYTHON ONLY (no Node.js, no Playwright)
Delegates to facebook_simple_scraper.py - pure Python facebook-scraper library.
"""
import re
from typing import Optional, Dict, Any

from app.services.facebook_simple_scraper import (
    get_post_by_url as _get_post_by_url,
    FacebookScraperError as FacebookAPIError,
)

__all__ = ["fetch_post_metrics", "extract_facebook_post_id", "extract_facebook_page_name", "FacebookAPIError"]


def extract_facebook_post_id(url: str) -> Optional[str]:
    """Extract post ID / story_fbid from a Facebook URL."""
    match = re.search(r'[?&]story_fbid=(\d+)', url)
    if match:
        return match.group(1)
    match = re.search(r'fb\.watch/([\w-]+)', url)
    if match:
        return match.group(1)
    match = re.search(r'/posts/([\w-]+)', url)
    if match:
        return match.group(1)
    match = re.search(r'/(?:videos|reel)/(\d+)', url)
    if match:
        return match.group(1)
    match = re.search(r'[?&]fbid=(\d+)', url)
    if match:
        return match.group(1)
    match = re.search(r'/share/(?:v|r|p)/([\w-]+)', url)
    if match:
        return match.group(1)
    match = re.search(r'/(\d{10,})', url)
    if match:
        return match.group(1)
    return None


def extract_facebook_page_name(url: str) -> Optional[str]:
    """Extract page/username from a Facebook URL."""
    cleaned = re.sub(r'^https?://(?:www\.|web\.|m\.|mbasic\.)?facebook\.com/', '', url)
    cleaned = cleaned.split('?')[0].split('/')[0]
    if cleaned and cleaned not in ('story.php', 'share', 'photo.php', 'video.php'):
        return cleaned
    return None


async def fetch_post_metrics(post_url: str) -> Dict[str, Any]:
    """
    Fetch Facebook post/video metrics.
    Returns: {likes, comments, shares, views, reactions, post_id, page_name, page_id, ...}
    Raises FacebookAPIError with a specific reason on failure.
    """
    post_id = extract_facebook_post_id(post_url)
    return await _get_post_by_url(post_url, post_id)
