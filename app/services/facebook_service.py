"""
Facebook scraper service — auto-fetch video/post metrics via facebook-scraper.
Uses: https://github.com/kevinzg/facebook-scraper
No API key needed, scrapes public pages/posts.
"""
import re
import asyncio
from typing import Optional, Dict, Any


class FacebookAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


def extract_facebook_post_id(url: str) -> Optional[str]:
    """
    Extract post ID / story_fbid from Facebook URL.
    Supports:
    - https://www.facebook.com/{page}/posts/{post_id}
    - https://www.facebook.com/{page}/videos/{video_id}
    - https://www.facebook.com/{page}/reel/{video_id}
    - https://www.facebook.com/{page}/photo/...
    - https://www.facebook.com/story.php?story_fbid={post_id}&id={page_id}
    - https://fb.watch/{shortcode}/
    - https://www.facebook.com/share/v/{video_id}/
    - https://web.facebook.com/...
    - https://m.facebook.com/...
    """
    # story.php format: story_fbid parameter
    match = re.search(r'[?&]story_fbid=(\d+)', url)
    if match:
        return match.group(1)

    # fb.watch short links
    match = re.search(r'fb\.watch/([\w-]+)', url)
    if match:
        return match.group(1)

    # /posts/POST_ID
    match = re.search(r'/posts/([\w-]+)', url)
    if match:
        return match.group(1)

    # /videos/VIDEO_ID or /reel/VIDEO_ID
    match = re.search(r'/(?:videos|reel)/(\d+)', url)
    if match:
        return match.group(1)

    # /photo/...?fbid=FBID
    match = re.search(r'[?&]fbid=(\d+)', url)
    if match:
        return match.group(1)

    # /share/v/VIDEO_ID/
    match = re.search(r'/share/(?:v|r)/([\w-]+)', url)
    if match:
        return match.group(1)

    # Last resort: try to extract any numeric ID from path
    match = re.search(r'/(\d{10,})', url)
    if match:
        return match.group(1)

    return None


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
    if cleaned and cleaned not in ('story.php', 'share', 'photo.php', 'video.php'):
        return cleaned
    return None


async def fetch_post_metrics(post_url: str) -> Dict[str, Any]:
    """
    Fetch Facebook post/video metrics using facebook-scraper.
    Returns: {likes, comments, shares, views, reactions, post_id, page_name, page_id}
    """
    post_id = extract_facebook_post_id(post_url)
    page_name = extract_facebook_page_name(post_url)

    # Run synchronous facebook-scraper in thread pool
    try:
        metrics = await asyncio.to_thread(_scrape_post, post_url, post_id)
        return metrics
    except FacebookAPIError:
        raise
    except Exception as e:
        raise FacebookAPIError(
            f"Facebook scrape failed: {str(e)[:200]}", 502
        )


def _scrape_post(post_url: str, post_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Synchronous wrapper: scrape a single Facebook post by URL.
    """
    from facebook_scraper import get_posts

    posts = list(get_posts(
        post_urls=[post_url],
        pages=1,
        extra_info=True,
        options={"allow_extra_requests": True},
        timeout=30,
    ))

    if not posts:
        # If post_urls didn't work, try with page name + post ID
        if post_id:
            posts = list(get_posts(
                post_urls=[post_id],
                pages=1,
                extra_info=True,
                options={"allow_extra_requests": True},
                timeout=30,
            ))

    if not posts:
        raise FacebookAPIError("Post not found or not accessible", 404)

    post = posts[0]

    if not post.get("available", True):
        raise FacebookAPIError("Post is not available or has been deleted", 404)

    # Extract reactions total (likes in facebook-scraper is sometimes reactions total)
    likes = post.get("likes", 0)
    comments = post.get("comments", 0)
    shares = post.get("shares", 0)

    # Reactions breakdown (if extra_info=True was respected)
    reactions = post.get("reactions", {})
    if isinstance(reactions, dict) and reactions:
        # Use total reactions if likes is 0
        total_reactions = sum(reactions.values())
        if likes == 0 and total_reactions > 0:
            likes = total_reactions

    # Views: Facebook video posts may have this
    # facebook-scraper doesn't consistently expose views,
    # but some post structs have it embedded in the raw data
    views = post.get("views", 0)
    # Try to get video views from raw data
    if views == 0 and post.get("video"):
        views = post.get("video", {}).get("views", 0)

    return {
        "post_id": post.get("post_id", post_id or ""),
        "page_name": post.get("username", ""),
        "page_id": post.get("user_id", ""),
        "likes": int(likes) if likes else 0,
        "comments": int(comments) if comments else 0,
        "shares": int(shares) if shares else 0,
        "views": int(views) if views else 0,
        "reactions": reactions if isinstance(reactions, dict) else {},
        "text": post.get("text", "")[:500],
        "is_video": post.get("video") is not None,
        "video_id": post.get("video_id", ""),
        "post_url": post.get("post_url", post_url),
        "thumbnail": post.get("image", post.get("video_thumbnail", "")),
    }