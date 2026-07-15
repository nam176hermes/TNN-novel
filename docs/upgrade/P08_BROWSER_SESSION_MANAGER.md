# P08 — Browser session manager

## Scope

P08 contains the existing Playwright browser path without changing source APIs,
adding routes, or calling a live source. `launch_persistent_context` remains the
only persistent browser launch mechanism. Existing Cloudflare handling still
waits for the interstitial and performs one reload attempt.

## Ownership and lifecycle

`BrowserSessionManager` owns one Playwright process, persistent context, and
page. Initialization is lazy on the first fetch. An `asyncio.Lock` serializes
all page control within the session; P07's browser-global limit remains the
outer worker boundary.

The manager restarts the session when any of these conditions is observed at
the next use:

- idle TTL reached (default 300 seconds);
- request ceiling reached (default 100);
- open-page ceiling exceeded (default 1);
- periodic health check detects a closed page or disconnected browser;
- Playwright reports a browser/context/page crash.

The checks are intentionally lazy. P08 does not add an autonomous scheduler
thread. The legacy synchronous wrapper uses one dedicated daemon event-loop
thread solely to preserve Playwright loop affinity across calls; it is not a
job scheduler.

`close_stealth_browser()` closes both async and sync owners. FastAPI calls it
from application lifespan shutdown, and an `atexit` fallback covers CLI use.

## State handling

- Cookie expiry uses Playwright's epoch `expires` value; expired entries are
  not loaded into Playwright or `requests.Session`.
- Cookie writes use a same-directory temporary file, `fsync`, and atomic
  `os.replace`.
- Cookie files are `0600` and the cookie directory/profile directory is `0700`
  where the filesystem supports POSIX permissions.
- Invalid JSON or invalid cookie structures are rotated to a private
  `.corrupt-*` file instead of being reused.
- A profile explicitly reported as corrupt/invalid by Playwright is rotated
  once before a clean persistent-context launch is attempted.
- Cookies, storage payloads, full URLs with query strings, HTML, and chapter
  content are never written to browser failure logs.

## Browser containment

- Persistent contexts launch with `accept_downloads=False`.
- Unexpected popups are closed immediately.
- Initial, intercepted top-level, and final navigation URLs pass through the
  P02 URL policy using an injectable DNS resolver.
- Browser crash recovery retries the same fetch once with a fresh context.
- The current CAPTCHA detection/solver compatibility code is not expanded or
  otherwise changed by P08.

## Compatibility

`StealthBrowser.fetch_with_stealth()` delegates to the manager.
`fetch_with_stealth_sync(url, timeout)` retains its HTML-returning signature
and delegates to the shared sync runtime. Callers do not create or stop a
Playwright process for every chapter anymore.

## Verification

- Mock-only targeted browser/fetch/lifespan suite: `72 passed, 1 warning in
  25.11s`.
- Full backend suite: `909 passed, 2 warnings in 1010.59s (0:16:50)`.
- No real browser or Internet source is used by P08 tests.
