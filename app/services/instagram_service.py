"""
Instagram service for fetching post/video metrics.
Uses RapidAPI (free-tiktok-api-scraper-mobile-version) for now.
"""
import re
import httpx
import json
from typing import Optional, Dict, Any
from app.config.settings import settings


class InstagramAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


def extract_instagram_shortcode(url: str) -> Optional[str]:
    """
    Extract shortcode from Instagram URL.
    Supports:
    - https://www.instagram.com/p/ABC123/
    - https://www.instagram.com/reel/ABC123/
    - https://www.instagram.com/p/ABC123/?igsh=xxxx
    - https://instagram.com/p/ABC123/
    """
    patterns = [
        r'instagram\.com/(?:p|reel|tv)/([\w-]+)',
        r'instagr\.am/(?:p|reel)/([\w-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


async def fetch_post_metrics(post_url: str) -> Dict[str, Any]:
    """
    Fetch Instagram post metrics.
    Returns: {likes, comments, views, shortcode, caption, owner, is_video}
    """
    shortcode = extract_instagram_shortcode(post_url)
    if not shortcode:
        raise InstagramAPIError("Invalid Instagram URL format", 400)

    # Strategy 1: Try RapidAPI endpoint (same TikTok provider supports Instagram)
    if settings.TIKTOK_RAPIDAPI_KEY:
        headers = {
            "X-RapidAPI-Key": settings.TIKTOK_RAPIDAPI_KEY,
            "X-RapidAPI-Host": settings.TIKTOK_RAPIDAPI_HOST,
        }
        rapid_endpoints = [
            f"{settings.TIKTOK_API_BASE_URL}/instagram/post?url={post_url}",
            f"{settings.TIKTOK_API_BASE_URL}/instagram/media?shortcode={shortcode}",
            f"{settings.TIKTOK_API_BASE_URL}/ig/info?shortcode={shortcode}",
        ]
        async with httpx.AsyncClient(timeout=15.0) as client:
            for endpoint in rapid_endpoints:
                try:
                    resp = await client.get(endpoint, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        return _normalize_rapid_response(data, shortcode)
                except Exception:
                    continue

        # Try TikTok endpoint as generic social media scraper
        try:
            # Some RapidAPI scrapers support both TikTok and Instagram
            resp = await client.get(
                f"{settings.TIKTOK_API_BASE_URL}/social/info?url={post_url}",
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                return _normalize_rapid_response(data, shortcode)
        except Exception:
            pass

    # Strategy 2: Try direct Instagram oEmbed API
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Facebook Graph oEmbed
            resp = await client.get(
                "https://www.instagram.com/p/{}/".format(shortcode),
                params={"__a": 1, "__d": "1"},
                headers={
                    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
                    "Accept": "application/json",
                },
                follow_redirects=True,
            )
            if resp.status_code == 200:
                data = resp.json()
                media = data.get("graphql", {}).get("shortcode_media") or \
                        data.get("items", [{}])[0].get("shortcode_media")
                if media:
                    return _normalize_graphql_response(media, shortcode)
    except Exception:
        pass

    # All strategies failed
    raise InstagramAPIError("Could not fetch Instagram metrics from any provider", 502)


def _normalize_rapid_response(data: dict, shortcode: str) -> Dict[str, Any]:
    """Normalize RapidAPI response for Instagram."""
    # Try different response formats
    media = data.get("data", {}).get("media", data.get("data", data.get("result", data)))
    if not isinstance(media, dict):
        media = data

    return {
        "shortcode": media.get("shortcode", media.get("code", shortcode)),
        "likes": int(media.get("like_count", media.get("likes", media.get("edge_liked_by", {}).get("count", 0)))),
        "comments": int(media.get("comment_count", media.get("comments", media.get("edge_media_to_comment", {}).get("count", 0)))),
        "views": int(media.get("view_count", media.get("views", media.get("video_view_count", 0)))),
        "is_video": media.get("is_video", media.get("media_type", 1) == 2 or media.get("media_type", "") == "VIDEO"),
        "caption": media.get("caption", media.get("caption_text", "")),
        "owner": {
            "id": media.get("owner", {}).get("id", ""),
            "username": media.get("owner", {}).get("username", media.get("user", {}).get("username", "")),
            "full_name": media.get("owner", {}).get("full_name", media.get("user", {}).get("full_name", "")),
        },
        "thumbnail": media.get("thumbnail_url", media.get("display_url", media.get("thumbnail_src", ""))),
        "taken_at": media.get("taken_at_timestamp", media.get("taken_at", 0)),
    }


def _normalize_graphql_response(media: dict, shortcode: str) -> Dict[str, Any]:
    """Normalize Instagram GraphQL response."""
    owner = media.get("owner", {})
    return {
        "shortcode": media.get("shortcode", shortcode),
        "likes": media.get("edge_media_preview_like", {}).get("count", 0),
        "comments": media.get("edge_media_to_comment", {}).get("count", 0),
        "views": media.get("video_view_count", 0),
        "is_video": media.get("is_video", False),
        "caption": (media.get("edge_media_to_caption", {}).get("edges", [{}])[0].get("node", {}).get("text", "")),
        "owner": {
            "id": owner.get("id", ""),
            "username": owner.get("username", ""),
            "full_name": owner.get("full_name", ""),
        },
        "thumbnail": media.get("display_url", ""),
        "taken_at": media.get("taken_at_timestamp", 0),
    }