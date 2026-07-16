"""Tests for CAPTCHA bypass upgrade (C01-C05).

All tests use mocks — no real browser, API calls, or Internet access.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.utils.captcha_solver import CaptchaSolver
from app.utils.proxy_pool import (
    ProxyConfig,
    ProxyPool,
    _parse_proxy_entry,
    build_proxy_pool_from_env,
)
from app.utils.stealth_scripts import (
    STEALTH_LAUNCH_ARGS,
    build_stealth_script,
    pick_user_agent,
    pick_viewport,
)


# ========================================================================== #
# C01: Fingerprint stealth hardening
# ========================================================================== #


class TestStealthScripts:
    """Tests for the stealth init script generation."""

    def test_stealth_script_does_not_use_integer_plugins(self):
        """BUG-1 fix: navigator.plugins must not be [1,2,3,4,5]."""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"
        script = build_stealth_script(ua)
        # Must contain Plugin prototype mock
        assert "Plugin.prototype" in script
        assert "MimeType.prototype" in script
        # Must NOT contain the old integer array
        assert "[1, 2, 3, 4, 5]" not in script

    def test_stealth_script_patches_webgl(self):
        """WebGL vendor/renderer spoofing must be present."""
        script = build_stealth_script("test")
        assert "37445" in script  # UNMASKED_VENDOR_WEBGL
        assert "37446" in script  # UNMASKED_RENDERER_WEBGL
        assert "Intel" in script

    def test_stealth_script_patches_audio_context(self):
        """AudioContext fingerprint noise must be present."""
        script = build_stealth_script("test")
        assert "AudioBuffer" in script
        assert "getChannelData" in script

    def test_stealth_script_patches_canvas(self):
        """Canvas toDataURL noise must be present."""
        script = build_stealth_script("test")
        assert "toDataURL" in script
        assert "getImageData" in script

    def test_stealth_script_patches_webrtc(self):
        """WebRTC IP leak prevention must be present."""
        script = build_stealth_script("test")
        assert "RTCPeerConnection" in script
        assert "iceTransportPolicy" in script or "relay" in script

    def test_stealth_script_sets_platform_matching_ua(self):
        """navigator.platform must match the UA string."""
        win_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131"
        mac_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/131"
        linux_ua = "Mozilla/5.0 (X11; Linux x86_64) Chrome/131"

        assert "Win32" in build_stealth_script(win_ua)
        assert "MacIntel" in build_stealth_script(mac_ua)
        assert "Linux x86_64" in build_stealth_script(linux_ua)

    def test_stealth_script_has_window_chrome_full_mock(self):
        """window.chrome must have runtime, app, csi, loadTimes."""
        script = build_stealth_script("test")
        assert "window.chrome.app" in script
        assert "window.chrome.csi" in script
        assert "window.chrome.loadTimes" in script

    def test_stealth_script_has_hardware_concurrency_and_memory(self):
        script = build_stealth_script("test")
        assert "hardwareConcurrency" in script
        assert "deviceMemory" in script

    def test_stealth_script_has_permissions_override(self):
        script = build_stealth_script("test")
        assert "permissions" in script
        assert "notifications" in script

    def test_launch_args_include_webrtc_flag(self):
        """BUG fix: WebRTC leak prevention flag must be in launch args."""
        assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in STEALTH_LAUNCH_ARGS

    def test_launch_args_disable_automation_controlled(self):
        assert "--disable-blink-features=AutomationControlled" in STEALTH_LAUNCH_ARGS

    def test_pick_user_agent_returns_from_pool(self):
        ua = pick_user_agent()
        assert "Chrome" in ua
        assert "Mozilla" in ua

    def test_pick_viewport_returns_valid_dict(self):
        vp = pick_viewport()
        assert "width" in vp
        assert "height" in vp
        assert vp["width"] >= 1280
        assert vp["height"] >= 720


# ========================================================================== #
# C03: CAPTCHA solver API fixes
# ========================================================================== #


class TestCaptchaSolver:
    """Tests for the fixed CAPTCHA solver."""

    def _make_mock_session(self, responses: list[dict]):
        """Create a mock requests.Session with queued responses."""
        session = MagicMock()
        response_queue = list(responses)

        def mock_post(url, json=None, timeout=None):
            if response_queue:
                data = response_queue.pop(0)
                resp = MagicMock()
                resp.json.return_value = data
                resp.raise_for_status.return_value = None
                return resp
            resp = MagicMock()
            resp.json.return_value = {"status": "error"}
            resp.raise_for_status.return_value = None
            return resp

        session.post = mock_post
        return session

    def test_2captcha_create_task_uses_correct_field_name(self):
        """BUG-3 fix: 2Captcha returns requestId, not taskId."""
        session = self._make_mock_session([
            {"requestId": "12345", "status": "idle"},  # createTask
            {"status": "ready", "solution": {"token": "tok_abc"}},  # getTaskResult
        ])
        solver = CaptchaSolver(
            "fake_key", "2captcha", session_factory=lambda: session
        )
        token = solver.solve_turnstile("https://example.com", "0x4AAA")
        assert token == "tok_abc"

    def test_capsolver_create_task_uses_task_id(self):
        """Capsolver returns taskId."""
        session = self._make_mock_session([
            {"taskId": "task_678", "errorId": 0},  # createTask
            {"status": "ready", "solution": {"token": "tok_xyz"}, "errorId": 0},
        ])
        solver = CaptchaSolver(
            "fake_key", "capsolver", session_factory=lambda: session
        )
        token = solver.solve_turnstile("https://example.com", "0x4BBB")
        assert token == "tok_xyz"

    def test_2captcha_poll_payload_uses_request_id(self):
        """BUG-5 fix: poll must send requestId, not taskId."""
        captured_payloads = []

        session = MagicMock()

        def mock_post(url, json=None, timeout=None):
            captured_payloads.append(json)
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            if "createTask" in url:
                resp.json.return_value = {"requestId": "r1", "status": "idle"}
            else:
                resp.json.return_value = {"status": "ready", "solution": {"token": "t"}}
            return resp

        session.post = mock_post
        solver = CaptchaSolver(
            "fake_key", "2captcha", session_factory=lambda: session
        )
        solver.solve_turnstile("https://example.com", "0x4CCC")
        # The poll payload should have requestId
        poll_payload = captured_payloads[-1]
        assert "requestId" in poll_payload
        assert poll_payload["requestId"] == "r1"

    def test_capsolver_uses_proxyless_task_type(self):
        """Turnstile should use AntiTurnstileTaskProxyless for Capsolver."""
        captured = []

        session = MagicMock()

        def mock_post(url, json=None, timeout=None):
            captured.append(json)
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"taskId": "t1"}
            return resp

        session.post = mock_post
        solver = CaptchaSolver(
            "fake_key", "capsolver", session_factory=lambda: session
        )
        solver.solve_turnstile("https://example.com", "0x4DDD")
        create_payload = captured[0]
        assert create_payload["task"]["type"] == "AntiTurnstileTaskProxyless"

    def test_retry_on_failure(self):
        """Solver should retry once on solve failure."""
        session = self._make_mock_session([
            {"requestId": "r1"},  # attempt 1 createTask
            {"status": "error"},  # attempt 1 poll fail
            {"requestId": "r2"},  # attempt 2 createTask (retry)
            {"status": "ready", "solution": {"token": "tok_retry"}},  # attempt 2 success
        ])
        solver = CaptchaSolver(
            "fake_key", "2captcha", session_factory=lambda: session
        )
        with patch("app.utils.captcha_solver.time.sleep"):
            token = solver.solve_turnstile("https://example.com", "0x4EEE")
        assert token == "tok_retry"

    def test_no_raw_payload_in_logs(self, caplog):
        """No API response payload should appear in logs."""
        import logging

        session = self._make_mock_session([
            {"requestId": "r1", "sensitive_data": "SECRET"},
            {"status": "ready", "solution": {"token": "tok"}, "sensitive": "LEAK"},
        ])
        solver = CaptchaSolver(
            "fake_key", "2captcha", session_factory=lambda: session
        )
        with caplog.at_level(logging.WARNING):
            solver.solve_turnstile("https://example.com", "0x4FFF")
        for record in caplog.records:
            assert "SECRET" not in record.message
            assert "LEAK" not in record.message

    def test_recaptcha_2captcha_returns_correct_field(self):
        """reCAPTCHA token from 2Captcha should use solution.token."""
        session = self._make_mock_session([
            {"requestId": "r1"},
            {"status": "ready", "solution": {"token": "recap_tok"}},
        ])
        solver = CaptchaSolver(
            "fake_key", "2captcha", session_factory=lambda: session
        )
        token = solver.solve_recaptcha("https://example.com", "6LeAAA")
        assert token == "recap_tok"

    def test_recaptcha_capsolver_returns_grecaptcharesponse(self):
        """reCAPTCHA token from Capsolver should use gRecaptchaResponse."""
        session = self._make_mock_session([
            {"taskId": "t1", "errorId": 0},
            {"status": "ready", "solution": {"gRecaptchaResponse": "capsolver_tok"}, "errorId": 0},
        ])
        solver = CaptchaSolver(
            "fake_key", "capsolver", session_factory=lambda: session
        )
        token = solver.solve_recaptcha("https://example.com", "6LeBBB")
        assert token == "capsolver_tok"


# ========================================================================== #
# C05: Proxy pool
# ========================================================================== #


class TestProxyPool:
    """Tests for enhanced proxy pool."""

    def test_parse_http_proxy(self):
        proxy = _parse_proxy_entry("http://user:pass@host:8080")
        assert proxy.proxy_type == "http"
        assert proxy.username == "user"
        assert proxy.password == "pass"
        assert "host:8080" in proxy.url

    def test_parse_socks5_proxy(self):
        proxy = _parse_proxy_entry("socks5://host:1080")
        assert proxy.proxy_type == "socks5"
        assert proxy.is_socks5 is True

    def test_parse_socks5_with_auth(self):
        proxy = _parse_proxy_entry("socks5://user:pass@host:1080")
        assert proxy.proxy_type == "socks5"
        assert proxy.username == "user"
        assert proxy.password == "pass"

    def test_parse_bare_host_port(self):
        proxy = _parse_proxy_entry("host:8080")
        assert proxy.proxy_type == "http"

    def test_round_robin_skips_unhealthy(self):
        pool = ProxyPool()
        pool.add_proxy(ProxyConfig(url="http://p1:8080"))
        pool.add_proxy(ProxyConfig(url="http://p2:8080"))
        pool.add_proxy(ProxyConfig(url="http://p3:8080"))
        pool.mark_healthy("http://p1:8080", False)
        pool.mark_healthy("http://p3:8080", False)

        next_proxy = pool.get_next()
        assert next_proxy.url == "http://p2:8080"

    def test_reset_health(self):
        pool = ProxyPool()
        pool.add_proxy(ProxyConfig(url="http://p1:8080"))
        pool.mark_healthy("http://p1:8080", False)
        assert pool.healthy_count == 0
        pool.reset_health()
        assert pool.healthy_count == 1

    def test_should_retry_on_timeout(self):
        pool = ProxyPool()
        assert pool.should_retry_with_proxy(TimeoutError("Connection timed out"))

    def test_should_retry_on_rate_limit(self):
        pool = ProxyPool()
        assert pool.should_retry_with_proxy(Exception("429 rate limit"))

    def test_should_not_retry_on_404(self):
        pool = ProxyPool()
        assert not pool.should_retry_with_proxy(Exception("404 not found"))

    def test_to_requests_proxies(self):
        proxy = ProxyConfig(url="http://host:8080")
        proxies = proxy.to_requests_proxies()
        assert "http" in proxies
        assert "https" in proxies

    def test_empty_env_returns_empty_pool(self, monkeypatch):
        monkeypatch.delenv("PROXY_LIST", raising=False)
        pool = build_proxy_pool_from_env()
        assert pool.count == 0
        assert pool.get_next() is None
