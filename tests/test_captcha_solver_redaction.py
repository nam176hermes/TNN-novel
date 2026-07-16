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


@pytest.mark.parametrize("method_name", ["solve_turnstile", "solve_recaptcha"])
def test_captcha_provider_payload_is_not_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    method_name: str,
) -> None:
    sensitive_value = "provider-token-should-not-appear"
    monkeypatch.setattr(
        captcha_solver.requests,
        "post",
        lambda *_args, **_kwargs: _Response({"error": sensitive_value}),
    )
    solver = captcha_solver.CaptchaSolver("operator-api-key")

    with caplog.at_level(logging.WARNING, logger="app.utils.captcha_solver"):
        result = getattr(solver, method_name)("https://example.test/", "site-key")

    assert result is None
    assert sensitive_value not in caplog.text
    assert "operator-api-key" not in caplog.text
    assert "Captcha provider response did not include a task ID" in caplog.text


def test_captcha_creation_exception_is_not_logged_verbatim(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_value = "request-token-should-not-appear"

    def raise_error(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(sensitive_value)

    monkeypatch.setattr(captcha_solver.requests, "post", raise_error)
    solver = captcha_solver.CaptchaSolver("operator-api-key")

    with caplog.at_level(logging.WARNING, logger="app.utils.captcha_solver"):
        assert solver.solve_turnstile("https://example.test/", "site-key") is None

    assert sensitive_value not in caplog.text
    assert "operator-api-key" not in caplog.text
    assert "Captcha task creation request failed" in caplog.text
