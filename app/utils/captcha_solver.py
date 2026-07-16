"""Captcha solving integration with 2Captcha/Capsolver API.

Supports Cloudflare Turnstile and Google reCAPTCHA v2/v3 via two providers:
  - 2captcha.com  (uses ``requestId`` in task lifecycle)
  - capsolver.com (uses ``taskId`` in task lifecycle)

All API responses are treated as untrusted: only safe status fields are logged.
No page URL, sitekey, provider payload, or solved token is ever written to logs.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 5
_RETRY_DELAY_SECONDS = 5
_MAX_SOLVE_RETRIES = 2  # 1 initial + 1 retry


class CaptchaSolver:
    """Solve CAPTCHAs via 2Captcha or Capsolver API."""

    def __init__(
        self,
        api_key: str,
        provider: str = "2captcha",
        *,
        session_factory=None,
    ):
        self.api_key = api_key
        self.provider = provider.lower()
        self.base_url = (
            "https://2captcha.com"
            if self.provider == "2captcha"
            else "https://api.capsolver.com"
        )
        # Inject a shared session for connection pooling + test mocking
        self._session = session_factory() if session_factory else requests.Session()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def solve_turnstile(
        self,
        page_url: str,
        sitekey: str,
        timeout: int = 120,
    ) -> Optional[str]:
        """Solve Cloudflare Turnstile captcha.

        Returns the token string on success, ``None`` on failure.
        """
        for attempt in range(1, _MAX_SOLVE_RETRIES + 1):
            token = self._solve_turnstile_once(page_url, sitekey, timeout)
            if token:
                return token
            if attempt < _MAX_SOLVE_RETRIES:
                logger.info(
                    "Turnstile solve attempt %d failed, retrying in %ds",
                    attempt,
                    _RETRY_DELAY_SECONDS,
                )
                time.sleep(_RETRY_DELAY_SECONDS)
        logger.warning("Turnstile solve exhausted %d attempts", _MAX_SOLVE_RETRIES)
        return None

    def solve_recaptcha(
        self,
        page_url: str,
        sitekey: str,
        timeout: int = 120,
    ) -> Optional[str]:
        """Solve reCAPTCHA v2/v3.

        Returns the token string on success, ``None`` on failure.
        """
        for attempt in range(1, _MAX_SOLVE_RETRIES + 1):
            token = self._solve_recaptcha_once(page_url, sitekey, timeout)
            if token:
                return token
            if attempt < _MAX_SOLVE_RETRIES:
                logger.info(
                    "reCAPTCHA solve attempt %d failed, retrying in %ds",
                    attempt,
                    _RETRY_DELAY_SECONDS,
                )
                time.sleep(_RETRY_DELAY_SECONDS)
        logger.warning("reCAPTCHA solve exhausted %d attempts", _MAX_SOLVE_RETRIES)
        return None

    # ------------------------------------------------------------------ #
    # Internal: single-attempt solve helpers
    # ------------------------------------------------------------------ #

    def _solve_turnstile_once(
        self, page_url: str, sitekey: str, timeout: int
    ) -> Optional[str]:
        """Single Turnstile solve attempt (no retry)."""
        if self.provider == "2captcha":
            payload = {
                "key": self.api_key,
                "method": "turnstile",
                "pageurl": page_url,
                "data-sitekey": sitekey,
                "json": 1,
            }
        else:  # capsolver — Proxyless is cheaper and more reliable
            payload = {
                "clientKey": self.api_key,
                "task": {
                    "type": "AntiTurnstileTaskProxyless",
                    "websiteURL": page_url,
                    "websiteKey": sitekey,
                },
            }

        task_id = self._create_task(payload)
        if task_id is None:
            return None

        return self._poll_result(task_id, captcha_type="turnstile")

    def _solve_recaptcha_once(
        self, page_url: str, sitekey: str, timeout: int
    ) -> Optional[str]:
        """Single reCAPTCHA solve attempt (no retry)."""
        if self.provider == "2captcha":
            payload = {
                "key": self.api_key,
                "method": "userrecaptcha",
                "googlekey": sitekey,
                "pageurl": page_url,
                "json": 1,
            }
        else:  # capsolver
            payload = {
                "clientKey": self.api_key,
                "task": {
                    "type": "RecaptchaV2Task",
                    "websiteURL": page_url,
                    "websiteKey": sitekey,
                },
            }

        task_id = self._create_task(payload)
        if task_id is None:
            return None

        return self._poll_result(task_id, captcha_type="recaptcha")

    # ------------------------------------------------------------------ #
    # Internal: API communication
    # ------------------------------------------------------------------ #

    def _create_task(self, payload: dict) -> Optional[str]:
        """Send createTask request and return the task/request identifier."""
        url = f"{self.base_url}/createTask"
        try:
            resp = self._session.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.warning("Captcha task creation request failed")
            return None

        # 2Captcha uses requestId; Capsolver uses taskId
        task_id = data.get("requestId") or data.get("taskId")
        if not task_id:
            logger.warning("Captcha provider response did not include a task ID")
            return None
        return str(task_id)

    def _poll_result(
        self, task_id: str, *, captcha_type: str, timeout: int = 120
    ) -> Optional[str]:
        """Poll getTaskResult until token is ready, error, or timeout."""
        url = f"{self.base_url}/getTaskResult"

        if self.provider == "2captcha":
            poll_payload = {
                "key": self.api_key,
                "requestId": task_id,
                "json": 1,
            }
        else:  # capsolver
            poll_payload = {
                "clientKey": self.api_key,
                "taskId": task_id,
            }

        start = time.time()
        while time.time() - start < timeout:
            try:
                resp = self._session.post(url, json=poll_payload, timeout=10)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue

            status = data.get("status")
            error_id = data.get("errorId", 0)

            # Capsolver: status == "ready" or errorId == 0 and solution present
            # 2Captcha: status == "ready" or request == status code
            if status == "ready" or (self.provider == "capsolver" and error_id == 0):
                solution = data.get("solution", {})
                if captcha_type == "turnstile":
                    token = solution.get("token") or solution.get(
                        "gRecaptchaResponse"
                    )
                else:
                    token = solution.get("gRecaptchaResponse") or solution.get("token")
                if token:
                    logger.info("Captcha solved successfully (%s)", captcha_type)
                    return str(token)
                logger.warning("Captcha solution missing token field")
                return None

            if (
                status == "error"
                or error_id
                or data.get("error")
                or (self.provider == "2captcha" and data.get("request") == "ERROR")
            ):
                logger.warning("Captcha provider returned a task error")
                return None

            time.sleep(_POLL_INTERVAL_SECONDS)

        logger.warning("Captcha task timed out after %ds (%s)", timeout, captcha_type)
        return None


# --------------------------------------------------------------------------- #
# Global singleton
# --------------------------------------------------------------------------- #

_solver: Optional[CaptchaSolver] = None


def init_captcha_solver(
    api_key: str, provider: str = "2captcha"
) -> CaptchaSolver:
    """Initialize the global captcha solver."""
    global _solver
    _solver = CaptchaSolver(api_key, provider)
    return _solver


def get_captcha_solver() -> Optional[CaptchaSolver]:
    """Get the global captcha solver instance."""
    return _solver
