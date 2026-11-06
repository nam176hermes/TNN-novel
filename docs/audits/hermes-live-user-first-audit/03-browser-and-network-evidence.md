# Browser and Network Evidence

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Browser session behavior

Refresh uses an HttpOnly cookie. The access token is session-scoped, and legacy local-storage token state is cleared. CSRF uses a double-submit cookie contract. [Source] `web/src/state/session.ts`; `app/mobile_api/session_cookies.py`; authenticated browser observations

## Security headers

Fresh public responses returned CSP, HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, a restrictive permissions policy, and strict referrer policy. An unauthenticated `/api/books` request returned `401` with `private, no-store`. A hostile-origin preflight returned `400` with no allowed origin. [Source] fresh urllib probe on 2026-07-24; `app/mobile_api/main.py`

## PWA two-path control

- First-session path without an online controlled reload: blank after offline reload.
- Correct warmed path with one online reload after service-worker readiness: Reader content and offline indicator render.

This control separates a lifecycle defect from a general offline-cache failure. [Source] `/tmp/novel-tnn-live-audit/controller/browser-fresh/pwa-valid-no-route-result.json`; `/tmp/novel-tnn-live-audit/controller/browser-fresh/pwa-valid-online-reload-result.json`

## Console noise

Cloudflare Insights injection conflicts with the application CSP, creating console noise while the policy correctly blocks the beacon. See OPS-CSP-009.
