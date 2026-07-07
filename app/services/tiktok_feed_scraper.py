"""
TikTok feed-based scraper using simple HTTP requests.
No TikTokApi/playwright/pyppeteer needed - works on Vercel serverless.
Uses public TikTok web endpoints with ms_token authentication.
"""
import os
import asyncio
import httpx
import re
import json
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


class TikTokScraperError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class TikTokVideo:
    video_id: str
    url: str
    views: int
    likes: int
    comments: int
    shares: int
    caption: str
    create_time: int
    author_username: str
    author_nickname: str
    is_video: bool = True


class TikTokFeedScraper:
    """
    Scrape TikTok user feed by @username using public web endpoints.
    No browser automation needed - uses simple HTTP with ms_token cookie.
    """
    
    def __init__(self, ms_token: Optional[str] = None):
        self.ms_token = ms_token or os.getenv("TIKTOK_MS_TOKEN")
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.tiktok.com/",
            },
            cookies={"msToken": self.ms_token} if self.ms_token else {},
            follow_redirects=True
        )
    
    async def __aenter__(self):
        if not self.ms_token:
            raise TikTokScraperError("TIKTOK_MS_TOKEN not configured. Set in env or pass to constructor.", 500)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def get_user_videos(self, username: str, count: int = 30) -> List[TikTokVideo]:
        """
        Fetch latest videos from @username feed.
        Uses TikTok's public web API endpoint.
        """
        if not self.ms_token:
            raise TikTokScraperError("ms_token not configured", 500)
        
        username = username.lstrip("@").strip()
        
        try:
            # Try the web API endpoint that TikTok uses
            url = f"https://www.tiktok.com/api/post/item_list/?aid=1988&count={count}&secUid=&type=1&username={username}"
            
            resp = await self.client.get(url)
            
            if resp.status_code == 403:
                raise TikTokScraperError("Access forbidden - ms_token may be expired or invalid", 403)
            if resp.status_code == 404:
                raise TikTokScraperError(f"User @{username} not found", 404)
            if resp.status_code != 200:
                raise TikTokScraperError(f"Failed to fetch feed: HTTP {resp.status_code}", resp.status_code)
            
            data = resp.json()
            
            if data.get("statusCode") != 0 and data.get("status_code") != 0:
                raise TikTokScraperError(f"API error: {data.get('statusMsg', 'Unknown error')}", 502)
            
            items = data.get("itemList", []) or data.get("item_list", [])
            
            if not items:
                # Try alternative endpoint
                return await self._try_alternative_endpoint(username, count)
            
            videos = []
            for item in items[:count]:
                videos.append(self._parse_video_item(item, username))
            
            return videos
            
        except TikTokScraperError:
            raise
        except Exception as e:
            raise TikTokScraperError(f"Failed to fetch @{username}: {str(e)[:200]}", 502)
    
    async def _try_alternative_endpoint(self, username: str, count: int) -> List[TikTokVideo]:
        """Try alternative TikTok web API endpoint."""
        url = f"https://www.tiktok.com/@{username}"
        resp = await self.client.get(url)
        
        if resp.status_code != 200:
            return []
        
        # Extract from HTML - look for the script tag with video data
        html = resp.text
        
        # Pattern 1: window._sharedData
        patterns = [
            r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            r'window\._sharedData\s*=\s*(\{.*?\});',
            r'"ItemModule":(\{.*?\}),"UserModule"',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    items = self._extract_items_from_html_data(data)
                    if items:
                        videos = []
                        for item in items[:count]:
                            videos.append(self._parse_video_item(item, username))
                        return videos
                except json.JSONDecodeError:
                    continue
        
        return []
    
    def _extract_items_from_html_data(self, data: dict) -> List[dict]:
        """Extract video items from various HTML data formats."""
        # Try different known structures
        paths = [
            ["__DEFAULT_SCOPE__", "webapp.video-detail", "itemInfo", "itemStruct"],
            ["__DEFAULT_SCOPE__", "webapp.user-detail", "itemList"],
            ["ItemModule"],
            ["props", "pageProps", "items"],
            ["props", "pageProps", "videoData", "itemInfos"],
        ]
        
        for path in paths:
            current = data
            try:
                for key in path:
                    current = current[key]
                if isinstance(current, list):
                    return current
                elif isinstance(current, dict):
                    return list(current.values())
            except (KeyError, TypeError):
                continue
        
        return []
    
    def _parse_video_item(self, item: dict, username: str) -> TikTokVideo:
        """Parse video item from TikTok API response."""
        # Handle different possible structures
        video_id = item.get("id") or item.get("video_id") or item.get("aweme_id") or ""
        
        stats = item.get("stats", {}) or item.get("statistics", {}) or {}
        author = item.get("author", {}) or item.get("authorInfo", {}) or {}
        
        return TikTokVideo(
            video_id=str(video_id),
            url=f"https://www.tiktok.com/@{username}/video/{video_id}",
            views=int(stats.get("playCount", stats.get("view_count", 0))),
            likes=int(stats.get("diggCount", stats.get("like_count", 0))),
            comments=int(stats.get("commentCount", stats.get("comment_count", 0))),
            shares=int(stats.get("shareCount", stats.get("share_count", 0))),
            caption=item.get("desc", item.get("description", "")),
            create_time=int(item.get("createTime", item.get("create_time", 0))),
            author_username=username,
            author_nickname=author.get("nickname", author.get("unique_id", "")),
            is_video=item.get("isVideo", item.get("video", {}).get("duration", 0) > 0) if item.get("video") else True
        )
    
    async def get_video_by_id(self, username: str, video_id: str) -> Optional[TikTokVideo]:
        """Fetch single video by ID from user feed."""
        videos = await self.get_user_videos(username, count=50)
        for v in videos:
            if v.video_id == video_id:
                return v
        return None


async def fetch_tiktok_feed(username: str, count: int = 30, ms_token: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Convenience function: fetch TikTok feed for @username.
    Returns list of dicts compatible with our internal format.
    """
    async with TikTokFeedScraper(ms_token) as scraper:
        videos = await scraper.get_user_videos(username, count)
        return [v.__dict__ for v in videos]


async def fetch_tiktok_video_metrics(username: str, video_id: str, ms_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch metrics for single TikTok video."""
    async with TikTokFeedScraper(ms_token) as scraper:
        video = await scraper.get_video_by_id(username, video_id)
        return video.__dict__ if video else None
