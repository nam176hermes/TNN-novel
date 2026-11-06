# Methodology, Safety, and Evidence

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Order used

1. Live user experience.
2. Browser and network evidence.
3. API and runtime evidence.
4. Source explanation.
5. Tests and data-integrity checks.
6. Scoring and repair workstreams.

This order prevented green tests or HTTP 200 responses from overriding visible defects.

## Production boundary

Production was treated as read-only. No import, translation, TTS, export, backup creation, restore, retry, cancel, provider test, or content mutation was triggered. Login created expected session and operational metadata. Reader progress remained `3 -> 3`; jobs remained `332 -> 332`; import jobs remained `0 -> 0`. [Source] `/tmp/novel-tnn-live-audit/controller/browser-fresh/db-before.json`; `/tmp/novel-tnn-live-audit/controller/browser-fresh/db-after.json`

The fresh restore used an isolated `/tmp` drill root, a read-only backup mount, `--network none` during extraction and validation, and a temporary status receipt. It did not update the production restore-status file. [Source] `scripts/production_restore_drill.sh`; `/tmp/novel-tnn-live-audit/restore-drill.log`

## Evidence labels

- `REPRODUCED`: observed in a fresh live or isolated run.
- `CODE_EVIDENCE`: implementation or test structure explains behavior.
- `SUSPECTED`: credible risk without enough runtime proof.
- `NOT_TESTED`: explicitly outside the safe test boundary.

Historic reports were context only. Fresh evidence controlled this verdict.

## Viewports

- Mobile: `360x740`, `390x844`, `412x915`.
- Desktop: `1366x768`, `1440x1000`.

## Sensitive-data handling

Credentials were read only from operator-owned files and never printed. Reports omit private book titles, chapter text, cookies, tokens, API keys, raw source payloads, and absolute user-content artifact paths.
