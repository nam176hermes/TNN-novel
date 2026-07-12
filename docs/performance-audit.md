# Performance Audit

## Scope And Measurement Quality

This report combines the measured P1 runtime audit with verified P2A/P2B results and the `2026-07-11` runtime regression pass. Canonical performance numbers come from isolated WSL Linux filesystem fixtures. Current `/mnt/c` test durations are reported only as environment evidence.

## Backend Route Findings

- Most isolated P1 read routes were below 100 ms.
- P2A reduced normal DB connection setup from `11.921 ms` median to `0.035 ms`.
- P2A reduced the 59-book translated-library route from `645-739 ms` to `5.188 ms` median and bounded the query/connection count at 1/1.
- P2B reduced the 120-chapter authenticated import route from approximately `5.62 s` to `144.083 ms` median with real glossary follow-up.
- P2B's transaction-focused 120-chapter service median was `24.724 ms`; real post-commit glossary work increased the service median to `149.771 ms`.
- Export creation measured approximately `94-106 ms` median on isolated fixtures.

## Current Backup Regression

- P1 measured synchronous backup creation at approximately `11.4-17.5 s` on a small fixture.
- Current `GET /api/system/backups` exceeded a 20-second client timeout against the canonical backup directory.
- Root cause: `scripts.ops.list_backups()` calls `read_backup_manifest()` for every archive. When a sidecar is absent, the function opens and scans the compressed archive to extract `manifest.json`.
- The canonical backup directory has two archives (`9.2 MB`, `188.7 MB`) and no sidecar manifests.
- User impact: the status/settings view can remain blocked while merely listing backups; backup creation also remains synchronous.
- Priority: P1 correctness/operability. Add sidecar repair/fallback bounds first, then implement the already-designed job-backed backup workflow.

## Frontend Bundle

| Asset | Raw | Gzip | Assessment |
|---|---:|---:|---|
| Main entry | 341.96 KB | 106.78 KB | Acceptable but broad app orchestration remains eager |
| Global CSS | 188.78 KB | 32.26 KB | Large global payload and maintenance hotspot |
| Reader route | 181.73 KB | 49.54 KB | Largest route chunk; optional tools are bundled together |
| Import route | 49.70 KB | not separately recorded | Reasonable transfer size; responsibility split is primarily maintainability-driven |

Route-level lazy loading works. A broad dependency upgrade is not justified by bundle evidence.

## Browser Runtime

- Isolated API process start to health/readiness was approximately `971 ms` in P1.
- P1 login content appeared in `91-161 ms`; authenticated useful shell took `830-844 ms`.
- Warm major-route navigation was generally `143-160 ms` with the audit settle allowance.
- The current synthetic browser pass produced no console errors and no measured horizontal overflow at `1440x1000`, `390x844`, or `360x740`.
- Current route screenshots confirm the main shell, library, import, jobs, sources, glossary, providers, status, and export surfaces render.
- The current browser harness switched Reader/Export too quickly in one sequential pass and captured Suspense/stale status content. Standalone export verification succeeded; those two 5-second sequential values are invalid and are excluded from performance conclusions.

## Reader

- Reader route chunk: `181.73 KB` raw, `49.54 KB` gzip.
- P1 normal open and chapter switch were below one second locally.
- QA mode measured `102-599 ms`; the long fixture reached approximately `5,182 DOM nodes`.
- Duplicate Reader requests and full QA DOM expansion remain measurable risks.
- Text is not blocked on audio/dictionary completion, which is the correct dependency direction.
- Virtualization is not justified for normal chapters. Progressive QA rendering or long-chapter thresholds should be tested before introducing virtualization.

## Import

- One 4.9 MB chapter was approximately `0.80 s` end-to-end in the P1 path; preview itself stayed under approximately `0.45 s`.
- Before P2B, 120 small chapters took `5.62 s` despite a 96 KB payload.
- After P2B, the route median was `144.083 ms`, with one connection, one transaction/commit, and one bounded duplicate query.
- The existing 5 MB text limit remains acceptable for this private operator app. Structure and chapter count mattered more than bytes before P2B.
- Server-side preview sessions and chunked upload are not currently justified. Reconsider only after measuring larger approved limits or browser memory pressure.

## TTS And Audio

- Fixture normalization/chunking overhead is small.
- Three complete fixture runs, each producing two MP3 chapters and one M4B, took `6.89`, `6.91`, and `7.09 s`; all 9 checks passed.
- Merge cost scales with file/chunk count and ffmpeg startup.
- Fixture M4B was valid media but lacked chapter markers.
- These measurements do not predict provider synthesis speed.

## Database And Storage

- SQLite integrity and foreign keys are healthy.
- Existing chapter/job indexes were effective in P1/P2A query plans.
- The largest logical DB consumers were translation-memory fuzzy data, translation cache, operational events, auth sessions, chapters, and QA reports.
- `operational_events` has 16,396 rows and no demonstrated retention ceiling.
- Filesystem metadata drift makes thousands of content paths unusable through the current root, even though files exist after deterministic remapping. This is a correctness blocker, not a raw storage-performance issue.

## WSL Filesystem Effect

Prior controlled comparison found `/mnt/c` materially slower for frontend build, SQLite, Python file operations, and lazy imports. Development and benchmark work should run from a Linux filesystem checkout, with Windows storage used for reviewed backups or access as needed.

## Directional Targets

| Flow | Current evidence | Target | Status |
|---|---|---|---|
| Normal DB connection | 0.035 ms median | materially below prior 11.921 ms | Met |
| 59-book library | 5.188 ms median | under 200 ms local | Met |
| 120-chapter commit | 144.083 ms route median | under 1.5 s local | Met |
| Normal authenticated page | usually under 1 s isolated | under 2 s local | Met |
| Reader normal chapter | under 1 s local | under 1 s after API | Met |
| Reader long QA | up to 599 ms, 5,182 nodes | no visible long freeze | Needs improvement |
| Backup list | over 20 s with legacy archives | under 250 ms warm | Not met |
| Backup create request | 11.4-17.5 s synchronous | quick 202 job response | Not met |

## Recommended Order

1. P0: migrate stale artifact paths safely on a copied DB, then controlled operator DB migration with backup and rollback.
2. P1: make backup listing metadata-only and backup creation job-backed.
3. P1: remove duplicate Reader request ownership and progressively render heavy QA.
4. P2: split Reader optional tools and CSS by feature after behavior tests are stable.
5. P3: formal low-end Android and WAN measurements.
