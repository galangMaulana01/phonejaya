"""
TikTok feed-based scraper using TikTokApi (davidteather/TikTok-Api).
Fetches latest videos from @username feed, no RapidAPI needed.
Requires: ms_token from TikTok cookies (set in env or config)
"""
import os
import asyncio
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

try:
    from TikTokApi import TikTokApi
except ImportError:
    TikTokApi = None


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
    Scrape TikTok user feed by @username.
    Returns list of TikTokVideo with metrics.
    """
    
    def __init__(self, ms_token: Optional[str] = None):
        self.ms_token = ms_token or os.getenv("TIKTOK_MS_TOKEN")
        self._api = None
    
    async def __aenter__(self):
        if not TikTokApi:
            raise TikTokScraperError("TikTokApi not installed. pip install TikTokApi", 500)
        if not self.ms_token:
            raise TikTokScraperError("TIKTOK_MS_TOKEN not configured", 500)
        
        self._api = TikTokApi()
        await self._api.create_sessions(
            ms_tokens=[self.ms_token],
            num_sessions=1,
            sleep_after=3,
            browser=os.getenv("TIKTOK_BROWSER", "chromium")
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._api:
            await self._api.close_sessions()
    
    async def get_user_videos(self, username: str, count: int = 30) -> List[TikTokVideo]:
        """
        Fetch latest videos from @username feed.
        Returns list of TikTokVideo with metrics.
        """
        if not self._api:
            raise TikTokScraperError("Scraper not initialized. Use async with.", 500)
        
        # Clean username
        username = username.lstrip("@").strip()
        
        try:
            user = self._api.user(username=username)
            videos = []
            async for video in user.videos(count=count):
                v = video.as_dict
                videos.append(TikTokVideo(
                    video_id=v.get("id", ""),
                    url=f"https://www.tiktok.com/@{username}/video/{v.get('id', '')}",
                    views=int(v.get("stats", {}).get("playCount", 0)),
                    likes=int(v.get("stats", {}).get("diggCount", 0)),
                    comments=int(v.get("stats", {}).get("commentCount", 0)),
                    shares=int(v.get("stats", {}).get("shareCount", 0)),
                    caption=v.get("desc", ""),
                    create_time=int(v.get("createTime", 0)),
                    author_username=username,
                    author_nickname=v.get("author", {}).get("nickname", ""),
                    is_video=True
                ))
            return videos
        except Exception as e:
            raise TikTokScraperError(f"Failed to fetch @{username}: {str(e)[:200]}", 502)
    
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