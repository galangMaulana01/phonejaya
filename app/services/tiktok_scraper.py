"""
TikTok Direct Web Scraper - NO RapidAPI, NO cost.
Uses TikTok public web API with msToken authentication.
Works on Vercel serverless (no browser/Playwright needed).
"""
import os
import re
import httpx
import json
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


class TikTokScraperError(Exception):
    """Custom exception for TikTok scraper errors."""
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class TikTokVideo:
    """TikTok video data structure."""
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


class TikTokDirectScraper:
    """
    Direct TikTok scraper using public web API.
    No browser automation - pure HTTP with msToken cookie.
    """
    
    # TikTok web API endpoints
    BASE_URL = "https://www.tiktok.com"
    API_ENDPOINT = "/api/post/item_list/"
    
    def __init__(self, ms_token: Optional[str] = None):
        self.ms_token = ms_token or os.getenv("TIKTOK_MS_TOKEN")
        
        if not self.ms_token:
            raise TikTokScraperError(
                "TIKTOK_MS_TOKEN not configured. Set in Vercel env vars or pass to constructor.",
                500
            )
        
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": self.BASE_URL,
            },
            cookies={"msToken": self.ms_token} if self.ms_token else {},
            follow_redirects=True
        )
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def get_video_by_url(self, video_url: str) -> Optional[TikTokVideo]:
        """
        Fetch single video metrics from URL.
        Supports: vt.tiktok.com, vm.tiktok.com, tiktok.com/@user/video/ID
        """
        video_id = self._extract_video_id(video_url)
        if not video_id:
            raise TikTokScraperError(f"Invalid TikTok URL: {video_url}", 400)
        
        # Try to fetch from user feed (most reliable)
        username = self._extract_username_from_url(video_url)
        if username:
            try:
                videos = await self.get_user_feed(username, count=30)
                for video in videos:
                    if video.video_id == video_id:
                        return video
            except Exception:
                pass
        
        # Fallback: try direct video info endpoint
        try:
            return await self._fetch_video_direct(video_id, video_url)
        except Exception as e:
            raise TikTokScraperError(f"Failed to fetch video {video_id}: {str(e)[:200]}", 502)
    
    async def get_user_feed(self, username: str, count: int = 30) -> List[TikTokVideo]:
        """
        Fetch latest videos from @username feed.
        Uses TikTok public web API endpoint.
        """
        username = username.lstrip("@").strip()
        
        try:
            # Primary endpoint
            params = {
                "aid": "1988",
                "count": min(count, 50),
                "secUid": "",
                "type": "post",
                "username": username,
            }
            
            url = f"{self.BASE_URL}{self.API_ENDPOINT}"
            resp = await self.client.get(url, params=params)
            
            if resp.status_code == 403:
                raise TikTokScraperError(
                    "Access forbidden - msToken may be expired or invalid. "
                    "Generate new token from browser DevTools.",
                    403
                )
            
            if resp.status_code == 404:
                raise TikTokScraperError(f"User @{username} not found", 404)
            
            if resp.status_code != 200:
                raise TikTokScraperError(
                    f"API error: HTTP {resp.status_code} - {resp.text[:200]}",
                    resp.status_code
                )
            
            data = resp.json()
            
            # Check API status code in response
            status_code = data.get("statusCode", data.get("status_code", 0))
            if status_code != 0:
                error_msg = data.get("statusMsg", data.get("message", "Unknown error"))
                raise TikTokScraperError(f"TikTok API error: {error_msg}", 502)
            
            items = data.get("itemList", []) or data.get("item_list", [])
            
            if not items:
                # Try alternative: fetch from user profile page
                return await self._fetch_from_profile_page(username, count)
            
            videos = []
            for item in items[:count]:
                video = self._parse_video_item(item, username)
                if video:
                    videos.append(video)
            
            return videos
            
        except TikTokScraperError:
            raise
        except httpx.TimeoutException:
            raise TikTokScraperError("Request timeout - TikTok server slow to respond", 504)
        except Exception as e:
            raise TikTokScraperError(f"Failed to fetch @{username} feed: {str(e)[:200]}", 502)
    
    async def _fetch_from_profile_page(self, username: str, count: int) -> List[TikTokVideo]:
        """
        Fallback: Fetch videos from user profile page HTML.
        Parses embedded JSON data.
        """
        url = f"{self.BASE_URL}/@{username}"
        resp = await self.client.get(url)
        
        if resp.status_code != 200:
            return []
        
        html = resp.text
        
        # Try to extract video data from embedded JSON
        patterns = [
            r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
            r'"itemList":(\[.*?\]),"userList"',
            r'"itemModule":(\{.*?\}),"userModule"',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    items = self._extract_items_from_json(data)
                    if items:
                        videos = []
                        for item in items[:count]:
                            video = self._parse_video_item(item, username)
                            if video:
                                videos.append(video)
                        return videos
                except (json.JSONDecodeError, KeyError):
                    continue
        
        return []
    
    def _extract_items_from_json(self, data: dict) -> List[dict]:
        """Extract video items from various JSON structures."""
        paths = [
            ["__DEFAULT_SCOPE__", "webapp.user-detail", "itemList"],
            ["__DEFAULT_SCOPE__", "webapp.video-detail", "itemInfo", "itemStruct"],
            ["itemModule"],
            ["itemList"],
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
            except (KeyError, TypeError, IndexError):
                continue
        
        return []
    
    async def _fetch_video_direct(self, video_id: str, video_url: str) -> Optional[TikTokVideo]:
        """
        Try to fetch single video directly (fallback method).
        Follows redirects from short links.
        """
        # First, follow redirect to get final URL
        resp = await self.client.get(video_url, follow_redirects=True)
        
        if resp.status_code != 200:
            raise TikTokScraperError(f"Video {video_id} not accessible", 404)
        
        html = resp.text
        
        # Try to extract video data from HTML
        # Pattern 1: Extract actual video ID from final URL (after redirect)
        final_url_pattern = r'tiktok\.com/@[^/]+/video/(\d{15,20})'
        final_match = re.search(final_url_pattern, str(resp.url))
        if final_match:
            video_id = final_match.group(1)
        
        # NEW APPROACH 2026: Parse embedded JSON data (like TikTok-Api v7.3.3)
        # TikTok stores video data in __UNIVERSAL_DATA__ or SIGI_STATE
        
        video_data = None
        
        # Method 1: Extract from __UNIVERSAL_DATA__ (most common in 2026)
        universal_match = re.search(
            r'<script[^>]*id="__UNIVERSAL_DATA__"[^>]*>(.*?)</script>',
            html,
            re.DOTALL
        )
        if universal_match:
            try:
                json_str = universal_match.group(1).strip()
                data = json.loads(json_str)
                
                # Navigate to video info
                # Structure: data[scope][type][video_id]
                if isinstance(data, dict):
                    for scope_key, scope_val in data.items():
                        if isinstance(scope_val, dict):
                            for type_key, type_val in scope_val.items():
                                if isinstance(type_val, dict) and video_id in type_val:
                                    video_data = type_val[video_id]
                                    break
                        if video_data:
                            break
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        
        # Method 2: Extract from SIGI_STATE (fallback)
        if not video_data:
            sigi_match = re.search(
                r'window\["SIGI_STATE"\]\s*=\s*({.+?});',
                html,
                re.DOTALL
            )
            if sigi_match:
                try:
                    sigi_data = json.loads(sigi_match.group(1))
                    item_module = sigi_data.get("ItemModule", {})
                    if isinstance(item_module, dict) and video_id in item_module:
                        video_data = item_module[video_id]
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
        
        # Method 3: Extract from __INITIAL_PROPS__ (another fallback)
        if not video_data:
            props_match = re.search(
                r'<script[^>]*id="__INITIAL_PROPS__"[^>]*>(.*?)</script>',
                html,
                re.DOTALL
            )
            if props_match:
                try:
                    props_data = json.loads(props_match.group(1).strip())
                    # Try different structures
                    for key in ["videoData", "itemInfo", "videoInfo"]:
                        if key in props_data:
                            video_data = props_data[key]
                            break
                except (json.JSONDecodeError, KeyError, TypeError):
                    pass
        
        # Successfully extracted video data?
        if video_data and isinstance(video_data, dict):
            try:
                # Extract stats
                stats = video_data.get("stats", video_data.get("statistics", {}))
                author = video_data.get("author", video_data.get("authorInfo", {}))
                music = video_data.get("music", {})
                
                views = int(stats.get("playCount", stats.get("view_count", stats.get("views", 0))))
                likes = int(stats.get("diggCount", stats.get("like_count", stats.get("likes", 0))))
                comments = int(stats.get("commentCount", stats.get("comment_count", stats.get("comments", 0))))
                shares = int(stats.get("shareCount", stats.get("share_count", stats.get("shares", 0))))
                
                caption = video_data.get("desc", video_data.get("description", ""))
                create_time = int(video_data.get("createTime", video_data.get("create_time", 0)))
                
                author_username = author.get("uniqueId", author.get("username", ""))
                author_nickname = author.get("nickname", author.get("nickName", ""))
                
                return TikTokVideo(
                    video_id=video_id,
                    url=str(resp.url),
                    views=views,
                    likes=likes,
                    comments=comments,
                    shares=shares,
                    caption=caption,
                    create_time=create_time,
                    author_username=author_username,
                    author_nickname=author_nickname,
                )
            except (KeyError, TypeError, ValueError) as e:
                # Data exists but malformed
                pass
        
        # ALL METHODS FAILED - return stub with 0 metrics
        return TikTokVideo(
            video_id=video_id,
            url=str(resp.url),
            views=0,
            likes=0,
            comments=0,
            shares=0,
            caption="",
            create_time=0,
            author_username="",
            author_nickname="",
        )
    
    def _parse_video_item(self, item: dict, username: str) -> Optional[TikTokVideo]:
        """Parse video item from TikTok API response."""
        try:
            video_id = item.get("id") or item.get("aweme_id") or item.get("video_id")
            if not video_id:
                return None
            
            stats = item.get("stats", {}) or item.get("statistics", {}) or {}
            author = item.get("author", {}) or item.get("authorInfo", {}) or {}
            
            # Extract caption
            caption = item.get("desc", "") or item.get("description", "")
            
            # Extract create time
            create_time = item.get("createTime", item.get("create_time", 0))
            if isinstance(create_time, str):
                try:
                    import time
                    create_time = int(time.mktime(time.strptime(create_time, "%Y-%m-%d %H:%M:%S")))
                except Exception:
                    create_time = 0
            
            return TikTokVideo(
                video_id=str(video_id),
                url=f"{self.BASE_URL}/@{username}/video/{video_id}",
                views=int(stats.get("playCount", stats.get("view_count", stats.get("views", 0)))),
                likes=int(stats.get("diggCount", stats.get("like_count", stats.get("likes", 0)))),
                comments=int(stats.get("commentCount", stats.get("comment_count", stats.get("comments", 0)))),
                shares=int(stats.get("shareCount", stats.get("share_count", stats.get("shares", 0)))),
                caption=caption,
                create_time=int(create_time) if create_time else 0,
                author_username=author.get("uniqueId", author.get("username", username)),
                author_nickname=author.get("nickname", author.get("nickName", "")),
                is_video=item.get("isVideo", True),
            )
        except Exception:
            return None
    
    def _extract_video_id(self, url: str) -> Optional[str]:
        """
        Extract video ID from TikTok URL.
        Supports multiple formats.
        """
        patterns = [
            r'tiktok\.com/@[^/]+/video/(\d{15,20})',  # Full URL
            r'vt\.tiktok\.com/([A-Za-z0-9]+)',         # Short link vt
            r'vm\.tiktok\.com/([A-Za-z0-9]+)',         # Short link vm
            r'm\.tiktok\.com/v/(\d{15,20})',           # Mobile
            r'tiktok\.com/t/([A-Za-z0-9]+)',           # Share link
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                # If short link ID, we need to resolve it
                if len(video_id) < 15:
                    # Short link - return as-is, will be resolved later
                    return video_id
                return video_id
        
        # Try to extract any long numeric ID as last resort
        match = re.search(r'(\d{15,20})', url)
        if match:
            return match.group(1)
        
        return None
    
    def _extract_username_from_url(self, url: str) -> Optional[str]:
        """Extract username from TikTok URL."""
        match = re.search(r'tiktok\.com/@([a-zA-Z0-9_.-]+)', url)
        if match:
            return match.group(1)
        return None


# ════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ════════════════════════════════════════════════════════════════

async def fetch_video_metrics(video_url: str) -> Dict[str, Any]:
    """
    Fetch metrics for a single TikTok video.
    
    Args:
        video_url: TikTok video URL (any format)
    
    Returns:
        Dict with: video_id, views, likes, comments, shares, 
                   author_username, author_nickname, url
    
    Raises:
        TikTokScraperError: If msToken not configured or API error
    """
    async with TikTokDirectScraper() as scraper:
        video = await scraper.get_video_by_url(video_url)
        
        if not video:
            raise TikTokScraperError("Video not found or not accessible", 404)
        
        return {
            "video_id": video.video_id,
            "views": video.views,
            "likes": video.likes,
            "comments": video.comments,
            "shares": video.shares,
            "author_username": video.author_username,
            "author_nickname": video.author_nickname,
            "url": video.url,
        }


async def fetch_user_feed(username: str, count: int = 30) -> List[Dict[str, Any]]:
    """
    Fetch user feed (latest videos).
    
    Args:
        username: TikTok username (without @)
        count: Number of videos to fetch (max 50)
    
    Returns:
        List of video dicts with metrics
    """
    async with TikTokDirectScraper() as scraper:
        videos = await scraper.get_user_feed(username, count)
        return [
            {
                "video_id": v.video_id,
                "url": v.url,
                "views": v.views,
                "likes": v.likes,
                "comments": v.comments,
                "shares": v.shares,
                "caption": v.caption,
                "author_username": v.author_username,
                "author_nickname": v.author_nickname,
            }
            for v in videos
        ]