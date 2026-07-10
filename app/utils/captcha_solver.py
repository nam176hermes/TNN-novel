"""Captcha solving integration with 2Captcha/Capsolver API."""

from __future__ import annotations

import time
from typing import Optional
import requests


class CaptchaSolver:
    """Solve CAPTCHAs via 2Captcha or Capsolver API."""

    def __init__(self, api_key: str, provider: str = "2captcha"):
        self.api_key = api_key
        self.provider = provider.lower()
        self.base_url = (
            "https://2captcha.com" if self.provider == "2captcha"
            else "https://api.capsolver.com"
        )

    def solve_turnstile(
        self,
        page_url: str,
        sitekey: str,
        site_domain: str = "demo",
        timeout: int = 120,
    ) -> Optional[str]:
        """Solve Cloudflare Turnstile captcha."""
        create_task_url = f"{self.base_url}/createTask"
        get_result_url = f"{self.base_url}/getTaskResult"

        # Create task
        if self.provider == "2captcha":
            payload = {
                "key": self.api_key,
                "method": "turnstile",
                "pageurl": page_url,
                "data-sitekey": sitekey,
                "json": 1,
            }
        else:  # capsolver
            payload = {
                "clientKey": self.api_key,
                "task": {
                    "type": "TurnstileTask",
                    "websiteURL": page_url,
                    "websiteKey": sitekey,
                },
            }

        try:
            resp = requests.post(create_task_url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[Captcha] Create task failed: {e}")
            return None

        if self.provider == "2captcha":
            task_id = data.get("taskId")
        else:
            task_id = data.get("taskId") or data.get("taskId")

        if not task_id:
            print(f"[Captcha] No task ID returned: {data}")
            return None

        # Poll for result
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                result_resp = requests.post(
                    get_result_url,
                    json={"key": self.api_key, "taskId": task_id} if self.provider == "2captcha" else {"clientKey": self.api_key, "taskId": task_id},
                    timeout=10,
                )
                result_data = result_resp.json()
            except Exception:
                time.sleep(5)
                continue

            status = result_data.get("status")
            if status == "ready" or status is True:
                return result_data.get("solution", {}).get("token")
            elif status == "error" or result_data.get("error"):
                print(f"[Captcha] Task error: {result_data}")
                return None

            time.sleep(5)

        print(f"[Captcha] Timeout after {timeout}s")
        return None

    def solve_recaptcha(
        self,
        page_url: str,
        sitekey: str,
        timeout: int = 120,
    ) -> Optional[str]:
        """Solve reCAPTCHA v2/v3."""
        create_task_url = f"{self.base_url}/createTask"
        get_result_url = f"{self.base_url}/getTaskResult"

        if self.provider == "2captcha":
            payload = {
                "key": self.api_key,
                "method": "userrecaptcha",
                "googlekey": sitekey,
                "pageurl": page_url,
                "json": 1,
            }
        else:
            payload = {
                "clientKey": self.api_key,
                "task": {
                    "type": "RecaptchaV2Task",
                    "websiteURL": page_url,
                    "websiteKey": sitekey,
                },
            }

        try:
            resp = requests.post(create_task_url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[Captcha] Create task failed: {e}")
            return None

        task_id = data.get("taskId")
        if not task_id:
            print(f"[Captcha] No task ID returned: {data}")
            return None

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                result_resp = requests.post(
                    get_result_url,
                    json={"key": self.api_key, "taskId": task_id} if self.provider == "2captcha" else {"clientKey": self.api_key, "taskId": task_id},
                    timeout=10,
                )
                result_data = result_resp.json()
            except Exception:
                time.sleep(5)
                continue

            status = result_data.get("status")
            if status == "ready" or status is True:
                return result_data.get("solution", {}).get("gRecaptchaResponse")
            elif status == "error" or result_data.get("error"):
                print(f"[Captcha] Task error: {result_data}")
                return None

            time.sleep(5)

        return None


# Global instance
_solver: Optional[CaptchaSolver] = None


def init_captcha_solver(api_key: str, provider: str = "2captcha") -> CaptchaSolver:
    """Initialize the global captcha solver."""
    global _solver
    _solver = CaptchaSolver(api_key, provider)
    return _solver


def get_captcha_solver() -> Optional[CaptchaSolver]:
    """Get the global captcha solver instance."""
    return _solver
