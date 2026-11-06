# Real-user mobile review


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Coverage

The isolated production image was exercised at 360x740, 390x844, and 412x915. Dashboard, Library, Jobs, Reader, and mobile navigation were captured with redacted screenshots. All routes opened, horizontal overflow was zero, and browser page-error arrays were empty. [Source: evidence/browser-summary.json] [Source: evidence/screenshots/]

## What works

- Login and protected-shell handoff worked before the staging throttle was reached.
- Dashboard, Library, Jobs, and Reader were reachable at all required widths.
- Visible sampled controls met the touch-target policy.
- Reader removed the global bottom navigation from the reading surface.
- Service-worker control and offline cache actions were available.
- No blank Reader surface followed first-session or warmed offline reload.

## What fails or remains weak

- The Jobs and Dashboard screenshots show lower content entering the fixed-navigation region at short heights. This reopens `UX-MOB-007` as bounded P2 debt.
- Reader settings does not move initial focus into the dialog and does not restore focus to its trigger on close.
- The install prompt overlaps the login action area at a short desktop-height viewport.
- A repeated expected refresh 401 is logged as console error noise in fresh unauthenticated contexts.

## Real-user verdict

**GO_WITH_LIMITATIONS.** Touch use is viable for the private operator. Keyboard accessibility and bottom safe-area behavior require repair before a higher mobile score. Public production was observed before source inspection; mutation-capable journeys were kept on staging.
