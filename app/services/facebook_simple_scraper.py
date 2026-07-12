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
import re
import logging
import httpx
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
        logger.info(f"Attempting to scrape with facebook-scraper library (timeout=30s)")
        posts = list(get_posts(
            post_urls=[post_url],  # type: ignore
            options={
                "allow_extra_requests": True,
                "remove_expired": False,
                "cookies": {"c_user": os.getenv("FACEBOOK_C_USER", ""), "xs": os.getenv("FACEBOOK_XS", "")} if os.getenv("FACEBOOK_C_USER") else None,
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
        logger.debug(f"Raw post data: {list(post.keys())}")
        
        # Check if post is available
        if not post.get("available", True):
            raise FacebookScraperError(
                f"Post is not available (may have been deleted or made private)",
                404
            )
        
        result = _post_to_dict(post)
        
        # CRITICAL VALIDATION: Check if scraping actually succeeded
        # facebook-scraper sometimes returns empty posts without throwing errors
        likes = result.get("likes", 0)
        comments = result.get("comments", 0)
        shares = result.get("shares", 0)
        views = result.get("views", 0)
        
        # If ALL metrics are 0, likely parsing failed (Facebook changed HTML structure)
        if likes == 0 and comments == 0 and shares == 0 and views == 0:
            logger.warning(f"Post found but all metrics are 0 - possible parsing failure")
            logger.warning(f"Post keys: {list(post.keys())}")
            logger.warning(f"Post text preview: {result.get('text', '')[:100]}")
            
            # Check if we at least got post_id (means we found something)
            if not result.get("post_id"):
                # TRY FALLBACK: Direct HTTP scrape without facebook-scraper library
                logger.info("Attempting fallback: direct HTTP scraping...")
                fallback_result = await _scrape_with_regex(post_url)
                if fallback_result:
                    logger.info(f"Fallback success: {fallback_result}")
                    return fallback_result
                
                raise FacebookScraperError(
                    f"Found post but couldn't extract metrics - Facebook may have changed page structure. "
                    f"Raw post keys: {list(post.keys())[:10]}. "
                    f"Try refreshing Facebook cookies (FACEBOOK_C_USER, FACEBOOK_XS).",
                    500
                )
        
        logger.info(
            f"Facebook scraping success: {likes} likes, {comments} comments, "
            f"{shares} shares, {views} views"
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


async def _scrape_with_regex(post_url: str) -> Optional[Dict[str, Any]]:
    """
    Fallback: Direct HTTP scraping with regex parsing.
    Used when facebook-scraper library fails to parse HTML structure.
    
    This is simpler but more fragile - only used as last resort.
    """
    try:
        c_user = os.getenv("FACEBOOK_C_USER", "")
        xs = os.getenv("FACEBOOK_XS", "")
        
        cookies = {}
        if c_user and xs:
            cookies = {"c_user": c_user, "xs": xs}
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        
        async with httpx.AsyncClient(cookies=cookies, headers=headers, timeout=30) as client:
            resp = await client.get(post_url, follow_redirects=True)
            if resp.status_code != 200:
                logger.warning(f"Direct HTTP scrape failed: HTTP {resp.status_code}")
                return None
            
            html = resp.text
            
            # Try to extract metrics with regex patterns
            # Facebook uses various formats, try multiple patterns
            
            likes_match = re.search(r'"likes":\s*"?(\d+)"?', html) or \
                         re.search(r'(\d{1,3}(?:,\d{3})*)\s*[Ll]ikes?', html) or \
                         re.search(r'data-testid="UFI2LikesCount"\S*>(\d+)', html)
            likes = int(likes_match.group(1).replace(',', '')) if likes_match else 0
            
            comments_match = re.search(r'"comments":\s*"?(\d+)"?', html) or \
                            re.search(r'(\d{1,3}(?:,\d{3})*)\s*[Cc]omments?', html) or \
                            re.search(r'data-testid="UFI2CommentsCount"\S*>(\d+)', html)
            comments = int(comments_match.group(1).replace(',', '')) if comments_match else 0
            
            shares_match = re.search(r'"shares":\s*"?(\d+)"?', html) or \
                          re.search(r'(\d{1,3}(?:,\d{3})*)\s*[Ss]hares?', html) or \
                          re.search(r'data-testid="shareCount"\S*>(\d+)', html)
            shares = int(shares_match.group(1).replace(',', '')) if shares_match else 0
            
            views_match = re.search(r'"views":\s*"?(\d+)"?', html) or \
                         re.search(r'(\d{1,3}(?:,\d{3})*)\s*[Vv]iews?', html) or \
                         re.search(r'data-testid="videoViewCount"\S*>([^<]+)', html)
            views = 0
            if views_match:
                views_str = views_match.group(1).replace(',', '')
                # Handle "1.5K" format
                if 'K' in views_str.upper():
                    views = int(float(views_str.replace('K', '').replace(',', '')) * 1000)
                elif 'M' in views_str.upper():
                    views = int(float(views_str.replace('M', '').replace(',', '')) * 1000000)
                else:
                    views = int(views_str)
            
            # If we got at least ONE non-zero metric, return success
            if likes > 0 or comments > 0 or shares > 0 or views > 0:
                logger.info(f"Regex scraping success: {likes} likes, {comments} comments, {shares} shares, {views} views")
                return {
                    "post_id": re.search(r'story_fbid=(\d+)', post_url) or re.search(r'/(\d{15,})', post_url),
                    "likes": likes,
                    "comments": comments,
                    "shares": shares,
                    "views": views,
                    "text": "",
                }
            
            logger.warning(f"Regex scraping found no metrics in HTML")
            return None
            
    except Exception as e:
        logger.exception(f"Regex scraping failed: {e}")
        return None


# Convenience function for influencer service
async def get_post_by_url(post_url: str, post_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Wrapper for fetch_post_metrics() with optional post_id parameter.
    Maintains API compatibility with old facebook_service.py
    """
    result = await fetch_post_metrics(post_url)
    if not result.get("post_id") and post_id:
        result["post_id"] = post_id
    return result