"""
Facebook Direct Scraper - core logic shared by both:
  - facebook_service.py       (manual "paste link" upload path)
  - facebook_feed_scraper.py  (cron auto-detect from a page's feed)

We still use the `facebook-scraper` pip package (kevinzg) as the actual
HTML-parsing engine - it targets mbasic.facebook.com (the lightweight,
non-JS version of Facebook), which is far more forgiving than IG/TikTok's
web apps: no JS challenge, no signed request params. Its parsing logic for
mbasic's HTML has been refined over years, so we reuse it rather than
reinventing that part from scratch.

What THIS file adds on top of the raw library (this is the part that was
missing before):
  1. Login/cookie support (`c_user` + `xs` cookies), via
     `facebook_scraper.set_cookies()`. Some pages/videos increasingly
     require a logged-in session even on mbasic - without this, those
     requests fail (previously nothing handled that case explicitly).
  2. Same non-ASCII cookie sanity check we added for Instagram's
     sessionid, so a mangled copy-paste fails with a clear message
     instead of a raw UnicodeEncodeError deep in the request layer.
  3. A single source of truth: both the manual-link and feed-based
     callers go through this one module instead of two independent
     copies of similar scraping code that can drift apart.

Env vars:
  FACEBOOK_C_USER, FACEBOOK_XS - cookies from a logged-in Facebook account
  (use a spare/throwaway account, not your main one). Both are required
  together - Facebook's login check needs both to consider a session valid.
  Get them from DevTools > Application > Cookies > facebook.com, same way
  as Instagram's sessionid.
"""
import os
import asyncio
from typing import Optional, List, Dict, Any


class FacebookScraperError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


_cookies_configured = False
_cookies_valid = False


def _validate_ascii(name: str, value: str) -> None:
    try:
        value.encode("ascii")
    except UnicodeEncodeError as e:
        raise FacebookScraperError(
            f"{name} contains a non-ASCII character ({e.reason} at position {e.start}) - "
            "this is almost always a copy-paste artifact. Re-copy the raw cookie value "
            "from DevTools > Cookies > facebook.com, making sure nothing extra "
            "(quotes, spaces, other text) gets included.",
            400,
        )


def _ensure_cookies_configured() -> bool:
    """
    Configure facebook-scraper's session cookies once per process, using
    FACEBOOK_C_USER / FACEBOOK_XS env vars. Returns True if a valid logged-in
    session is active, False if no cookies were configured at all.
    Raises FacebookScraperError if cookies were provided but are invalid/expired.
    """
    global _cookies_configured, _cookies_valid

    if _cookies_configured:
        return _cookies_valid

    c_user = (os.getenv("FACEBOOK_C_USER") or "").strip()
    xs = (os.getenv("FACEBOOK_XS") or "").strip()

    _cookies_configured = True

    if not c_user or not xs:
        _cookies_valid = False
        return False

    _validate_ascii("FACEBOOK_C_USER", c_user)
    _validate_ascii("FACEBOOK_XS", xs)

    import facebook_scraper
    from facebook_scraper import exceptions as fb_exceptions

    try:
        facebook_scraper.set_cookies({"c_user": c_user, "xs": xs})
    except fb_exceptions.InvalidCookies:
        raise FacebookScraperError(
            "FACEBOOK_C_USER / FACEBOOK_XS were provided but Facebook doesn't "
            "consider the session logged in - the cookies are likely expired "
            "or the account got logged out/flagged. Log in again with the "
            "throwaway account and refresh both cookie values.",
            401,
        )
    except Exception as e:
        raise FacebookScraperError(f"Failed to configure Facebook session: {e}", 500)

    _cookies_valid = True
    return True


def _post_to_dict(post: dict, fallback_post_id: str = "", fallback_page_name: str = "") -> Dict[str, Any]:
    likes = post.get("likes", 0)
    comments = post.get("comments", 0)
    shares = post.get("shares", 0)

    reactions = post.get("reactions", {})
    if isinstance(reactions, dict) and reactions:
        total_reactions = sum(reactions.values())
        if not likes and total_reactions > 0:
            likes = total_reactions

    views = post.get("views", 0)
    if not views and post.get("video"):
        views = post.get("video", {}).get("views", 0)

    time_val = post.get("time")

    return {
        "post_id": post.get("post_id", fallback_post_id),
        "page_name": post.get("username", fallback_page_name),
        "page_id": post.get("user_id", ""),
        "likes": int(likes) if likes else 0,
        "comments": int(comments) if comments else 0,
        "shares": int(shares) if shares else 0,
        "views": int(views) if views else 0,
        "reactions": reactions if isinstance(reactions, dict) else {},
        "text": (post.get("text") or "")[:500],
        "is_video": post.get("video") is not None,
        "video_id": post.get("video_id", ""),
        "post_url": post.get("post_url", ""),
        "thumbnail": post.get("image", post.get("video_thumbnail", "")),
        "time": time_val.isoformat() if hasattr(time_val, "isoformat") else str(time_val or ""),
    }


# ════════════════════════════════════════════════════════════════
# Public async API
# ════════════════════════════════════════════════════════════════

async def get_post_by_url(post_url: str, post_id: Optional[str] = None) -> Dict[str, Any]:
    """Fetch a single Facebook post/video's metrics by URL."""
    has_session = _ensure_cookies_configured()
    try:
        result = await asyncio.to_thread(_scrape_post_sync, post_url, post_id, has_session)
        return result
    except FacebookScraperError:
        raise
    except Exception as e:
        raise FacebookScraperError(f"Facebook scrape failed: {str(e)[:300]}", 502)


def _scrape_post_sync(post_url: str, post_id: Optional[str], has_session: bool) -> Dict[str, Any]:
    from facebook_scraper import get_posts
    from facebook_scraper import exceptions as fb_exceptions

    try:
        posts = list(get_posts(
            post_urls=[post_url],
            options={"allow_extra_requests": True},
            extra_info=True,
            timeout=30,
        ))
    except fb_exceptions.LoginRequired:
        raise FacebookScraperError(
            "This post requires a logged-in session to view - configure "
            "FACEBOOK_C_USER / FACEBOOK_XS." if not has_session else
            "This post requires a logged-in session, and the configured "
            "session was rejected - it may be expired or the account got flagged.",
            401,
        )
    except fb_exceptions.NotFound:
        raise FacebookScraperError("Post not found", 404)

    if not posts and post_id:
        try:
            posts = list(get_posts(
                post_urls=[post_id],
                options={"allow_extra_requests": True},
                extra_info=True,
                timeout=30,
            ))
        except (fb_exceptions.LoginRequired, fb_exceptions.NotFound):
            posts = []

    if not posts:
        raise FacebookScraperError(
            "Post not found or not accessible - it may be private, deleted, "
            "or require a logged-in session that isn't configured.",
            404,
        )

    post = posts[0]
    if not post.get("available", True):
        raise FacebookScraperError("Post is not available or has been deleted", 404)

    return _post_to_dict(post, fallback_post_id=post_id or "")


async def get_page_feed(page_name: str, count: int = 30) -> List[Dict[str, Any]]:
    """Fetch latest posts from a Facebook page's feed."""
    has_session = _ensure_cookies_configured()

    page_name = page_name.strip().lstrip("@")

    try:
        posts = await asyncio.to_thread(_scrape_feed_sync, page_name, count, has_session)
        return posts
    except FacebookScraperError:
        raise
    except Exception as e:
        raise FacebookScraperError(f"Facebook feed scrape failed: {str(e)[:300]}", 502)


def _scrape_feed_sync(page_name: str, count: int, has_session: bool) -> List[Dict[str, Any]]:
    from facebook_scraper import get_posts
    from facebook_scraper import exceptions as fb_exceptions

    try:
        posts_gen = get_posts(
            page_name,
            pages=max(1, count // 10 + 1),
            extra_info=True,
            options={"allow_extra_requests": True},
            timeout=30,
        )

        results = []
        for post in posts_gen:
            if len(results) >= count:
                break
            if not post.get("available", True):
                continue
            results.append(_post_to_dict(post, fallback_page_name=page_name))
        return results

    except fb_exceptions.LoginRequired:
        raise FacebookScraperError(
            f"@{page_name}'s feed requires a logged-in session to view - configure "
            "FACEBOOK_C_USER / FACEBOOK_XS." if not has_session else
            f"@{page_name}'s feed requires a logged-in session, and the configured "
            "session was rejected - it may be expired or the account got flagged.",
            401,
        )
    except fb_exceptions.NotFound:
        raise FacebookScraperError(f"Page @{page_name} not found", 404)
    except fb_exceptions.TemporarilyBanned:
        raise FacebookScraperError(
            "The configured Facebook account got temporarily blocked for "
            "automated behavior. Wait before retrying, and consider slowing "
            "down the sync frequency.",
            429,
        )
