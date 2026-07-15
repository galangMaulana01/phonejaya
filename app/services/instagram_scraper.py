"""
Instagram Direct Scraper - core logic shared by both:
  - instagram_service.py       (manual "paste link" upload path)
  - instagram_feed_scraper.py  (cron auto-detect from @username feed)

WHY THIS EXISTS (context for future maintainers / AI agents):
The previous instagram_service.py / instagram_feed_scraper.py both relied on
the `?__a=1` query param and `window._sharedData` - both were shut down by
Instagram around 2020-2021. Every request to those either 404s, redirects
to a login wall, or returns HTML with none of the expected script tags.
That's a dead endpoint, not a parsing bug - no amount of regex tweaking
fixes it.

Instagram does not offer a "guest token" the way TikTok's msToken works.
To read a user's post feed reliably you need a real logged-in account's
`sessionid` cookie (set INSTAGRAM_SESSIONID env var). Without it:
  - Feed access (get_user_feed) is not attempted - it will raise a clear
    error telling you to configure a session, rather than silently
    returning an empty/zeroed list.
  - Single-post metrics (get_post_by_url) will try a logged-out fallback
    (the public oEmbed-style embed page), which is best-effort and only
    covers public posts - Instagram may or may not include view counts
    there depending on the post.

Endpoints used (documented technique, not officially supported by Meta):
  - https://www.instagram.com/api/v1/users/web_profile_info/?username=X
    Requires header x-ig-app-id: 936619743392459 + sessionid cookie.
    Returns user info + up to ~12 latest posts with real stats. This is
    enough for "detect new posts" polling - it is NOT full pagination.
  - https://www.instagram.com/api/v1/media/{media_id}/info/
    Same headers/cookie. media_id is derived from the post shortcode.

Like the TikTok fix: failures raise InstagramScraperError with a specific
reason instead of returning fake zeroed data. If Instagram changes its
response shape again, this will surface as a clear error message we can
iterate on - not a silent "0 views" that looks like success.
"""
import os
import re
import json
import httpx
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

IG_APP_ID = "936619743392459"  # public web app id, used by instagram.com's own frontend
IG_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


class InstagramScraperError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class InstagramPost:
    shortcode: str
    url: str
    views: int
    likes: int
    comments: int
    caption: str
    taken_at: int
    is_video: bool
    author_username: str
    author_full_name: str
    description: str = ""
    thumbnail_url: str = ""


def extract_shortcode(url: str) -> Optional[str]:
    """Extract shortcode from an Instagram post/reel URL."""
    patterns = [
        r'instagram\.com/(?:p|reel|tv)/([\w-]+)',
        r'instagr\.am/(?:p|reel)/([\w-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def shortcode_to_media_id(shortcode: str) -> int:
    """
    Convert an Instagram shortcode to its numeric media id.
    Standard algorithm (same one instaloader and other IG tools use):
    treat the shortcode as a base-64 number using Instagram's custom alphabet.
    """
    media_id = 0
    for char in shortcode:
        media_id = media_id * 64 + IG_ALPHABET.index(char)
    return media_id


class InstagramDirectScraper:
    """
    Direct Instagram scraper using the web app's own internal API.
    Requires a real account's sessionid for anything beyond single-post
    best-effort fetching.
    """

    BASE_URL = "https://www.instagram.com"
    API_HOST = "https://i.instagram.com"  # private API host - required for
                                          # /api/v1/media/{id}/info/ to return
                                          # the full response (view counts,
                                          # correct user object) - www.instagram.com
                                          # serves an incomplete version of this
                                          # same endpoint.

    def __init__(self, session_id: Optional[str] = None, csrf_token: Optional[str] = None):
        self.session_id = (session_id or os.getenv("INSTAGRAM_SESSIONID") or "").strip()
        self.csrf_token = (csrf_token or os.getenv("INSTAGRAM_CSRFTOKEN") or "").strip()

        for name, value in (("INSTAGRAM_SESSIONID", self.session_id), ("INSTAGRAM_CSRFTOKEN", self.csrf_token)):
            if value:
                try:
                    value.encode("ascii")
                except UnicodeEncodeError as e:
                    raise InstagramScraperError(
                        f"{name} contains a non-ASCII character ({e.reason} at position {e.start}) - "
                        "this is almost always a copy-paste artifact. Re-copy the raw cookie "
                        "value from DevTools > Cookies > instagram.com.",
                        400,
                    )

        cookies = {"ig_did": "missing"}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "x-ig-app-id": IG_APP_ID,
            "x-requested-with": "XMLHttpRequest",
            "Referer": self.BASE_URL + "/",
        }
        if self.session_id:
            cookies["sessionid"] = self.session_id
        if self.csrf_token:
            # Instagram's 2026 endpoints reject requests that only carry
            # csrftoken as a cookie - it must also be sent as this header,
            # or several endpoints respond with 403/redirect loops even
            # with an otherwise-valid sessionid.
            cookies["csrftoken"] = self.csrf_token
            headers["x-csrftoken"] = self.csrf_token

        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers=headers,
            cookies=cookies,
            follow_redirects=True,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    def _has_session(self) -> bool:
        return bool(self.session_id)

    def _check_response_for_login_wall(self, resp: httpx.Response) -> None:
        if resp.status_code in (401, 403):
            raise InstagramScraperError(
                "Instagram rejected the request (401/403) - sessionid is likely "
                "missing, expired, or the account got flagged. Refresh INSTAGRAM_SESSIONID.",
                resp.status_code,
            )
        if "/accounts/login" in str(resp.url):
            raise InstagramScraperError(
                "Instagram redirected to the login page - sessionid is missing, "
                "invalid, or expired.",
                401,
            )

    # ------------------------------------------------------------------
    # Single post (works logged-out on a best-effort basis, more reliable
    # with a session)
    # ------------------------------------------------------------------

    async def get_post_by_url(self, post_url: str) -> InstagramPost:
        shortcode = extract_shortcode(post_url)
        if not shortcode:
            raise InstagramScraperError("Invalid Instagram post/reel URL", 400)

        if self._has_session():
            return await self._get_post_via_api(shortcode)
        return await self._get_post_via_embed(shortcode)

    async def _get_post_via_api(self, shortcode: str) -> InstagramPost:
        media_id = shortcode_to_media_id(shortcode)
        try:
            resp = await self.client.get(f"{self.API_HOST}/api/v1/media/{media_id}/info/")
        except httpx.TooManyRedirects:
            raise InstagramScraperError(
                "Instagram kept redirecting (likely bounced into a login/consent "
                "loop) instead of returning the post - this means INSTAGRAM_SESSIONID "
                "has expired or been invalidated. Log in again with the throwaway "
                "account and refresh the cookie value.",
                401,
            )

        self._check_response_for_login_wall(resp)
        if resp.status_code != 200:
            raise InstagramScraperError(
                f"media/info API returned HTTP {resp.status_code}: {resp.text[:200]}",
                resp.status_code,
            )

        try:
            data = resp.json()
        except json.JSONDecodeError:
            raise InstagramScraperError("media/info API did not return JSON", 502)

        items = data.get("items", [])
        if not items:
            raise InstagramScraperError(
                f"No media data returned for shortcode {shortcode} - post may be "
                "private, deleted, or the account was blocked.",
                404,
            )

        post = self._parse_item(items[0], shortcode)

        # As of 2026, Instagram removed view counts from this single-post
        # endpoint entirely (likes/comments still work fine here - only
        # views is affected). The workaround: views are still present on
        # the author's feed *listing* endpoint, so look the post up there
        # as a supplementary call when views came back empty.
        looks_like_real_username = (
            post.author_username
            and len(post.author_username) >= 2
            and not post.author_username.isdigit()
        )
        if post.views == 0 and looks_like_real_username:
            try:
                feed_posts = await self.get_user_feed(post.author_username, count=12)
                match = next((p for p in feed_posts if p.shortcode == shortcode), None)
                if match and match.views:
                    post.views = match.views
            except InstagramScraperError:
                pass  # best-effort - keep views=0 rather than fail the whole request

        return post

    async def _get_post_via_embed(self, shortcode: str) -> InstagramPost:
        """
        Logged-out fallback: parse the public embed page. This is
        best-effort - covers public posts only, and Instagram may omit
        exact view counts for some post types when logged out.
        """
        resp = await self.client.get(f"{self.BASE_URL}/p/{shortcode}/embed/captioned/")

        if resp.status_code == 404:
            raise InstagramScraperError(f"Post {shortcode} not found or private", 404)
        if resp.status_code != 200:
            raise InstagramScraperError(
                f"Embed page returned HTTP {resp.status_code} - no INSTAGRAM_SESSIONID "
                "configured, so only the logged-out fallback was tried.",
                resp.status_code,
            )

        html = resp.text

        # Instagram embeds a small contextJSON / graphql blob in the embed page
        match = re.search(r'contextJSON"\s*:\s*"(.*?)"\s*[,}]', html)
        if match:
            try:
                raw = match.group(1).encode().decode("unicode_escape")
                data = json.loads(raw)
                media = data.get("shortcode_media") or data.get("media")
                if media:
                    return self._parse_graphql_item(media, shortcode)
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        raise InstagramScraperError(
            f"Could not extract post data for {shortcode} from the logged-out "
            "embed page. Configure INSTAGRAM_SESSIONID for reliable access - "
            "logged-out scraping of Instagram is inherently unreliable.",
            502,
        )

    # ------------------------------------------------------------------
    # Feed (requires a real session - no guest path)
    # ------------------------------------------------------------------

    async def get_user_feed(self, username: str, count: int = 12) -> List[InstagramPost]:
        if not self._has_session():
            raise InstagramScraperError(
                "INSTAGRAM_SESSIONID is not configured. Instagram does not allow "
                "guest access to a user's post feed - a real logged-in account's "
                "session is required for auto-detect to work.",
                401,
            )

        username = username.lstrip("@").strip()
        try:
            resp = await self.client.get(
                f"{self.BASE_URL}/api/v1/users/web_profile_info/",
                params={"username": username},
            )
        except httpx.TooManyRedirects:
            raise InstagramScraperError(
                "Instagram kept redirecting (likely bounced into a login/consent "
                "loop) instead of returning the profile - this means INSTAGRAM_SESSIONID "
                "has expired or been invalidated. Log in again with the throwaway "
                "account and refresh the cookie value.",
                401,
            )

        self._check_response_for_login_wall(resp)
        if resp.status_code == 404:
            raise InstagramScraperError(f"User @{username} not found", 404)
        if resp.status_code != 200:
            raise InstagramScraperError(
                f"web_profile_info API returned HTTP {resp.status_code}: {resp.text[:200]}",
                resp.status_code,
            )

        try:
            data = resp.json()
        except json.JSONDecodeError:
            raise InstagramScraperError("web_profile_info API did not return JSON", 502)

        user = (data.get("data") or {}).get("user")
        if not user:
            raise InstagramScraperError(
                f"web_profile_info response missing 'user' for @{username} - "
                "Instagram may have changed its response shape.",
                502,
            )

        if user.get("is_private"):
            raise InstagramScraperError(
                f"@{username} is a private account - the logged-in session must "
                "follow this account to read its posts.",
                403,
            )

        edges = (user.get("edge_owner_to_timeline_media") or {}).get("edges", [])
        posts = []
        for edge in edges[:count]:
            node = edge.get("node", {})
            post = self._parse_graphql_item(node, node.get("shortcode", ""), username_hint=username)
            if post:
                posts.append(post)

        return posts

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_item(self, item: dict, shortcode: str) -> InstagramPost:
        """Parse the mobile-style API item format (api/v1/media/{id}/info/)."""
        user = item.get("user", {}) or {}
        # Get thumbnail from image_versions2
        thumbnail_url = ""
        image_versions = item.get("image_versions2", {}) or {}
        candidates = image_versions.get("candidates", [])
        if candidates:
            thumbnail_url = candidates[0].get("url", "")
        # Fallback to cover_photo_url or media_url
        if not thumbnail_url:
            thumbnail_url = item.get("cover_photo_url", "") or item.get("media_url", "")

        return InstagramPost(
            shortcode=shortcode,
            url=f"{self.BASE_URL}/p/{shortcode}/",
            views=int(item.get("play_count", item.get("view_count", 0)) or 0),
            likes=int(item.get("like_count", 0) or 0),
            comments=int(item.get("comment_count", 0) or 0),
            caption=(item.get("caption") or {}).get("text", "") if item.get("caption") else "",
            taken_at=int(item.get("taken_at", 0) or 0),
            is_video=item.get("media_type") == 2,
            author_username=user.get("username", ""),
            author_full_name=user.get("full_name", ""),
            description=(item.get("caption") or {}).get("text", "") if item.get("caption") else "",
            thumbnail_url=thumbnail_url,
        )

    def _parse_graphql_item(
        self, node: dict, shortcode: str, username_hint: str = ""
    ) -> Optional[InstagramPost]:
        """Parse the GraphQL-style node format (web_profile_info / embed page)."""
        if not shortcode:
            return None
        try:
            owner = node.get("owner", {}) or {}
            caption_edges = (node.get("edge_media_to_caption") or {}).get("edges", [])
            caption = caption_edges[0]["node"]["text"] if caption_edges else ""
            
            # Get thumbnail from display_resources
            thumbnail_url = ""
            display_resources = node.get("display_resources", [])
            if display_resources:
                thumbnail_url = display_resources[-1].get("src", "")
            # Fallback to thumbnail_src
            if not thumbnail_url:
                thumbnail_url = node.get("thumbnail_src", "")

            return InstagramPost(
                shortcode=shortcode,
                url=f"{self.BASE_URL}/p/{shortcode}/",
                views=int(node.get("video_view_count", 0) or 0),
                likes=int(
                    (node.get("edge_media_preview_like") or node.get("edge_liked_by") or {}).get("count", 0)
                    or 0
                ),
                comments=int((node.get("edge_media_to_comment") or {}).get("count", 0) or 0),
                caption=caption,
                taken_at=int(node.get("taken_at_timestamp", 0) or 0),
                is_video=bool(node.get("is_video", False)),
                author_username=owner.get("username", username_hint),
                author_full_name=owner.get("full_name", ""),
                description=caption,
                thumbnail_url=thumbnail_url,
            )
        except Exception:
            return None


# ════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ════════════════════════════════════════════════════════════════

async def fetch_post_metrics(post_url: str) -> Dict[str, Any]:
    """Fetch metrics for a single Instagram post/reel by URL."""
    async with InstagramDirectScraper() as scraper:
        post = await scraper.get_post_by_url(post_url)
        return {
            "shortcode": post.shortcode,
            "views": post.views,
            "likes": post.likes,
            "comments": post.comments,
            "is_video": post.is_video,
            "caption": post.caption,
            "description": post.description,
            "thumbnail_url": post.thumbnail_url,
            "taken_at": post.taken_at,
            "owner": {
                "username": post.author_username,
                "full_name": post.author_full_name,
            },
            "url": post.url,
        }


async def fetch_user_feed(username: str, count: int = 12) -> List[Dict[str, Any]]:
    """Fetch latest posts (up to ~12) for @username with real engagement metrics."""
    async with InstagramDirectScraper() as scraper:
        posts = await scraper.get_user_feed(username, count)
        return [p.__dict__ for p in posts]
