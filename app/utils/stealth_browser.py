"""Headless browser with stealth mode for Cloudflare/captcha bypass.

Features:
- Auto-stealth fingerprint patching (webdriver, plugins, chrome)
- Captcha auto-detection (Turnstile + reCAPTCHA via data-sitekey)
- Captcha solving via global CaptchaSolver (2Captcha/Capsolver)
- Per-domain cookie persistence (load before fetch, save after)
- Sync wrapper ``fetch_with_stealth_sync`` for non-async call-sites
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from app.utils.cookie_store import load_cookies, save_cookies
from app.utils.captcha_solver import get_captcha_solver

logger = logging.getLogger(__name__)

_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = { runtime: {} };
"""

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


class StealthBrowser:
    """Playwright-based stealth browser for bypassing Cloudflare."""

    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self._initialized = False

    async def init(self):
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )
        if self._initialized:
            return
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-zygote",
            ],
        )
        self._initialized = True

    async def close(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self._initialized = False

    # ------------------------------------------------------------------ #
    # Captcha detection (in-page JS)
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _detect_and_solve_captcha(page: Page, url: str) -> bool:
        """Detect Turnstile/reCAPTCHA on page. Solve if solver configured.

        Returns True if a captcha was detected (regardless of solve success).
        """
        solver = get_captcha_solver()

        # --- Cloudflare Turnstile ---
        turnstile_el = await page.query_selector(
            '[data-sitekey], .cf-turnstile, div[data-testid="turnstile"]'
        )
        if turnstile_el:
            sitekey = await turnstile_el.get_attribute("data-sitekey")
            if sitekey:
                logger.info("Turnstile detected (sitekey=%s) for %s", sitekey[:12], url)
                if solver:
                    token = solver.solve_turnstile(url, sitekey)
                    if token:
                        await page.evaluate(
                            """(args) => {
                                const [token] = args;
                                const el = document.querySelector('[data-sitekey]');
                                if (el) el.setAttribute('data-response', token);
                                // Also try cf-turnstile callback
                                if (window.turnstile) {
                                    window.turnstile.reset();
                                }
                            }""",
                            [token],
                        )
                        logger.info("Turnstile token injected")
                        await page.wait_for_timeout(3000)
                        return True
                    else:
                        logger.warning("Turnstile solve returned empty token")
                        return True
                else:
                    logger.warning("Turnstile detected but no captcha solver configured")
                    return True

        # --- reCAPTCHA v2 ---
        recaptcha_el = await page.query_selector('.g-recaptcha[data-sitekey]')
        if recaptcha_el:
            sitekey = await recaptcha_el.get_attribute("data-sitekey")
            if sitekey:
                logger.info("reCAPTCHA detected (sitekey=%s) for %s", sitekey[:12], url)
                if solver:
                    token = solver.solve_recaptcha(url, sitekey)
                    if token:
                        await page.evaluate(
                            """(args) => {
                                const [token] = args;
                                document.getElementById('g-recaptcha-response').innerHTML = token;
                            }""",
                            [token],
                        )
                        logger.info("reCAPTCHA token injected")
                        await page.wait_for_timeout(3000)
                        return True
                    else:
                        logger.warning("reCAPTCHA solve returned empty token")
                        return True
                else:
                    logger.warning("reCAPTCHA detected but no solver configured")
                    return True

        return False

    # ------------------------------------------------------------------ #
    # Main fetch
    # ------------------------------------------------------------------ #

    async def fetch_with_stealth(
        self,
        url: str,
        timeout: int = 60_000,
        *,
        persist_cookies: bool = True,
    ) -> str:
        """Fetch page with stealth, cookie reuse, and captcha auto-solve.

        Flow:
        1. Load saved cookies → inject into context
        2. Navigate to URL
        3. Wait for Cloudflare challenge auto-resolve
        4. Detect + solve captcha if present
        5. Save cookies for next session
        6. Return page HTML
        """
        if not self._initialized:
            await self.init()

        context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=_DEFAULT_UA,
            java_script_enabled=True,
        )
        await context.add_init_script(_STEALTH_INIT_SCRIPT)

        # 1. Load saved cookies
        saved = load_cookies(url)
        if saved:
            await context.add_cookies(saved)
            logger.debug("Loaded %d cookies for %s", len(saved), url)

        page = await context.new_page()
        await page.set_default_timeout(timeout)

        try:
            await page.goto(url, wait_until="domcontentloaded")

            # 2. Cloudflare interstitial auto-resolve
            await asyncio.sleep(3)
            title = await page.title()
            if "Checking your browser" in title or "Just a moment" in title:
                logger.info("Cloudflare challenge page for %s — waiting up to 30s", url)
                try:
                    await page.wait_for_function(
                        "document.title && !document.title.includes('Just a moment') "
                        "&& !document.title.includes('Checking your browser')",
                        timeout=30_000,
                    )
                except Exception:
                    logger.warning("Cloudflare challenge did not auto-resolve for %s", url)

            # 3. Captcha detection + solve
            captcha_found = await self._detect_and_solve_captcha(page, url)
            if captcha_found:
                # Re-check title after solve attempt
                await asyncio.sleep(2)

            # 4. Save cookies for next time
            if persist_cookies:
                cookies = await context.cookies()
                if cookies:
                    save_cookies(url, cookies)
                    logger.debug("Saved %d cookies for %s", len(cookies), url)

            content = await page.content()
            return content

        finally:
            await context.close()

    # ------------------------------------------------------------------ #
    # Legacy alias (kept for backward compat)
    # ------------------------------------------------------------------ #

    async def solve_captcha_and_fetch(
        self,
        url: str,
        captcha_solver=None,
        timeout: int = 60_000,
    ) -> str:
        """Deprecated — use ``fetch_with_stealth`` (auto-detects solver)."""
        return await self.fetch_with_stealth(url, timeout=timeout)


# --------------------------------------------------------------------------- #
# Global instance + async API
# --------------------------------------------------------------------------- #

_stealth_browser: Optional[StealthBrowser] = None


async def get_stealth_browser() -> StealthBrowser:
    global _stealth_browser
    if _stealth_browser is None:
        _stealth_browser = StealthBrowser()
        await _stealth_browser.init()
    return _stealth_browser


async def close_stealth_browser() -> None:
    global _stealth_browser
    if _stealth_browser is not None:
        await _stealth_browser.close()
        _stealth_browser = None


# --------------------------------------------------------------------------- #
# Sync wrapper — used by source_adapters.fetch_public_html
# --------------------------------------------------------------------------- #

def fetch_with_stealth_sync(url: str, timeout: int = 60_000) -> str:
    """Sync wrapper around ``StealthBrowser.fetch_with_stealth``.

    Creates a fresh browser instance per call (avoids event-loop conflicts
    when called from sync code). Returns page HTML on success, raises
    ``RuntimeError`` on failure.
    """
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError(
            "Playwright not installed. Run: pip install playwright && playwright install chromium"
        )

    async def _run() -> str:
        browser = StealthBrowser()
        try:
            await browser.init()
            return await browser.fetch_with_stealth(url, timeout=timeout)
        finally:
            await browser.close()

    from app.utils.asyncio_bridge import run_coro_sync

    return run_coro_sync(_run())
