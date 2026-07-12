"""
Facebook Scraper - SIMPLE PYTHON ONLY (no Node.js, no Playwright)

Uses facebook-scraper library (https://pypi.org/project/facebook-scraper/)

REQUIREMENTS:
- facebook-scraper installed: pip install facebook-scraper
- Facebook session cookies: FACEBOOK_C_USER and FACEBOOK_XS env vars

HOW TO GET COOKIES:
1. Login to Facebook in your browser
2. Open DevTools (F12) → Application → Cookies → https://www.facebook.com
3. Copy the values of:
   - c_user (your user ID)
   - xs (session token, format: randomstring:timestamp:other)
4. Set as environment variables in Vercel:
   - FACEBOOK_C_USER = <paste c_user value>
   - FACEBOOK_XS = <paste xs value>

NOTE: Cookies expire every 30-60 days. Refresh when scraping fails.
"""
import os
import logging
from typing import Optional, Dict, Any

from facebook_scraper import get_posts, set_cookies
from facebook_scraper.exceptions import LoginRequired, NotFound, TemporarilyBanned

logger = logging.getLogger(__name__)


class FacebookScraperError(Exception):
    """Custom exception for Facebook scraping errors."""
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


_cookies_initialized = False


def _ensure_cookies_configured() -> bool:
    """
    Configure facebook-scraper with session cookies from env vars.
    Returns True if cookies are configured, False otherwise.
    Raises FacebookScraperError if cookies are invalid.
    """
    global _cookies_initialized
    
    if _cookies_initialized:
        return True
    
    c_user = (os.getenv("FACEBOOK_C_USER") or "").strip()
    xs = (os.getenv("FACEBOOK_XS") or "").strip()
    
    if not c_user or not xs:
        logger.warning("FACEBOOK_C_USER or FACEBOOK_XS not configured - scraping will be limited to public posts")
        return False
    
    # Validate ASCII (catch copy-paste artifacts)
    try:
        c_user.encode("ascii")
        xs.encode("ascii")
    except UnicodeEncodeError as e:
        raise FacebookScraperError(
            f"Cookie contains non-ASCII character at position {e.start} - "
            "re-copy from browser DevTools, ensure no extra spaces/quotes",
            400
        )
    
    try:
        set_cookies({"c_user": c_user, "xs": xs})
        logger.info("Facebook cookies configured successfully")
        _cookies_initialized = True
        return True
    except Exception as e:
        logger.error(f"Failed to set Facebook cookies: {e}")
        raise FacebookScraperError(
            f"Invalid Facebook cookies - session may be expired or account flagged. "
            f"Re-login and refresh FACEBOOK_C_USER and FACEBOOK_XS. Error: {e}",
            401
        )


def _post_to_dict(post: dict) -> Dict[str, Any]:
    """Convert facebook-scraper post dict to our standard format."""
    # Handle reactions → likes
    likes = post.get("likes", 0)
    if not likes and post.get("reactions"):
        reactions = post.get("reactions", {})
        if isinstance(reactions, dict):
            likes = sum(reactions.values())
    
    # Handle video views
    views = post.get("views", 0) or post.get("video_views", 0) or 0
    
    return {
        "post_id": post.get("post_id", ""),
        "page_name": post.get("username", "") or post.get("page_name", ""),
        "page_id": post.get("user_id", ""),
        "likes": int(likes) if likes else 0,
        "comments": int(post.get("comments", 0)) if post.get("comments") else 0,
        "shares": int(post.get("shares", 0)) if post.get("shares") else 0,
        "views": int(views) if views else 0,
        "reactions": post.get("reactions", {}) if isinstance(post.get("reactions"), dict) else {},
        "text": (post.get("text") or "")[:500],
        "is_video": post.get("video") is not None,
        "video_id": post.get("video_id", ""),
        "post_url": post.get("post_url", ""),
        "image": post.get("image", ""),
        "time": str(post.get("time", "")) if post.get("time") else "",
    }


async def fetch_post_metrics(post_url: str) -> Dict[str, Any]:
    """
    Fetch Facebook post metrics (likes, comments, shares, views).
    
    SIMPLE PYTHON-ONLY IMPLEMENTATION:
    - No Node.js
    - No Playwright
    - No browser automation
    - Uses facebook-scraper library with HTTP requests
    
    Args:
        post_url: Facebook post URL (e.g., https://www.facebook.com/share/p/ABC123/)
    
    Returns:
        Dict with metrics: {likes, comments, shares, views, post_id, page_name, ...}
    
    Raises:
        FacebookScraperError: with specific reason (login required, not found, etc.)
    """
    # Configure cookies (if available)
    _ensure_cookies_configured()
    
    logger.info(f"Scraping Facebook post: {post_url[:80]}")
    
    try:
        posts = list(get_posts(
            post_urls=[post_url],  # type: ignore
            options={
                "allow_extra_requests": True,
                "remove_expired": False,
            },
            extra_info=True,
            timeout=30
        ))
        
        if not posts:
            raise FacebookScraperError(
                f"Post not found or inaccessible: {post_url}. "
                "It may be private, deleted, or requires login.",
                404
            )
        
        post = posts[0]
        
        # Check if post is available
        if not post.get("available", True):
            raise FacebookScraperError(
                f"Post is not available (may have been deleted or made private)",
                404
            )
        
        result = _post_to_dict(post)
        
        logger.info(
            f"Facebook scraping success: {result['likes']} likes, "
            f"{result['comments']} comments, {result['shares']} shares"
        )
        
        return result
        
    except LoginRequired:
        raise FacebookScraperError(
            "This post requires a logged-in Facebook session. "
            "Configure FACEBOOK_C_USER and FACEBOOK_XS environment variables "
            "with cookies from a logged-in account.",
            401
        )
    except NotFound:
        raise FacebookScraperError(
            f"Post not found: {post_url}. It may have been deleted or the URL is incorrect.",
            404
        )
    except TemporarilyBanned:
        raise FacebookScraperError(
            "Facebook has temporarily blocked scraping requests. "
            "Wait a few minutes and try again, or slow down the scraping frequency.",
            429
        )
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"Facebook scraping failed: {error_msg}")
        
        # Check for common error patterns
        if "login" in error_msg.lower() or "sign in" in error_msg.lower():
            raise FacebookScraperError(
                f"Facebook requires login: {error_msg[:200]}. "
                "Configure FACEBOOK_C_USER and FACEBOOK_XS.",
                401
            )
        elif "not found" in error_msg.lower() or "404" in error_msg:
            raise FacebookScraperError(
                f"Post not found: {error_msg[:200]}",
                404
            )
        else:
            raise FacebookScraperError(
                f"Facebook scraping failed: {error_msg[:200]}",
                500
            )


# Convenience function for influencer service
async def get_post_by_url(post_url: str, post_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Wrapper for fetch_post_metrics() with optional post_id parameter.
    Maintains API compatibility with old facebook_service.py
    """
    return await fetch_post_metrics(post_url)