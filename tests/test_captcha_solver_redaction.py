from __future__ import annotations

import logging

import pytest

from app.utils import captcha_solver


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


def _make_session_mock(responses: list[dict] | None = None, raise_on_post: Exception | None = None):
    """Create a mock session for CaptchaSolver."""
    session = type("MockSession", (), {})()
    if raise_on_post:
        def post(*_a, **_kw):
            raise raise_on_post
    else:
        response_queue = list(responses or [])

        def post(*_a, **_kw):
            if response_queue:
                return _Response(response_queue.pop(0))
            return _Response({"error": "no more responses"})
    session.post = post
    return session


@pytest.mark.parametrize("method_name", ["solve_turnstile", "solve_recaptcha"])
def test_captcha_provider_payload_is_not_logged(
    caplog: pytest.LogCaptureFixture,
    method_name: str,
) -> None:
    sensitive_value = "provider-token-should-not-appear"
    session = _make_session_mock([{"error": sensitive_value}])

    solver = captcha_solver.CaptchaSolver(
        "operator-api-key",
        session_factory=lambda: session,
    )

    with caplog.at_level(logging.WARNING, logger="app.utils.captcha_solver"):
        result = getattr(solver, method_name)("https://example.test/", "site-key")

    assert result is None
    assert sensitive_value not in caplog.text
    assert "operator-api-key" not in caplog.text
    assert "Captcha provider response did not include a task ID" in caplog.text


def test_captcha_creation_exception_is_not_logged_verbatim(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_value = "request-token-should-not-appear"
    session = _make_session_mock(raise_on_post=RuntimeError(sensitive_value))

    solver = captcha_solver.CaptchaSolver(
        "operator-api-key",
        session_factory=lambda: session,
    )

    with caplog.at_level(logging.WARNING, logger="app.utils.captcha_solver"):
        assert solver.solve_turnstile("https://example.test/", "site-key") is None

    assert sensitive_value not in caplog.text
    assert "operator-api-key" not in caplog.text
    assert "Captcha task creation request failed" in caplog.text
