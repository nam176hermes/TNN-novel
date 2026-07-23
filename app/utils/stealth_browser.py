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
import atexit
from collections.abc import Awaitable, Callable
import logging
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Any, Optional
from urllib.parse import urlsplit

try:
    # Try patchright first (undetected Playwright fork — fixes Runtime.enable leak)
    from patchright.async_api import async_playwright, BrowserContext, Page
    PLAYWRIGHT_AVAILABLE = True
    PATCHRIGHT_AVAILABLE = True
except ImportError:
    try:
        from playwright.async_api import async_playwright, BrowserContext, Page
        PLAYWRIGHT_AVAILABLE = True
        PATCHRIGHT_AVAILABLE = False
    except ImportError:
        PLAYWRIGHT_AVAILABLE = False
        PATCHRIGHT_AVAILABLE = False

from app.utils.cookie_store import load_cookies, save_cookies
from app.utils.captcha_solver import get_captcha_solver
from app.utils.proxy_pool import proxy_pool
from app.observability import Observability, default_observability
from app.security.url_policy import (
    UrlPolicyViolation,
    UrlResolver,
    default_resolver,
    redacted_url,
    validate_fetch_url,
)

logger = logging.getLogger(__name__)

from app.utils.stealth_scripts import (
    STEALTH_LAUNCH_ARGS,
    HARMFUL_ARGS,
    build_stealth_script,
    filter_harmful_args,
    pick_user_agent,
    pick_viewport,
)


async def _start_playwright() -> Any:
    """Start playwright/patchright with patchright preferred if available."""
    if PATCHRIGHT_AVAILABLE:
        logger.info("Using patchright (undetected Playwright)")
    else:
        logger.info("Using vanilla Playwright (patchright not installed)")
    return await async_playwright().start()


def _is_browser_crash(error: BaseException) -> bool:
    message = str(error).casefold()
    return any(
        marker in message
        for marker in (
            "browser has been closed",
            "context or browser has been closed",
            "target page, context or browser has been closed",
            "browser disconnected",
            "connection closed",
        )
    )


def _is_corrupt_profile(error: BaseException) -> bool:
    message = str(error).casefold()
    return "profile" in message and any(
        marker in message for marker in ("corrupt", "invalid", "cannot read", "failed to load")
    )


class BrowserSessionManager:
    """Own one lazy persistent Playwright context and serialize its page use."""

    def __init__(
        self,
        *,
        profile_dir: str | Path | None = None,
        idle_ttl_seconds: float = 300.0,
        health_check_interval_seconds: float = 30.0,
        max_pages: int = 1,
        max_requests: int = 100,
        playwright_factory: Callable[[], Awaitable[Any]] = _start_playwright,
        resolver: UrlResolver = default_resolver,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        observability: Observability | None = None,
    ) -> None:
        configured_profile = os.getenv("STEALTH_BROWSER_PROFILE_DIR", "").strip()
        self.profile_dir = Path(
            profile_dir
            or configured_profile
            or (Path(tempfile.gettempdir()) / "pw_stealth_profile")
        )
        self.idle_ttl_seconds = max(0.0, idle_ttl_seconds)
        self.health_check_interval_seconds = max(0.0, health_check_interval_seconds)
        self.max_pages = max(1, max_pages)
        self.max_requests = max(1, max_requests)
        self._playwright_factory = playwright_factory
        self._resolver = resolver
        self._clock = clock
        self._sleep = sleep
        self._observability = observability or default_observability
        self._lock = asyncio.Lock()
        self._playwright: Any | None = None
        self._context: BrowserContext | Any | None = None
        self._page: Page | Any | None = None
        self._request_count = 0
        self._last_used_at: float | None = None
        self._last_health_check_at: float | None = None
        self._navigation_violation: UrlPolicyViolation | None = None

    async def fetch(
        self,
        url: str,
        timeout: int = 60_000,
        *,
        persist_cookies: bool = True,
    ) -> str:
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright not installed")
        validated = validate_fetch_url(url, resolver=self._resolver)
        canonical_url = validated.canonical_url

        async with self._lock:
            await self._ensure_session()
            for crash_attempt in range(2):
                try:
                    result = await self._fetch_locked(
                        canonical_url,
                        timeout=timeout,
                        persist_cookies=persist_cookies,
                    )
                    self._request_count += 1
                    self._last_used_at = self._clock()
                    return result
                except Exception as exc:
                    if crash_attempt == 0 and _is_browser_crash(exc):
                        await self._restart_session()
                        continue
                    raise
        raise RuntimeError("Browser session fetch failed")

    async def close(self) -> None:
        async with self._lock:
            await self._close_session()

    async def _ensure_session(self) -> None:
        now = self._clock()
        if self._context is None or self._page is None:
            await self._start_session()
            return
        idle_expired = (
            self._last_used_at is not None
            and self.idle_ttl_seconds > 0
            and now - self._last_used_at >= self.idle_ttl_seconds
        )
        page_limit_reached = len(self._context.pages) > self.max_pages
        request_limit_reached = self._request_count >= self.max_requests
        health_due = (
            self._last_health_check_at is None
            or now - self._last_health_check_at >= self.health_check_interval_seconds
        )
        unhealthy = health_due and not self._is_healthy()
        if idle_expired or page_limit_reached or request_limit_reached or unhealthy:
            await self._restart_session()
        elif health_due:
            self._last_health_check_at = now

    def _is_healthy(self) -> bool:
        if self._context is None or self._page is None:
            return False
        browser = getattr(self._context, "browser", None)
        if browser is not None:
            is_connected = getattr(browser, "is_connected", None)
            if callable(is_connected) and not is_connected():
                return False
        is_closed = getattr(self._page, "is_closed", None)
        return not (callable(is_closed) and is_closed())

    async def _start_session(self) -> None:
        try:
            await self._launch_persistent_context()
        except Exception as exc:
            await self._close_session()
            if not _is_corrupt_profile(exc):
                raise
            self._rotate_profile()
            await self._launch_persistent_context()
        self._observability.record_browser_lifecycle("launch")

    async def _launch_persistent_context(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.profile_dir.chmod(0o700)
        except OSError:
            pass
        self._playwright = await self._playwright_factory()
        display = _detect_display()
        ua = pick_user_agent()
        viewport = pick_viewport()
        proxy = proxy_pool.get_next() if proxy_pool.proxies else None
        # Build args: our stealth flags minus any harmful defaults Playwright adds
        final_args = STEALTH_LAUNCH_ARGS
        if not PATCHRIGHT_AVAILABLE:
            # Patchright already filters harmful args internally.
            # For vanilla Playwright, we need to explicitly ignore them.
            final_args = filter_harmful_args(STEALTH_LAUNCH_ARGS) + [
                arg for arg in STEALTH_LAUNCH_ARGS if arg not in HARMFUL_ARGS
            ]
            # Deduplicate while preserving order
            seen = set()
            final_args = [a for a in final_args if not (a in seen or seen.add(a))]

        self._context = await self._playwright.chromium.launch_persistent_context(
            str(self.profile_dir),
            headless=not bool(display),
            viewport=viewport,
            user_agent=ua,
            java_script_enabled=True,
            accept_downloads=False,
            args=final_args,
            proxy=({"server": proxy.url} if proxy else None),
            ignore_default_args=list(HARMFUL_ARGS),  # Remove Playwright's harmful defaults
        )
        await self._context.add_init_script(build_stealth_script(ua))
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        for extra_page in tuple(self._context.pages[1:]):
            await extra_page.close()
        self._configure_page(self._page)
        self._request_count = 0
        self._last_used_at = self._clock()
        self._last_health_check_at = self._last_used_at

    def _configure_page(self, page: Page | Any) -> None:
        def close_popup(popup: Page | Any) -> None:
            asyncio.create_task(popup.close())

        page.on("popup", close_popup)

    async def _install_resource_blocking(self, page: Page | Any) -> None:
        """Block unnecessary resources (fonts, images, media) for faster fetches.

        Ported from Scrapling's EXTRA_RESOURCES approach.
        Skips blocking for OCR-dependent sites that need image rendering.
        """
        if not hasattr(page, "route") or getattr(page, "_novel_resource_blocker", False):
            return

        blocked_types = {
            "font",
            "media",
            "websocket",
            "beacon",
            "texttrack",
            "csp_report",
        }
        # Note: images NOT blocked globally — some OCR sites need screenshots

        try:
            async def block_handler(route: Any, request: Any) -> None:
                resource_type = getattr(request, "resource_type", "")
                if resource_type in blocked_types:
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", block_handler)
            setattr(page, "_novel_resource_blocker", True)
        except Exception:
            pass

    async def _install_navigation_guard(self, page: Page | Any) -> None:
        if not hasattr(page, "route") or getattr(page, "_novel_navigation_guard", False):
            return

        async def guard(route: Any, request: Any) -> None:
            try:
                is_navigation = request.is_navigation_request()
                is_top_level = request.frame == page.main_frame
                scheme = urlsplit(request.url).scheme.casefold()
                if scheme not in {"about", "blob", "data"}:
                    validate_fetch_url(request.url, resolver=self._resolver)
            except UrlPolicyViolation as exc:
                if is_navigation and is_top_level:
                    self._navigation_violation = exc
                await route.abort("blockedbyclient")
                return
            await route.continue_()

        await page.route("**/*", guard)
        try:
            setattr(page, "_novel_navigation_guard", True)
        except (AttributeError, TypeError):
            pass

    async def _fetch_locked(self, url: str, *, timeout: int, persist_cookies: bool) -> str:
        page = self._page
        context = self._context
        if page is None or context is None:
            raise RuntimeError("Browser session is not initialized")
        page.set_default_timeout(timeout)
        await self._install_navigation_guard(page)
        await self._install_resource_blocking(page)
        cookies = load_cookies(url)
        if cookies and hasattr(context, "add_cookies"):
            await context.add_cookies(cookies)
        self._navigation_violation = None
        try:
            await page.goto(url, wait_until="domcontentloaded")
        except Exception:
            if self._navigation_violation is not None:
                raise self._navigation_violation
            raise
        if self._navigation_violation is not None:
            raise self._navigation_violation
        final_url = getattr(page, "url", url)
        validate_fetch_url(final_url, resolver=self._resolver)

        await self._sleep(5)
        title = await page.title()
        safe_url = redacted_url(url)

        # --- Multi-strategy Cloudflare challenge handling ---
        await self._handle_cloudflare_challenge(page, url, title, safe_url)

        captcha_found = await StealthBrowser._detect_and_solve_captcha(page, url)
        if captcha_found:
            await self._sleep(3)
        if persist_cookies:
            current_cookies = await context.cookies()
            if current_cookies:
                save_cookies(url, current_cookies)
                logger.debug("Saved %d cookies for %s", len(current_cookies), safe_url)
        return await page.content()

    async def _handle_cloudflare_challenge(
        self,
        page: Page | Any,
        url: str,
        initial_title: str,
        safe_url: str,
    ) -> None:
        """Detect and resolve Cloudflare challenges using multiple strategies.

        Strategy 1: Wait up to 45s for managed challenge auto-resolve.
        Strategy 2: Reload page and wait again.
        Strategy 3: Fresh navigation (clear cookies for domain, reload).
        """
        challenge_keywords = ("Just a moment", "Checking your browser", "Attention Required")

        def is_challenge(title_text: str) -> bool:
            return any(kw in title_text for kw in challenge_keywords)

        if not is_challenge(initial_title):
            return

        logger.info("Cloudflare challenge detected for %s (strategy 1: wait)", safe_url)

        # Strategy 1: Wait for auto-resolve
        try:
            await page.wait_for_function(
                "document.title && !document.title.includes('Just a moment') "
                "&& !document.title.includes('Checking your browser') "
                "&& !document.title.includes('Attention Required')",
                timeout=45_000,
            )
            logger.info("Cloudflare challenge auto-resolved for %s", safe_url)
            return
        except Exception:
            logger.warning(
                "Cloudflare challenge did not auto-resolve for %s (strategy 2: reload)",
                safe_url,
            )

        # Strategy 2: Reload
        try:
            await page.reload(wait_until="domcontentloaded", timeout=30_000)
            await self._sleep(5)
            title_after_reload = await page.title()
            if not is_challenge(title_after_reload):
                logger.info("Cloudflare resolved after reload for %s", safe_url)
                return
            logger.warning("Still blocked after reload for %s (strategy 3: fresh nav)", safe_url)
        except Exception as reload_error:
            logger.warning(
                "Reload failed for %s (%s) — trying fresh navigation",
                safe_url,
                type(reload_error).__name__,
            )

        # Strategy 3: Clear cookies and navigate fresh
        try:
            # Clear cookies for this domain to force a fresh challenge cycle
            context = self._context
            if context is not None:
                parsed = urlsplit(url)
                domain = parsed.hostname or ""
                if domain:
                    # Clear all cookies for this domain
                    all_cookies = await context.cookies()
                    domain_cookies = [c for c in all_cookies if domain in c.get("domain", "")]
                    if domain_cookies:
                        for cookie in domain_cookies:
                            try:
                                await context.clear_cookies(
                                    name=cookie.get("name", ""),
                                    domain=cookie.get("domain", ""),
                                )
                            except Exception:
                                pass
                        logger.info("Cleared %d cookies for %s", len(domain_cookies), safe_url)

            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await self._sleep(8)
            title_after_fresh = await page.title()
            if not is_challenge(title_after_fresh):
                logger.info("Cloudflare resolved after fresh navigation for %s", safe_url)
                return
            logger.warning("Cloudflare challenge persists after all strategies for %s", safe_url)
        except Exception as nav_error:
            logger.warning(
                "Fresh navigation failed for %s (%s)",
                safe_url,
                type(nav_error).__name__,
            )

        # Strategy 3.5: Free Turnstile checkbox clicking (no API cost)
        try:
            clicked = await self._try_turnstile_click(page, safe_url)
            if clicked:
                title_after_click = await page.title()
                if not is_challenge(title_after_click):
                    logger.info("Cloudflare resolved via free Turnstile click for %s", safe_url)
                    return
        except Exception as click_error:
            logger.warning(
                "Turnstile click failed for %s (%s)",
                safe_url,
                type(click_error).__name__,
            )

        # Strategy 4: API captcha solver for embedded Turnstile widgets
        try:
            solved = await StealthBrowser._detect_and_solve_captcha(page, url)
            if solved:
                logger.info("Captcha solved via API for %s (strategy 4)", safe_url)
                return
        except Exception as solver_error:
            logger.warning(
                "API captcha solver failed for %s (%s)",
                safe_url,
                type(solver_error).__name__,
            )

    async def _try_turnstile_click(self, page: Page | Any, safe_url: str) -> bool:
        """Attempt to solve Cloudflare Turnstile by clicking the checkbox widget.

        Ported from Scrapling's _cloudflare_solver approach.
        Detects the Turnstile iframe, calculates checkbox coordinates, and clicks.
        Returns True if a click was attempted, False if no widget found.
        """
        import random

        # Pattern for Cloudflare challenge iframe URL
        cf_iframe = None
        for frame in page.frames:
            if "challenges.cloudflare.com" in (frame.url or ""):
                cf_iframe = frame
                break

        if cf_iframe is None:
            # Try CSS selectors for embedded Turnstile
            box_selectors = [
                "#cf_turnstile div",
                "#cf-turnstile div",
                ".turnstile > div > div",
                ".main-content p + div > div > div",
            ]
            for selector in box_selectors:
                try:
                    locator = page.locator(selector).last
                    box = await locator.bounding_box()
                    if box and box.get("width", 0) > 10:
                        # Calculate checkbox coordinates (offset from top-left of widget)
                        click_x = box["x"] + random.randint(26, 28)
                        click_y = box["y"] + random.randint(25, 27)
                        await page.mouse.click(click_x, click_y, delay=random.randint(100, 200))
                        logger.info("Clicked embedded Turnstile at %s for %s", selector, safe_url)
                        await self._sleep(3)
                        return True
                except Exception:
                    continue
            return False

        # Found CF iframe — click the checkbox inside it
        try:
            await self._sleep(1)  # Let iframe stabilize
            frame_element = await cf_iframe.frame_element()
            box = await frame_element.bounding_box()
            if not box:
                return False

            click_x = box["x"] + random.randint(26, 28)
            click_y = box["y"] + random.randint(25, 27)
            await page.mouse.click(click_x, click_y, delay=random.randint(100, 200))
            logger.info("Clicked Turnstile iframe checkbox for %s", safe_url)
            await self._sleep(3)
            return True
        except Exception:
            return False

    async def _restart_session(self) -> None:
        self._observability.record_browser_lifecycle("restart")
        await self._close_session()
        await self._start_session()

    async def _close_session(self) -> None:
        context, playwright = self._context, self._playwright
        self._context = None
        self._page = None
        self._playwright = None
        self._request_count = 0
        self._last_used_at = None
        self._last_health_check_at = None
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                pass

    def _rotate_profile(self) -> None:
        if not self.profile_dir.exists():
            return
        rotated = self.profile_dir.with_name(
            f"{self.profile_dir.name}.corrupt-{time.time_ns()}"
        )
        try:
            os.replace(self.profile_dir, rotated)
        except OSError:
            shutil.rmtree(self.profile_dir, ignore_errors=True)


def _detect_display() -> str:
    """Detect available X display. Returns empty string for headless.

    In Docker containers without X server, xdpyinfo is missing and we
    should NOT assume :99 exists — that causes headed launch crash.
    """
    display = os.getenv("DISPLAY", "")
    if display:
        return display
    import subprocess

    for candidate in (":0", ":99"):
        try:
            result = subprocess.run(
                ["xdpyinfo", "-display", candidate],
                capture_output=True,
                timeout=3,
            )
            if result.returncode == 0:
                os.environ["DISPLAY"] = candidate
                return candidate
        except FileNotFoundError:
            # xdpyinfo not installed → no X server → headless
            return ""
        except Exception:
            continue
    return ""


class StealthBrowser:
    """Playwright-based stealth browser for bypassing Cloudflare."""

    def __init__(self, manager: BrowserSessionManager | None = None):
        self.manager = manager or BrowserSessionManager()

    async def init(self):
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )

    async def close(self):
        await self.manager.close()

    # ------------------------------------------------------------------ #
    # Captcha detection (in-page JS + iframe scanning)
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _detect_and_solve_captcha(page: Page, url: str) -> bool:
        """Detect Turnstile/reCAPTCHA on page and in child iframes.

        Solves via configured API solver if available. Injects token using
        callback-based approach that actually triggers the page's submit flow.

        Returns True if a captcha was detected (regardless of solve success).
        """
        solver = get_captcha_solver()
        safe_url = redacted_url(url)

        # --- Search main frame AND child frames for Turnstile ---
        turnstile_result = await StealthBrowser._find_captcha_element(
            page,
            selectors=[
                '[data-sitekey]:not(.g-recaptcha)',
                '.cf-turnstile',
                'div[data-testid="turnstile"]',
            ],
        )
        if turnstile_result:
            frame, element = turnstile_result
            sitekey = await element.get_attribute("data-sitekey")
            if sitekey:
                logger.info("Turnstile detected (sitekey=%s) for %s", sitekey[:12], safe_url)
                if solver:
                    # Use the frame's URL as page_url for solver API
                    frame_url = frame.url if frame != page.main_frame else url
                    token = solver.solve_turnstile(frame_url, sitekey)
                    if token:
                        await StealthBrowser._inject_turnstile_token(frame, token)
                        logger.info("Turnstile token injected via callback")
                        await page.wait_for_timeout(3000)
                        return True
                    else:
                        logger.warning("Turnstile solve returned empty token")
                        return True
                else:
                    logger.warning("Turnstile detected but no captcha solver configured")
                    return True

        # --- reCAPTCHA v2 ---
        recaptcha_result = await StealthBrowser._find_captcha_element(
            page,
            selectors=['.g-recaptcha[data-sitekey]'],
        )
        if recaptcha_result:
            frame, element = recaptcha_result
            sitekey = await element.get_attribute("data-sitekey")
            if sitekey:
                logger.info("reCAPTCHA detected (sitekey=%s) for %s", sitekey[:12], safe_url)
                if solver:
                    frame_url = frame.url if frame != page.main_frame else url
                    token = solver.solve_recaptcha(frame_url, sitekey)
                    if token:
                        await StealthBrowser._inject_recaptcha_token(frame, token)
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

    @staticmethod
    async def _find_captcha_element(
        page: Page,
        selectors: list[str],
    ) -> tuple[Any, Any] | None:
        """Search main frame and all child frames for a captcha element.

        Returns (frame, element) tuple or None.
        """
        # Check main frame first
        for selector in selectors:
            el = await page.query_selector(selector)
            if el:
                return page.main_frame, el

        # Check child frames (Turnstile often embeds in cross-origin iframe)
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            for selector in selectors:
                try:
                    el = await frame.query_selector(selector)
                    if el:
                        return frame, el
                except Exception:
                    # Cross-origin frames may block query_selector
                    continue

        return None

    @staticmethod
    async def _inject_turnstile_token(frame: Any, token: str) -> None:
        """Inject Turnstile token using callback-based approach.

        Tries multiple strategies to ensure the token actually triggers
        the page's form submission or callback flow.
        """
        await frame.evaluate(
            """(token) => {
                // Strategy 1: Find the data-callback and invoke it directly
                const widget = document.querySelector('[data-sitekey]');
                if (widget) {
                    // Set hidden response field
                    const responseInput = document.querySelector(
                        'input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]'
                    );
                    if (responseInput) {
                        responseInput.value = token;
                    }

                    // Try explicit callback
                    const callbackName = widget.getAttribute('data-callback');
                    if (callbackName && typeof window[callbackName] === 'function') {
                        window[callbackName](token);
                        return;
                    }

                    // Try turnstile.execute / success callback
                    if (window.turnstile) {
                        // Set response on the widget widget ID
                        const widgetId = widget.getAttribute('data-turnstile-id');
                        if (widgetId && window.turnstile.getResponse) {
                            // Manually trigger the callback if registered
                            const successCallback = window.turnstile._callbacks?.[widgetId];
                            if (successCallback) {
                                successCallback(token);
                                return;
                            }
                        }
                    }

                    // Strategy 2: Set token on element and submit parent form
                    widget.setAttribute('data-response', token);
                    const form = widget.closest('form');
                    if (form) {
                        form.submit();
                        return;
                    }

                    // Strategy 3: Dispatch a custom event
                    widget.dispatchEvent(new CustomEvent('cf:turnstile:success', {
                        detail: { token },
                        bubbles: true,
                    }));
                }
            }""",
            token,
        )

    @staticmethod
    async def _inject_recaptcha_token(frame: Any, token: str) -> None:
        """Inject reCAPTCHA v2 token using textarea + callback approach."""
        await frame.evaluate(
            """(token) => {
                // Set the hidden textarea
                const textarea = document.getElementById('g-recaptcha-response');
                if (textarea) {
                    textarea.innerHTML = token;
                    textarea.value = token;
                }

                // Try explicit callback
                const widget = document.querySelector('.g-recaptcha');
                if (widget) {
                    const callbackName = widget.getAttribute('data-callback');
                    if (callbackName && typeof window[callbackName] === 'function') {
                        window[callbackName](token);
                        return;
                    }
                }

                // Try calling grecaptcha.execute if available
                if (window.grecaptcha && typeof window.grecaptcha.execute === 'function') {
                    try {
                        const widgetId = widget?.getAttribute('data-widget-id');
                        if (widgetId !== null && widgetId !== undefined) {
                            // Can't set response via execute, but trigger callback
                        }
                    } catch(e) {}
                }

                // Fallback: submit parent form
                const form = document.querySelector('.g-recaptcha')?.closest('form');
                if (form) {
                    // Give the page time to process the token
                    setTimeout(() => form.submit(), 500);
                }
            }""",
            token,
        )

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
        """Fetch through the shared persistent browser session manager."""
        return await self.manager.fetch(
            url,
            timeout=timeout,
            persist_cookies=persist_cookies,
        )

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
    await asyncio.to_thread(_sync_browser_runtime.close)


# --------------------------------------------------------------------------- #
# Sync wrapper — used by source_adapters.fetch_public_html
# --------------------------------------------------------------------------- #


class _SyncBrowserRuntime:
    """Keep one manager on one worker event loop for legacy synchronous callers."""

    def __init__(
        self,
        *,
        manager_factory: Callable[[], BrowserSessionManager] = BrowserSessionManager,
    ) -> None:
        self._lock = threading.Lock()
        self._manager_factory = manager_factory
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._manager: BrowserSessionManager | None = None
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None

    def fetch(self, url: str, timeout: int) -> str:
        self._ensure_started()
        with self._lock:
            loop, manager = self._loop, self._manager
        if loop is None or manager is None:
            raise RuntimeError("Browser session runtime failed to start")
        future = asyncio.run_coroutine_threadsafe(
            manager.fetch(url, timeout=timeout),
            loop,
        )
        return future.result()

    def close(self) -> None:
        with self._lock:
            thread, loop, manager = self._thread, self._loop, self._manager
            if thread is None or loop is None or manager is None:
                return
        try:
            asyncio.run_coroutine_threadsafe(manager.close(), loop).result()
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=10)
            with self._lock:
                if self._thread is thread:
                    self._thread = None
                    self._loop = None
                    self._manager = None

    def _ensure_started(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._ready.clear()
            self._startup_error = None
            self._thread = threading.Thread(
                target=self._thread_main,
                name="browser-session",
                daemon=True,
            )
            self._thread.start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("Browser session runtime startup timed out")
        if self._startup_error is not None:
            raise RuntimeError("Browser session runtime failed to start") from self._startup_error

    def _thread_main(self) -> None:
        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            manager = self._manager_factory()
            with self._lock:
                self._loop = loop
                self._manager = manager
            self._ready.set()
            loop.run_forever()
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
        finally:
            if loop is not None and not loop.is_closed():
                loop.close()


_sync_browser_runtime = _SyncBrowserRuntime()
atexit.register(_sync_browser_runtime.close)

def fetch_with_stealth_sync(url: str, timeout: int = 60_000) -> str:
    """Sync wrapper around ``StealthBrowser.fetch_with_stealth``.

    Reuses the lazy session manager on a dedicated worker event loop. Returns
    page HTML on success and raises ``RuntimeError`` on failure.
    """
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError(
            "Playwright not installed. Run: pip install playwright && playwright install chromium"
        )

    return _sync_browser_runtime.fetch(url, timeout)
