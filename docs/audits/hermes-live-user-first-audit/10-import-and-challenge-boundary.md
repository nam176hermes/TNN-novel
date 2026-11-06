# Import and Protected-Challenge Boundary

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Import evidence

Live Import UI rendered and exposed the staged flow. Isolated E2E covered paste import and translation-job start with mocked APIs. Backend tests cover URL policy, extraction, archive handling, persistence, retries, cancellation, and user-verification contracts. [Source] desktop Import screenshot; Playwright E2E output; backend full-suite output

## Protected legacy behavior

The Playwright persistent browser-session mechanism remains present. Source represents unresolved challenge states as `user_verification_required` where automation cannot safely continue. [Source] `app/utils/stealth_browser.py`; `app/database/import_jobs.py`; related tests

## Audit boundary

No live CAPTCHA, bot-wall bypass, paid solver, proxy, or protected third-party source was attempted. No conclusion is made about current third-party bypass success.

## Risks to preserve during repair

- Do not duplicate jobs across challenge retries.
- Keep cookies, challenge pages, credentials, and raw source payloads out of logs.
- Preserve cancel and lease ownership checks.
- Keep provider and browser configuration isolated from public API responses.

## Verdict

Import contract: **GO_WITH_LIMITATIONS**. Live destructive proof is `NOT_TESTED`; isolated contract coverage is strong.
