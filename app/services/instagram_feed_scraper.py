"""
Instagram feed-based scraper.
Uses requests + regex on public Instagram pages (no API key needed).
For better reliability, can also use instagram-scraper (pip install instagram-scraper)
"""
import re
import json
import asyncio
import httpx
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


class InstagramScraperError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class InstagramVideo:
    shortcode: str
    url: str
    views: int
    likes: int
    comments: int
    caption: str
    taken_at: int
    is_video: bool
    thumbnail: str
    author_username: str
    author_full_name: str


class InstagramFeedScraper:
    """
    Scrape Instagram user feed by @username.
    Returns list of InstagramVideo with metrics.
    """
    
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True
        )
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def close(self):
        await self.client.aclose()
    
    async def get_user_posts(self, username: str, count: int = 30) -> List[InstagramVideo]:
        """
        Fetch latest posts from @username feed.
        Uses the public Instagram web page with __a=1 parameter.
        """
        username = username.lstrip("@").strip()
        
        try:
            # First try the __a=1 API endpoint directly
            url = f"https://www.instagram.com/{username}/?__a=1&__d=1"
            resp = await self.client.get(url)
            
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                posts = []
                for item in items:
                    post = self._parse_api_item(item, username)
                    if post:
                        posts.append(post)
                if posts:
                    return posts[:count]
            
            # Fallback: try the HTML page
            url = f"https://www.instagram.com/{username}/"
            resp = await self.client.get(url)
            
            if resp.status_code == 404:
                raise InstagramScraperError(f"User @{username} not found", 404)
            if resp.status_code != 200:
                raise InstagramScraperError(f"Failed to fetch page: {resp.status_code}", resp.status_code)
            
            # Extract shared data from the page
            posts = self._extract_posts_from_html(resp.text, username)
            
            return posts[:count]
            
        except InstagramScraperError:
            raise
        except Exception as e:
            raise InstagramScraperError(f"Failed to fetch @{username}: {str(e)[:200]}", 502)
    
    def _extract_posts_from_html(self, html: str, username: str) -> List[InstagramVideo]:
        """Extract posts from Instagram HTML page."""
        posts = []
        
        # Try to find the additional data script tag
        # Pattern 1: <script type="application/json" data-content-type="feed">{"items":[...]}</script>
        feed_pattern = r'<script[^>]*data-content-type="feed"[^>]*>(.*?)</script>'
        matches = re.findall(feed_pattern, html, re.DOTALL)
        
        if matches:
            for match in matches:
                try:
                    data = json.loads(match)
                    items = data.get("items", [])
                    for item in items:
                        post = self._parse_post_item(item, username)
                        if post:
                            posts.append(post)
                    if posts:
                        return posts
                except json.JSONDecodeError:
                    continue
        
        # Pattern 2: window._sharedData = {...}
        shared_data_pattern = r'window\._sharedData\s*=\s*(\{.*?\});'
        matches = re.findall(shared_data_pattern, html, re.DOTALL)
        
        if matches:
            for match in matches:
                try:
                    data = json.loads(match)
                    entry_data = data.get("entry_data", {})
                    profile_page = entry_data.get("ProfilePage", [])
                    if profile_page:
                        user = profile_page[0].get("graphql", {}).get("user", {})
                        edge_media = user.get("edge_owner_to_timeline_media", {})
                        edges = edge_media.get("edges", [])
                        for edge in edges:
                            node = edge.get("node", {})
                            post = self._parse_graphql_post(node, username)
                            if post:
                                posts.append(post)
                        return posts
                except json.JSONDecodeError:
                    continue
        
        # Pattern 3: __a=1 API endpoint (fallback)
        return self._try_api_endpoint(username)
    
    async def _try_api_endpoint(self, username: str) -> List[InstagramVideo]:
        """Try the __a=1 API endpoint as fallback."""
        # This is a sync fallback - we'll use async version
        return []
    
    def _parse_post_item(self, item: dict, username: str) -> Optional[InstagramVideo]:
        """Parse post from feed items format."""
        try:
            media = item.get("media", item)
            code = media.get("code", media.get("shortcode", ""))
            if not code:
                return None
            
            return InstagramVideo(
                shortcode=code,
                url=f"https://www.instagram.com/p/{code}/",
                views=int(media.get("video_view_count", media.get("play_count", 0))),
                likes=int(media.get("like_count", media.get("likes", 0))),
                comments=int(media.get("comment_count", media.get("comments", 0))),
                caption=media.get("caption", {}).get("text", "") if media.get("caption") else "",
                taken_at=int(media.get("taken_at", media.get("taken_at_timestamp", 0))),
                is_video=media.get("media_type") == 2 or media.get("is_video", False),
                thumbnail=media.get("image_versions2", {}).get("candidates", [{}])[0].get("url", "") if media.get("image_versions2") else media.get("thumbnail_url", ""),
                author_username=username,
                author_full_name=media.get("user", {}).get("full_name", "")
            )
        except Exception:
            return None
    
    def _parse_graphql_post(self, node: dict, username: str) -> Optional[InstagramVideo]:
        """Parse post from GraphQL format."""
        try:
            code = node.get("shortcode", "")
            if not code:
                return None
            
            return InstagramVideo(
                shortcode=code,
                url=f"https://www.instagram.com/p/{code}/",
                views=int(node.get("video_view_count", 0)),
                likes=int(node.get("edge_media_preview_like", {}).get("count", 0)),
                comments=int(node.get("edge_media_to_comment", {}).get("count", 0)),
                caption="",
                taken_at=int(node.get("taken_at_timestamp", 0)),
                is_video=node.get("is_video", False),
                thumbnail=node.get("display_url", ""),
                author_username=username,
                author_full_name=node.get("owner", {}).get("full_name", "")
            )
        except Exception:
            return None
    
    def _parse_api_item(self, item: dict, username: str) -> Optional[InstagramVideo]:
        """Parse post from __a=1 API format."""
        try:
            code = item.get("code", item.get("shortcode", ""))
            if not code:
                return None
            
            return InstagramVideo(
                shortcode=code,
                url=f"https://www.instagram.com/p/{code}/",
                views=int(item.get("video_view_count", item.get("play_count", 0))),
                likes=int(item.get("like_count", item.get("likes", 0))),
                comments=int(item.get("comment_count", item.get("comments", 0))),
                caption=item.get("caption", {}).get("text", "") if item.get("caption") else "",
                taken_at=int(item.get("taken_at_timestamp", item.get("taken_at", 0))),
                is_video=item.get("media_type", 1) == 2,
                thumbnail=item.get("image_versions2", {}).get("candidates", [{}])[0].get("url", "") if item.get("image_versions2") else item.get("thumbnail_url", ""),
                author_username=username,
                author_full_name=item.get("user", {}).get("full_name", "")
            )
        except Exception:
            return None


async def fetch_instagram_feed(username: str, count: int = 30) -> List[Dict[str, Any]]:
    """
    Convenience function: fetch Instagram feed for @username.
    Returns list of dicts compatible with our internal format.
    """
    async with InstagramFeedScraper() as scraper:
        posts = await scraper.get_user_posts(username, count)
        return [p.__dict__ for p in posts]


async def fetch_instagram_post_metrics(username: str, shortcode: str) -> Optional[Dict[str, Any]]:
    """Fetch metrics for single Instagram post by shortcode."""
    async with InstagramFeedScraper() as scraper:
        posts = await scraper.get_user_posts(username, count=50)
        for p in posts:
            if p.shortcode == shortcode:
                return p.__dict__
        return None