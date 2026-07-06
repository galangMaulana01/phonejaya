#!/usr/bin/env python3
"""
Simple TikTok MS_TOKEN refresher using system chromium.
Jalanin manual atau cron: python3 refresh_tiktok_token_simple.py

Butuh: 
- chromium-browser terinstall (apt install chromium-browser)
- python-dotenv, playwright
"""

import asyncio
import os
import sys
import json
import logging
from pathlib import Path

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
    print("Run: pip install playwright httpx python-dotenv")
    sys.exit(1)

# Load .env.tiktok
ENV_FILE = ROOT_DIR / ".env.tiktok"
load_dotenv(ENV_FILE)

# Config from env
TIKTOK_USERNAME = os.getenv("TIKTOK_USERNAME")
TIKTOK_PASSWORD = os.getenv("TIKTOK_PASSWORD")
VERCEL_TOKEN = os.getenv("VERCEL_TOKEN")
VERCEL_PROJECT_ID = os.getenv("VERCEL_PROJECT_ID")
VERCEL_ENV_TARGET = os.getenv("VERCEL_ENV_TARGET", "production")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)


class SimpleTikTokRefresher:
    def __init__(self):
        self.ms_token = None
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        # Use system chromium
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            executable_path="/usr/bin/chromium-browser",  # System chromium
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
                "--no-zygote",
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
        
        await self.page.goto("https://www.tiktok.com/login", wait_until="networkidle", timeout=60000)
        
        log.info("⏳ Waiting for login form...")
        # Try multiple selectors for username input
        username_selectors = [
            'input[name="username"]',
            'input[placeholder*="username" i]',
            'input[placeholder*="phone" i]',
            'input[placeholder*="email" i]',
            '[data-e2e="login-username"]',
            'input[type="text"]',
        ]
        
        username_input = None
        for sel in username_selectors:
            try:
                username_input = await self.page.wait_for_selector(sel, timeout=5000)
                if username_input:
                    log.info(f"✅ Found username input: {sel}")
                    break
            except:
                continue
        
        if not username_input:
            raise Exception("❌ Username input not found")
        
        # Fill username
        await username_input.fill(TIKTOK_USERNAME)
        await self.page.wait_for_timeout(500)
        
        # Find password input
        password_selectors = [
            'input[name="password"]',
            'input[type="password"]',
            '[data-e2e="login-password"]',
        ]
        
        password_input = None
        for sel in password_selectors:
            try:
                password_input = await self.page.wait_for_selector(sel, timeout=3000)
                if password_input:
                    log.info(f"✅ Found password input: {sel}")
                    break
            except:
                continue
        
        if not password_input:
            raise Exception("❌ Password input not found")
        
        # Fill password
        await password_input.fill(TIKTOK_PASSWORD)
        await self.page.wait_for_timeout(500)
        
        # Click login button
        login_selectors = [
            'button[data-e2e="login-button"]',
            'button[type="submit"]',
            'button:has-text("Log in")',
            'button:has-text("Login")',
            'div[role="button"]:has-text("Log in")',
        ]
        
        for sel in login_selectors:
            try:
                btn = await self.page.wait_for_selector(sel, timeout=3000)
                if btn:
                    await btn.click()
                    log.info(f"✅ Clicked login button: {sel}")
                    break
            except:
                continue
        
        # Wait for redirect/login success
        log.info("⏳ Waiting for login to complete...")
        try:
            await self.page.wait_for_url("https://www.tiktok.com/**", timeout=30000)
        except:
            pass
        
        await self.page.wait_for_timeout(3000)
        
        # Extract msToken cookie
        log.info("🍪 Extracting msToken cookie...")
        cookies = await self.context.cookies()
        ms_token = None
        token = None
        for cookie in cookies:
            if cookie["name"] == "msToken":
                ms_token = cookie["value"]
                break
        
        if not ms_token:
            # Try localStorage/sessionStorage
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

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get current env to find existing TIKTOK_MS_TOKEN
            resp = await client.get(url, headers=headers, params={"limit": 100})
            if resp.status_code != 200:
                log.error(f"❌ Failed to fetch Vercel env: {resp.status_code} - {resp.text}")
                return False

            envs = resp.json().get("envs", [])
            existing = None
            for env in envs:
                if env.get("key") == "TIKTOK_MS_TOKEN":
                    existing = env
                    break

            if existing:
                # Update existing
                update_url = f"{url}/{existing['id']}"
                payload = {
                    "key": "TIKTOK_MS_TOKEN",
                    "value": ms_token,
                    "target": [VERCEL_ENV_TARGET],
                    "type": "encrypted",
                }
                resp = await client.patch(update_url, headers=headers, json=payload)
                action = "updated"
            else:
                # Create new
                payload = {
                    "key": "TIKTOK_MS_TOKEN",
                    "value": ms_token,
                    "target": [VERCEL_ENV_TARGET],
                    "type": "encrypted",
                }
                resp = await client.post(url, headers=headers, json=payload)
                action = "created"

            if resp.status_code in (200, 201):
                log.info(f"✅ Vercel env {action}: TIKTOK_MS_TOKEN")
                return True
            else:
                log.error(f"❌ Failed to {action} Vercel env: {resp.status_code} - {resp.text}")
                return False


async def main():
    # Validate config
    missing = []
    if not TIKTOK_USERNAME:
        missing.append("TIKTOK_USERNAME")
    if not TIKTOK_PASSWORD:
        missing.append("TIKTOK_PASSWORD")
    
    if missing:
        log.error(f"❌ Missing required env vars: {', '.join(missing)}")
        log.error(f"   Create {ENV_FILE} from .env.tiktok.example")
        sys.exit(1)

    log.info("🚀 Starting TikTok MS_TOKEN refresh...")

    async with SimpleTikTokRefresher() as refresher:
        try:
            ms_token = await refresher.login_and_get_token()
            success = await refresher.update_vercel_env(ms_token)
            
            if success:
                log.info("🎉 TikTok MS_TOKEN refresh completed successfully!")
            else:
                log.error("❌ Failed to update Vercel env")
                sys.exit(1)
                
        except Exception as e:
            log.error(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())