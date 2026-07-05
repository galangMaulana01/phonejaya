"""
TikTok RapidAPI integration for auto-fetching video metrics.
Uses: https://rapidapi.com/tokinsight/api/free-tiktok-api-scraper-mobile-version
"""
import re
import httpx
from typing import Optional, Dict, Any
from app.config.settings import settings


class TikTokAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


def extract_tiktok_video_id(url: str) -> Optional[str]:
    """
    Extract video ID from TikTok URL.
    Supports formats:
    - https://www.tiktok.com/@username/video/1234567890
    - https://vm.tiktok.com/xxxxxx
    - https://vt.tiktok.com/xxxxxx
    """
    patterns = [
        r'tiktok\.com/@[^/]+/video/(\d+)',
        r'vm\.tiktok\.com/([A-Za-z0-9]+)',
        r'vt\.tiktok\.com/([A-Za-z0-9]+)',
        r'tiktok\.com/.*/video/(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


async def fetch_video_metrics(video_url: str) -> Dict[str, Any]:
    """
    Fetch video metrics from TikTok RapidAPI.
    Returns: {views, likes, comments, shares, video_id, author_username, author_nickname}
    """
    if not settings.TIKTOK_RAPIDAPI_KEY:
        raise TikTokAPIError("TikTok RapidAPI key not configured", 500)

    video_id = extract_tiktok_video_id(video_url)
    if not video_id:
        raise TikTokAPIError("Invalid TikTok URL format", 400)

    headers = {
        "X-RapidAPI-Key": settings.TIKTOK_RAPIDAPI_KEY,
        "X-RapidAPI-Host": settings.TIKTOK_RAPIDAPI_HOST,
    }

    # Try different endpoint patterns based on common RapidAPI TikTok scrapers
    endpoints_to_try = [
        f"{settings.TIKTOK_API_BASE_URL}/video/info?video_id={video_id}",
        f"{settings.TIKTOK_API_BASE_URL}/video/detail?video_id={video_id}",
        f"{settings.TIKTOK_API_BASE_URL}/api/video/info?video_id={video_id}",
        f"{settings.TIKTOK_API_BASE_URL}/video?video_id={video_id}",
        f"{settings.TIKTOK_API_BASE_URL}/video/data?video_id={video_id}",
        f"{settings.TIKTOK_API_BASE_URL}/aweme/v1/aweme/detail/?aweme_id={video_id}",
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        for endpoint in endpoints_to_try:
            try:
                resp = await client.get(endpoint, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return _normalize_response(data, video_id)
                elif resp.status_code == 404:
                    continue  # Try next endpoint
                else:
                    raise TikTokAPIError(
                        f"API error: {resp.status_code} - {resp.text[:200]}",
                        resp.status_code
                    )
            except httpx.TimeoutException:
                continue
            except Exception:
                continue

    raise TikTokAPIError("Failed to fetch video metrics from all endpoints", 502)


def _normalize_response(data: dict, video_id: str) -> Dict[str, Any]:
    """
    Normalize various RapidAPI response formats to standard structure.
    """
    # Common response structures from different TikTok scrapers
    video_data = None

    # Format 1: {data: {video: {...}}}
    if data.get("data", {}).get("video"):
        video_data = data["data"]["video"]
    # Format 2: {data: {...}} direct video object
    elif data.get("data", {}).get("aweme_id"):
        video_data = data["data"]
    # Format 3: {video: {...}}
    elif data.get("video"):
        video_data = data["video"]
    # Format 4: direct object
    elif data.get("aweme_id") or data.get("id"):
        video_data = data
    # Format 5: {item_list: [...]}
    elif data.get("item_list"):
        video_data = data["item_list"][0] if data["item_list"] else None

    if not video_data:
        return {
            "video_id": video_id,
            "views": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "author_username": "",
            "author_nickname": "",
        }

    # Extract stats - try multiple field names
    stats = video_data.get("statistics", video_data.get("stats", video_data))

    views = (
        stats.get("play_count")
        or stats.get("view_count")
        or stats.get("views")
        or stats.get("digg_count")  # sometimes views in digg
        or 0
    )
    likes = (
        stats.get("digg_count")
        or stats.get("like_count")
        or stats.get("likes")
        or 0
    )
    comments = (
        stats.get("comment_count")
        or stats.get("comments")
        or 0
    )
    shares = (
        stats.get("share_count")
        or stats.get("shares")
        or stats.get("forward_count")
        or 0
    )

    author = video_data.get("author", video_data.get("user", {}))
    author_username = author.get("unique_id", author.get("username", ""))
    author_nickname = author.get("nickname", author.get("nick_name", ""))

    return {
        "video_id": video_data.get("aweme_id", video_data.get("id", video_id)),
        "views": int(views) if views else 0,
        "likes": int(likes) if likes else 0,
        "comments": int(comments) if comments else 0,
        "shares": int(shares) if shares else 0,
        "author_username": author_username,
        "author_nickname": author_nickname,
    }