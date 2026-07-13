"""
TikTok Direct Web Scraper - NO RapidAPI, NO cost.
Uses TikTok's public web endpoints (hidden JSON + item_list API).
Works on Vercel serverless (no browser/Playwright needed).

ROOT-CAUSE FIX (2026-07-08):
Previous version always returned views/likes/comments/shares = 0 because:
  1. `/api/post/item_list/` was called with `secUid=""` and a `username` param.
     That endpoint does NOT accept `username` — it only works with a real
     `secUid`, which must be resolved from the profile page first. With an
     empty secUid, TikTok returns HTTP 200 with `itemList: []` every time
     (not an error), so the code silently fell through to a broken fallback.
  2. The single-video fallback looked for a script tag with id
     `__UNIVERSAL_DATA__`, which does not exist. The real tag is
     `__UNIVERSAL_DATA_FOR_REHYDRATION__` (already used correctly elsewhere
     in this file) - so that parsing path was dead code that never matched.
  3. When every parsing method failed, the code returned a "successful"
     TikTokVideo object with all stats hardcoded to 0 instead of raising an
     error - masking real failures (blocked request, changed page structure,
     private account, etc.) as if scraping had worked.

This version:
  - Resolves secUid from the profile page before calling item_list.
  - Fixes the script-tag id bug.
  - Parses video-detail pages via the confirmed-correct path:
    __DEFAULT_SCOPE__ -> webapp.video-detail -> itemInfo -> itemStruct
  - Raises TikTokScraperError with a specific reason instead of returning
    a fake zeroed result, so failures are visible in logs and can actually
    be diagnosed/fixed instead of hidden.
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
@dataclass
class TikTokVideo:
    video_id: str
    url: str
    views: int
    likes: int
    comments: int
    caption: str
    create_time: int
    author_username: str
    author_nickname: str
    is_video: bool = True


# Markers that indicate TikTok served a bot-check / interstitial page instead
# of the real page. If we see these, we raise a clear error instead of
# silently treating the (missing) data as "0".
_CHALLENGE_MARKERS = (
    "validate.tiktok.com",
    "/captcha/",
    "verify to continue",
    "Please wait...",
    "secsdk-captcha",
)


class TikTokDirectScraper:
    """
    Direct TikTok scraper using public web endpoints.
    No browser automation - pure HTTP with msToken cookie + resolved secUid.
    """

    BASE_URL = "https://www.tiktok.com"
    ITEM_LIST_ENDPOINT = "/api/post/item_list/"

    def __init__(self, ms_token: Optional[str] = None):
        self.ms_token = ms_token or os.getenv("TIKTOK_MS_TOKEN")

        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "sec-ch-ua": '"Chromium";v="126", "Not.A/Brand";v="24"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "navigate",
                "sec-fetch-dest": "document",
            },
            cookies={"msToken": self.ms_token} if self.ms_token else {},
            follow_redirects=True,
        )
        # secUid resolution is expensive (extra HTTP round trip), cache per instance
        self._sec_uid_cache: Dict[str, str] = {}
        self._bootstrapped = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    async def _bootstrap_session(self) -> None:
        """
        Hit the TikTok homepage once so the client picks up baseline session
        cookies (ttwid, tt_csrf_token, etc.) via Set-Cookie. httpx keeps
        cookies on the client automatically across requests, so every
        subsequent call in this scraper instance benefits from this.
        """
        if self._bootstrapped:
            return
        try:
            await self.client.get(self.BASE_URL)
        except Exception:
            # Non-fatal - we still try the real request below
            pass
        self._bootstrapped = True

    def _extract_rehydration_json(self, html: str) -> Optional[dict]:
        """Extract and parse the __UNIVERSAL_DATA_FOR_REHYDRATION__ script tag."""
        match = re.search(
            r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not match:
            return None
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            return None

    def _is_challenge_page(self, html: str) -> bool:
        lowered = html[:5000].lower()
        return any(marker.lower() in lowered for marker in _CHALLENGE_MARKERS)

    # ------------------------------------------------------------------
    # secUid resolution (the actual fix for "always 0")
    # ------------------------------------------------------------------

    async def _resolve_sec_uid(self, username: str) -> str:
        """
        Resolve a username's secUid from their profile page. This is
        required by /api/post/item_list/ - the endpoint does not accept
        a username directly.
        """
        username = username.lstrip("@").strip()
        if username in self._sec_uid_cache:
            return self._sec_uid_cache[username]

        await self._bootstrap_session()

        profile_url = f"{self.BASE_URL}/@{username}"
        resp = await self.client.get(profile_url, headers={"Referer": self.BASE_URL})

        if resp.status_code == 404:
            raise TikTokScraperError(f"User @{username} not found", 404)
        if resp.status_code != 200:
            raise TikTokScraperError(
                f"Failed to load profile @{username}: HTTP {resp.status_code}", resp.status_code
            )

        html = resp.text
        if self._is_challenge_page(html):
            raise TikTokScraperError(
                f"TikTok served a verification/challenge page for @{username} "
                "instead of the profile - request was flagged as bot traffic.",
                403,
            )

        data = self._extract_rehydration_json(html)
        if not data:
            raise TikTokScraperError(
                f"Could not find __UNIVERSAL_DATA_FOR_REHYDRATION__ on @{username}'s "
                "profile page - TikTok page structure may have changed.",
                502,
            )

        try:
            user = (
                data["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]["user"]
            )
            sec_uid = user.get("secUid")
        except (KeyError, TypeError):
            sec_uid = None

        if not sec_uid:
            raise TikTokScraperError(
                f"secUid not found for @{username} - account may be private, "
                "banned, or nonexistent.",
                404,
            )

        self._sec_uid_cache[username] = sec_uid
        return sec_uid

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_video_by_url(self, video_url: str) -> Optional[TikTokVideo]:
        """
        Fetch single video metrics directly from its own page.
        Supports: vt.tiktok.com, vm.tiktok.com, tiktok.com/@user/video/ID, tiktok.com/t/...
        The video-detail page embeds full stats in its own rehydration JSON,
        so we don't need to go through the user's feed at all.
        """
        await self._bootstrap_session()

        resp = await self.client.get(video_url, headers={"Referer": self.BASE_URL})

        if resp.status_code == 404:
            raise TikTokScraperError("Video not found or private", 404)
        if resp.status_code != 200:
            raise TikTokScraperError(f"Video page returned HTTP {resp.status_code}", resp.status_code)

        html = resp.text
        final_url = str(resp.url)

        if self._is_challenge_page(html):
            raise TikTokScraperError(
                "TikTok served a verification/challenge page instead of the video "
                "- request was flagged as bot traffic.",
                403,
            )

        video_id_match = re.search(r"/video/(\d{15,20})", final_url)
        video_id = video_id_match.group(1) if video_id_match else self._extract_video_id(video_url)

        data = self._extract_rehydration_json(html)
        if not data:
            raise TikTokScraperError(
                "Could not find __UNIVERSAL_DATA_FOR_REHYDRATION__ on the video page "
                "- TikTok page structure may have changed.",
                502,
            )

        try:
            item = data["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]
        except (KeyError, TypeError):
            item = None

        if not item:
            raise TikTokScraperError(
                f"Video data missing from page JSON for video {video_id} "
                "- video may have been removed or made private.",
                404,
            )

        video = self._parse_video_item(item, item.get("author", {}).get("uniqueId", ""))
        if not video:
            raise TikTokScraperError(f"Failed to parse video data for {video_id}", 502)
        video.url = final_url
        return video

    async def get_user_feed(self, username: str, count: int = 30) -> List[TikTokVideo]:
        """
        Fetch latest videos from @username feed via the item_list API,
        using a properly resolved secUid (this is the piece that was
        missing before and caused every request to come back empty).
        """
        username = username.lstrip("@").strip()
        sec_uid = await self._resolve_sec_uid(username)

        videos: List[TikTokVideo] = []
        cursor = 0
        page_size = min(count, 35)  # TikTok caps item_list at ~35 per page

        while len(videos) < count:
            params = {
                "aid": "1988",
                "secUid": sec_uid,
                "count": page_size,
                "cursor": cursor,
            }
            resp = await self.client.get(
                f"{self.BASE_URL}{self.ITEM_LIST_ENDPOINT}",
                params=params,
                headers={"Referer": f"{self.BASE_URL}/@{username}"},
            )

            if resp.status_code == 403:
                raise TikTokScraperError(
                    "Access forbidden fetching item_list - msToken may be expired/invalid "
                    "or request was flagged as bot traffic.",
                    403,
                )
            if resp.status_code != 200:
                raise TikTokScraperError(
                    f"item_list API returned HTTP {resp.status_code}: {resp.text[:200]}",
                    resp.status_code,
                )

            try:
                data = resp.json()
            except json.JSONDecodeError:
                raise TikTokScraperError(
                    "item_list API did not return JSON - likely served a challenge page.",
                    502,
                )

            status_code = data.get("statusCode", data.get("status_code", 0))
            if status_code not in (0, None):
                raise TikTokScraperError(
                    f"TikTok API error: {data.get('statusMsg', data.get('message', 'Unknown error'))}",
                    502,
                )

            items = data.get("itemList", []) or []
            for item in items:
                video = self._parse_video_item(item, username)
                if video:
                    videos.append(video)

            has_more = data.get("hasMore", False)
            cursor = data.get("cursor", cursor)
            if not has_more or not items:
                break

        return videos[:count]

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_video_item(self, item: dict, username: str) -> Optional[TikTokVideo]:
        """Parse a single video item from TikTok's item_list / video-detail JSON."""
        try:
            video_id = item.get("id") or item.get("aweme_id") or item.get("video_id")
            if not video_id:
                return None

            stats = item.get("stats", {}) or item.get("statistics", {}) or {}
            author = item.get("author", {}) or item.get("authorInfo", {}) or {}

            caption = item.get("desc", "") or item.get("description", "")
            create_time = item.get("createTime", item.get("create_time", 0))

            author_username = author.get("uniqueId") or author.get("username") or username

            return TikTokVideo(
                video_id=str(video_id),
                url=f"{self.BASE_URL}/@{author_username}/video/{video_id}",
                views=int(stats.get("playCount", 0) or 0),
                likes=int(stats.get("diggCount", 0) or 0),
                comments=int(stats.get("commentCount", 0) or 0),
                caption=caption,
                create_time=int(create_time) if create_time else 0,
                author_username=author_username,
                author_nickname=author.get("nickname") or author.get("nickName") or "",
                is_video=item.get("isVideo", True),
            )
        except Exception:
            return None

    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from a TikTok URL when redirect resolution isn't available."""
        patterns = [
            r'tiktok\.com/@[^/]+/video/(\d{15,20})',
            r'vt\.tiktok\.com/([A-Za-z0-9]+)',
            r'vm\.tiktok\.com/([A-Za-z0-9]+)',
            r'm\.tiktok\.com/v/(\d{15,20})',
            r'tiktok\.com/t/([A-Za-z0-9]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        match = re.search(r'(\d{15,20})', url)
        return match.group(1) if match else None


# ════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ════════════════════════════════════════════════════════════════

async def fetch_video_metrics(video_url: str) -> Dict[str, Any]:
    """
    Fetch metrics for a single TikTok video.

    Raises:
        TikTokScraperError: with a specific, actionable reason if scraping fails.
        (Callers should catch this and log the message - do NOT swallow it
        into a fake zeroed result.)
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
            "author_username": video.author_username,
            "author_nickname": video.author_nickname,
            "url": video.url,
        }


async def fetch_user_feed(username: str, count: int = 30) -> List[Dict[str, Any]]:
    """
    Fetch user feed (latest videos) with real engagement metrics.
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
                "caption": v.caption,
                "author_username": v.author_username,
                "author_nickname": v.author_nickname,
            }
            for v in videos
        ]
