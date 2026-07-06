"""
Facebook feed-based scraper using facebook-scraper.
Fetches latest posts from a Facebook page feed.
"""
import asyncio
import re
from typing import Optional, List, Dict, Any


class FacebookFeedScraperError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


def extract_facebook_page_name(url: str) -> Optional[str]:
    """
    Extract page/username from Facebook URL.
    Returns the page name or None if not found.
    """
    # Remove protocol and domain variations
    cleaned = re.sub(r'^https?://(?:www\.|web\.|m\.|mbasic\.)?facebook\.com/', '', url)
    # Remove query params
    cleaned = cleaned.split('?')[0].split('/')[0]
    # Skip if it's a direct ID or share link
    if cleaned and cleaned not in ('story.php', 'share', 'photo.php', 'video.php', 'groups', 'pages'):
        return cleaned
    return None


async def fetch_page_feed(page_name: str, count: int = 30) -> List[Dict[str, Any]]:
    """
    Fetch latest posts from a Facebook page feed.
    Returns list of post dicts with metrics.
    """
    page_name = page_name.strip()
    if page_name.startswith('@'):
        page_name = page_name[1:]
    
    try:
        posts = await asyncio.to_thread(_scrape_page_feed, page_name, count)
        return posts
    except FacebookFeedScraperError:
        raise
    except Exception as e:
        raise FacebookFeedScraperError(
            f"Facebook feed scrape failed: {str(e)[:200]}", 502
        )


def _scrape_page_feed(page_name: str, count: int) -> List[Dict[str, Any]]:
    """
    Synchronous wrapper: scrape a Facebook page's feed.
    """
    from facebook_scraper import get_posts
    
    # Get posts from the page
    posts_gen = get_posts(
        page_name,
        pages=1,
        extra_info=True,
        options={"allow_extra_requests": True},
        timeout=30,
    )
    
    posts = []
    for post in posts_gen:
        if len(posts) >= count:
            break
        if not post.get("available", True):
            continue
        
        # Extract metrics
        likes = post.get("likes", 0)
        comments = post.get("comments", 0)
        shares = post.get("shares", 0)
        
        reactions = post.get("reactions", {})
        if isinstance(reactions, dict) and reactions:
            total_reactions = sum(reactions.values())
            if likes == 0 and total_reactions > 0:
                likes = total_reactions
        
        views = post.get("views", 0)
        if views == 0 and post.get("video"):
            views = post.get("video", {}).get("views", 0)
        
        posts.append({
            "post_id": post.get("post_id", ""),
            "page_name": post.get("username", page_name),
            "page_id": post.get("user_id", ""),
            "likes": int(likes) if likes else 0,
            "comments": int(comments) if comments else 0,
            "shares": int(shares) if shares else 0,
            "views": int(views) if views else 0,
            "reactions": reactions if isinstance(reactions, dict) else {},
            "text": post.get("text", "")[:500],
            "is_video": post.get("video") is not None,
            "video_id": post.get("video_id", ""),
            "post_url": post.get("post_url", ""),
            "thumbnail": post.get("image", post.get("video_thumbnail", "")),
            "time": post.get("time", "").isoformat() if hasattr(post.get("time"), "isoformat") else str(post.get("time", "")),
        })
    
    return posts


async def fetch_facebook_post_metrics(page_name: str, post_id: str) -> Optional[Dict[str, Any]]:
    """Fetch metrics for a single Facebook post by post_id from page feed."""
    posts = await fetch_page_feed(page_name, count=50)
    for post in posts:
        if post.get("post_id") == post_id:
            return post
    return None


async def fetch_facebook_video_metrics(page_name: str, video_id: str) -> Optional[Dict[str, Any]]:
    """Fetch metrics for a single Facebook video by video_id from page feed."""
    posts = await fetch_page_feed(page_name, count=50)
    for post in posts:
        if post.get("video_id") == video_id or post.get("post_id") == video_id:
            return post
    return None