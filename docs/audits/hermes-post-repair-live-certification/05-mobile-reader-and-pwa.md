# Mobile Reader and PWA


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Reader evidence

Reader opened at every required viewport with one visible surface, zero horizontal overflow, zero page errors, and 327 to 479 initial DOM nodes. Two rapid chapter changes ended with one surface and no loading residue. Requests were 2 source, 2 QA, and 3 translation reads, which proves bounded behavior but leaves one duplicate translation read. [Source: evidence/browser-summary.json]

The custom audit did not certify all mode buttons because its exact accessible-name selectors did not resolve them. The release E2E independently passed Vietnamese rendering and current-chapter Raw and Split availability. Raw compact and QA behavior retain source and component-test evidence but are not claimed as complete live mode-matrix certification. [Source: evidence/test-summary.json]

## PWA first-session path

The isolated production image met the required state before offline success:

- service worker controlled the client;
- cache action was present and enabled;
- shell and runtime cache names existed;
- one offline badge was shown;
- immediate offline reload returned the Reader shell, one Reader surface, and cached text.

First-session E2E passed independently. [Source: evidence/browser-summary.json] [Source: evidence/test-summary.json]

## PWA warmed path

The warmed path returned the Reader shell, one Reader surface, and cached text after disconnect and reload. Warmed E2E passed independently. [Source: evidence/browser-summary.json]

## Lifecycle limitations

The final isolated adversarial run completed with process exit 0, zero harness errors, and all seven explicit assertions true. A corrupted chapter entry and a shell-only state retained the Reader shell and one readable surface with zero page errors. Logout cleared all Reader localStorage keys and reduced IndexedDB cached chapters from 1 to 0. Cache revision cleanup removed stale v1 Reader caches while preserving an unrelated cache. Initial unauthenticated `/api/auth/refresh` HTTP 401 responses were expected bootstrap denials, not failed authenticated requests. [Source: evidence/pwa-adversarial.json]

The chapter-only state with both shell caches deliberately removed could not reload offline and returned `net::ERR_FAILED`. This is bounded expected behavior because IndexedDB chapter content cannot bootstrap the application without the shell. Public-production fresh-profile mutation remained excluded.

## Verdict

**GO_WITH_LIMITATIONS.** The previous first-session P1 and the isolated lifecycle matrix are verified fixed. Remaining limitations are public fresh-profile mutation, one duplicate translation request, incomplete custom mode locators, and settings-dialog focus debt.
