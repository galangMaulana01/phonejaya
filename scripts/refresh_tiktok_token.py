#!/usr/bin/env python3
"""
Auto-refresh TikTok MS_TOKEN menggunakan Playwright.
Jalankan sekali seminggu via cron/GitHub Actions.

Flow:
1. Login ke TikTok pakai username/password (simpan di .env.tiktok)
2. Extract msToken cookie
3. Update Vercel Environment Variable via Vercel API
4. Trigger redeploy (optional)
"""

import asyncio
import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# Setup path
SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT_DIR))

try:
    from playwright.async_api import async_playwright
    import httpx
    from dotenv import load_dotenv
except ImportError as e:
    print(f"❌ Missing deps: {e}")
    print("Run: pip install playwright httpx python-dotenv && playwright install chromium")
    sys.exit(1)

# Load .env.tiktok
ENV_FILE = ROOT_DIR / ".env.tiktok"
load_dotenv(ENV_FILE)

# Config
TIKTOK_USERNAME = os.getenv("TIKTOK_USERNAME")
TIKTOK_PASSWORD = os.getenv("TIKOK_PASSWORD")  # typo di .env? handle both
if not TIKTOK_PASSWORD:
    TIKTOK_PASSWORD = os.getenv("TIKTOK_PASSWORD")

VERCEL_TOKEN = os.getenv("VERCEL_TOKEN")           # Vercel Personal Access Token
VERCEL_PROJECT_ID = os.getenv("VERCEL_PROJECT_ID") # Project ID di Vercel
VERCEL_ORG_ID = os.getenv("VERCEL_ORG_ID")         # Team/Org ID (optional)
VERCEL_ENV_TARGET = os.getenv("VERCEL_ENV_TARGET", "production")  # production/preview

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)


class TikTokTokenRefresher:
    def __init__(self):
        self.ms_token = None
        self.browser = None
        self.context = None
        self.page = None

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        # Launch headless chromium
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
            ]
        )
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            viewport={"width": 390, "height": 844},
            locale="en-US",
            timezone_id="Asia/Jakarta",
        )
        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def login_and_get_token(self) -> str:
        """Login ke TikTok dan extract msToken cookie."""
        log.info("🌐 Opening TikTok login page...")
        
        # Go to login page
        await self.page.goto("https://www.tiktok.com/login", wait_until="networkidle", timeout=60000)
        
        # Wait for login form - try multiple selectors
        log.info("⏳ Waiting for login form...")
        selectors = [
            'input[name="username"]',
            'input[placeholder*="username" i]',
            'input[placeholder*="phone" i]',
            'input[placeholder*="email" i]',
            '[data-e2e="login-username"]',
        ]
        
        username_input = None
        for sel in selectors:
            try:
                await self.page.wait_for_selector(sel, timeout=5000)
                username_input = await self.page.query_selector(sel)
                if username_input:
                    break
            except:
                continue
        
        if not username_input:
            # Try click "Use phone/email/username" button first
            try:
                await self.page.click('text="Use phone / email / username"', timeout=3000)
                await self.page.wait_for_selector('input[name="username"]', timeout=5000)
                username_input = await self.page.query_selector('input[name="username"]')
            except:
                pass

        if not username_input:
            raise Exception("❌ Could not find username input. TikTok UI may have changed.")

        # Fill credentials
        log.info("🔐 Filling credentials...")
        await username_input.fill(TIKTOK_USERNAME)
        await self.page.wait_for_timeout(500)

        # Password input
        password_selectors = [
            'input[name="password"]',
            'input[type="password"]',
            '[data-e2e="login-password"]',
        ]
        password_input = None
        for sel in password_selectors:
            try:
                password_input = await self.page.query_selector(sel)
                if password_input:
                    break
            except:
                continue

        if not password_input:
            raise Exception("❌ Could not find password input")

        await password_input.fill(TIKTOK_PASSWORD)
        await self.page.wait_for_timeout(500)

        # Submit login
        log.info("🚀 Submitting login...")
        submit_selectors = [
            'button[type="submit"]',
            '[data-e2e="login-button"]',
            'button:has-text("Log in")',
            'button:has-text("Login")',
        ]
        
        for sel in submit_selectors:
            try:
                btn = await self.page.query_selector(sel)
                if btn:
                    await btn.click()
                    break
            except:
                continue

        # Wait for login success - check for redirect or profile
        log.info("⏳ Waiting for login to complete...")
        try:
            # Wait for navigation or profile element
            await self.page.wait_for_url("**/tiktok.com/**", timeout=30000)
            await self.page.wait_for_timeout(3000)
        except:
            pass

        # Check if login failed (captcha, 2fa, etc)
        page_content = await self.page.content()
        if "captcha" in page_content.lower() or "verify" in page_content.lower():
            raise Exception("❌ Captcha/verification required. Manual intervention needed.")
        
        if "incorrect" in page_content.lower() or "wrong" in page_content.lower():
            raise Exception("❌ Invalid credentials")

        # Extract msToken cookie
        log.info("🍪 Extracting msToken cookie...")
        cookies = await self.context.cookies()
        ms_token = None
        for cookie in cookies:
            if cookie["name"] == "msToken":
                ms_token = cookie["value"]
                break

        if not ms_token:
            # Try localStorage / sessionStorage
            ms_token = await self.page.evaluate("""() => {
                return localStorage.getItem('msToken') || 
                       sessionStorage.getItem('msToken') || 
                       document.cookie.split('; ').find(c => c.startsWith('msToken='))?.split('=')[1];
            }""")

        if not ms_token:
            raise Exception("❌ msToken not found in cookies/storage")

        log.info(f"✅ Got msToken (length: {len(ms_token)})")
        return ms_token

    async def update_vercel_env(self, ms_token: str) -> bool:
        """Update Vercel environment variable via API."""
        if not VERCEL_TOKEN or not VERCEL_PROJECT_ID:
            log.warning("⚠️ Vercel credentials not configured. Skipping env update.")
            return False

        url = f"https://api.vercel.com/v10/projects/{VERCEL_PROJECT_ID}/env"
        headers = {
            "Authorization": f"Bearer {VERCEL_TOKEN}",
            "Content-Type": "application/json",
        }

        # Check existing env
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get current env
            resp = await client.get(url, headers=headers, params={"limit": 100})
            if resp.status_code != 200:
                log.error(f"❌ Failed to fetch Vercel env: {resp.status_code} - {resp.text}")
                return False

            envs = resp.json().get("envs", [])
            existing = next((e for e in envs if e["key"] == "TIKTOK_MS_TOKEN"), None)

            payload = {
                "key": "TIKTOK_MS_TOKEN",
                "value": ms_token,
                "target": [VERCEL_ENV_TARGET],
                "type": "encrypted",
            }

            if existing:
                # Update
                env_id = existing["id"]
                update_url = f"{url}/{env_id}"
                resp = await client.patch(update_url, headers=headers, json=payload)
                action = "updated"
            else:
                # Create
                resp = await client.post(url, headers=headers, json=payload)
                action = "created"

            if resp.status_code in (200, 201):
                log.info(f"✅ Vercel env TIKTOK_MS_TOKEN {action} successfully")
                return True
            else:
                log.error(f"❌ Failed to update Vercel env: {resp.status_code} - {resp.text}")
                return False

    async def trigger_redeploy(self) -> bool:
        """Trigger Vercel redeploy (optional)."""
        if not VERCEL_TOKEN or not VERCEL_PROJECT_ID:
            return False

        url = f"https://api.vercel.com/v13/deployments"
        headers = {
            "Authorization": f"Bearer {VERCEL_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "projectId": VERCEL_PROJECT_ID,
            "target": VERCEL_ENV_TARGET,
            "github": {"enabled": False},  # Force new deployment
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code in (200, 201):
                log.info("🚀 Redeploy triggered")
                return True
            else:
                log.warning(f"⚠️ Redeploy failed: {resp.status_code} - {resp.text}")
                return False


async def main():
    print("=" * 60)
    print("🔄 TIKTOK MS_TOKEN AUTO REFRESH")
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # Validate required env
    missing = []
    if not TIKTOK_USERNAME:
        missing.append("TIKTOK_USERNAME")
    if not TIKTOK_PASSWORD:
        missing.append("TIKTOK_PASSWORD")
    if not VERCEL_TOKEN:
        missing.append("VERCEL_TOKEN")
    if not VERCEL_PROJECT_ID:
        missing.append("VERCEL_PROJECT_ID")

    if missing:
        log.error(f"❌ Missing required env vars: {', '.join(missing)}")
        log.error("Set them in .env.tiktok or environment")
        sys.exit(1)

    try:
        async with TikTokTokenRefresher() as refresher:
            # 1. Login & get token
            ms_token = await refresher.login_and_get_token()

            # 2. Update Vercel
            success = await refresher.update_vercel_env(ms_token)

            if success:
                # 3. Optional: trigger redeploy
                await refresher.trigger_redeploy()
                log.info("🎉 Token refresh completed successfully!")
            else:
                log.error("❌ Failed to update Vercel env")
                sys.exit(1)

    except Exception as e:
        log.error(f"💥 Fatal error: {e}")
        sys.exit(1)

    print("=" * 60)
    print(f"✅ Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())