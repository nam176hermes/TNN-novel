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
import os
from typing import Optional

try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

from app.utils.cookie_store import save_cookies
from app.utils.captcha_solver import get_captcha_solver
from app.security.url_policy import redacted_url, validate_fetch_url

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
        # Use headed mode when DISPLAY is available — Cloudflare detects headless
        headed = bool(os.getenv("DISPLAY"))
        self.browser = await self.playwright.chromium.launch(
            headless=not headed,
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
        safe_url = redacted_url(url)

        # --- Cloudflare Turnstile ---
        turnstile_el = await page.query_selector(
            '[data-sitekey], .cf-turnstile, div[data-testid="turnstile"]'
        )
        if turnstile_el:
            sitekey = await turnstile_el.get_attribute("data-sitekey")
            if sitekey:
                logger.info("Turnstile detected (sitekey=%s) for %s", sitekey[:12], safe_url)
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
                logger.info("reCAPTCHA detected (sitekey=%s) for %s", sitekey[:12], safe_url)
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
        """Fetch page with persistent browser profile for better Cloudflare bypass.

        Uses a persistent user-data-dir so Cloudflare sees a 'returning visitor'
        with existing cookies/fingerprint, dramatically improving pass rate.
        """
        import tempfile

        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright not installed")
        safe_url_result = validate_fetch_url(url)
        url = safe_url_result.canonical_url
        safe_url = redacted_url(url)

        # Auto-detect display — WSLg provides :0, Xvfb typically :99
        display = os.getenv("DISPLAY", "")
        if not display:
            import subprocess
            for test_display in (":0", ":99"):
                try:
                    result = subprocess.run(
                        ["xdpyinfo", "-display", test_display],
                        capture_output=True, timeout=3,
                    )
                    if result.returncode == 0:
                        display = test_display
                        os.environ["DISPLAY"] = test_display
                        break
                except FileNotFoundError:
                    # xdpyinfo not installed — try connecting directly
                    display = test_display
                    os.environ["DISPLAY"] = test_display
                    break
                except Exception:
                    continue
        headed = bool(display)
        profile_dir = os.path.join(
            tempfile.gettempdir(), "pw_stealth_profile"
        )

        playwright = await async_playwright().start()
        context = await playwright.chromium.launch_persistent_context(
            profile_dir,
            headless=not headed,
            viewport={"width": 1920, "height": 1080},
            user_agent=_DEFAULT_UA,
            java_script_enabled=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-zygote",
            ],
        )
        await context.add_init_script(_STEALTH_INIT_SCRIPT)

        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(timeout)

        try:
            await page.goto(url, wait_until="domcontentloaded")

            # 2. Cloudflare interstitial — wait longer, then try reload
            await asyncio.sleep(5)
            title = await page.title()
            if "Checking your browser" in title or "Just a moment" in title:
                logger.info("Cloudflare challenge page for %s — waiting up to 45s", safe_url)
                try:
                    await page.wait_for_function(
                        "document.title && !document.title.includes('Just a moment') "
                        "&& !document.title.includes('Checking your browser')",
                        timeout=45_000,
                    )
                except Exception:
                    logger.warning("Cloudflare challenge did not auto-resolve for %s — trying reload", safe_url)
                    # Try reloading the page — often resolves after first visit sets cookies
                    try:
                        await page.reload(wait_until="domcontentloaded", timeout=30_000)
                        await asyncio.sleep(5)
                        title2 = await page.title()
                        if "Just a moment" in title2 or "Checking" in title2:
                            logger.warning("Still blocked after reload for %s", safe_url)
                        else:
                            logger.info("Cloudflare resolved after reload for %s", safe_url)
                    except Exception as reload_err:
                        logger.warning("Reload failed for %s: %s", safe_url, reload_err)

            # 3. Captcha detection + solve
            captcha_found = await self._detect_and_solve_captcha(page, url)
            if captcha_found:
                # Re-check title after solve attempt
                await asyncio.sleep(3)

            # 4. Save cookies for next time
            if persist_cookies:
                cookies = await context.cookies()
                if cookies:
                    save_cookies(url, cookies)
                    logger.debug("Saved %d cookies for %s", len(cookies), safe_url)

            content = await page.content()
            return content

        finally:
            await context.close()
            await playwright.stop()

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
