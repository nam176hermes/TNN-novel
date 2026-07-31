# Workstream 2 — Mobile Reader Correctness and Offline Behavior

## Result

**GO for operator review and controlled integration.** READ-001, READ-002, and PERF-002 are fixed on the dedicated branch. No production checkout, data, container, configuration, ingress, paid provider, or GPU workload was changed.

This branch is not deployed and is not merged into the main worktree.

## Baseline

- Worktree: `/home/thenam176/Novel-TNN-worktrees/ws2-mobile-reader-correctness`
- Branch: `repair/ws2-mobile-reader-correctness`
- Baseline commit: `2594fd121ec46de718e86991d6460d5e27874c91`
- Baseline relationship: Workstream 1 implementation and report were present before Workstream 2 began.
- Runtime used for verification: Python 3.11.15, Node 22.23.0, npm 10.9.8.
- Test isolation: `NOVEL_PIPELINE_IGNORE_DOTENV=1`; mutable tests used pytest temporary directories/fixture databases. The external production env was only checked for metadata/required keys and was not sourced or printed.

The audit reproduction baseline was:

- raw/source returned 3,701 characters, including 2,783 CJK characters, while Raw, Raw compact, and Split remained disabled;
- an offline mobile reload produced a blank page at 360×740, 390×844, and 412×915;
- four rapid chapter transitions generated 23 requests, including seven translation requests.

## Root causes

### READ-001 — current chapter capabilities were not owned with current chapter data

Reader content and capability decisions crossed App and Reader component boundaries. Source, translation, rich content, and QA did not share one canonical chapter identity. A late or mismatched resource state could therefore leave the visible translation on the current chapter while source-dependent controls reflected another state.

### PERF-002 — duplicate initiators and missing stale-response protection

Current-chapter text and QA loads had multiple initiation paths. Requests did not have a single in-flight identity contract, and stale responses were not consistently canceled or rejected before state writes.

### READ-002 — app state recovery existed without a complete offline boot contract

The previous PWA behavior had four gaps:

1. no bounded resume metadata identified the last cached chapter at boot;
2. an offline refresh-token failure could clear an otherwise locally readable session;
3. manual offline cache did not persist raw/source text or content revision;
4. the service worker cached HTML shell routes but did not precache the production build's hashed JS/CSS assets, so offline navigation could return HTML that could not boot React.

## Ownership map after the repair

| State/resource | Canonical owner | Contract |
|---|---|---|
| Current book and chapter selection | `useLibrary` | One selected `book_id`/`chapter_id`; offline resume can restore a synthetic selected chapter without loading the network library first. |
| Canonical Reader chapter identity | `useReaderChapterData` | `${book_id}:${chapter_id}` is shared by text and QA resources. |
| Source, translation, rich HTML | `useChapterText` through `useReaderChapterData` | One active request key; duplicate loads reuse the promise; superseded requests are aborted; request generations reject late writes. |
| QA | `useQa` through `useReaderChapterData` | One active request per canonical chapter key; stale QA responses cannot overwrite current QA. |
| Reader render capabilities | `ReaderView` from canonical text props | Raw requires current source; Split and Raw compact require current source plus current translation; unavailable persisted modes fall back safely. |
| Dictionary/glossary and X-Ray | `ReaderView`, keyed by selected book/chapter | Optional resources remain independent and do not block translation rendering. |
| Audio capability/playback | `useReaderAudio` in `ReaderView` | Optional and keyed by the selected book/chapter; unchanged by this workstream. |
| Offline content/cache metadata | `useReaderOfflineCache`, `readerCache`, and `readerOfflineCache` | Explicit manual caching only; revision-aware chapter payload; private API responses are not placed in Cache Storage. |
| Offline boot pointer | `readerResume` | Versioned, bounded metadata only; no source, translation, token, or secret is stored in the resume record. |
| Reader preferences | Existing Reader preference stores | Preserved across logout; private content, progress, marks, dictionaries, manifests, resume metadata, IndexedDB chapter/assets/audio are cleared on logout. |

## Request timeline and measurements

### Before

Audit measurement for initial/current Reader activity plus four rapid transitions: **23 API requests**:

- 7 translation;
- 4 source;
- 4 QA;
- 4 dictionary;
- 4 reader sync.

### After

The canonical chapter-data regression performs the initial load plus four transitions with exactly **15 canonical resource requests**:

- 5 source;
- 5 translation;
- 5 QA;
- 0 duplicate source/translation/QA requests;
- rich content remains optional and is not requested when the chapter has no rich-content revision.

This is a 35% reduction from the audit's 23 total calls for the measured flow. Dictionary and sync remain optional ReaderView-owned resources; they are intentionally outside the new chapter-data controller and were not misrepresented as removed.

Stale-response tests verify:

- superseded source/translation requests are aborted;
- a previous chapter's late response cannot replace the current chapter;
- duplicate current loads reuse the active request;
- stale QA responses cannot replace the current report.

No stable wall-clock comparison was claimed because the E2E backend is mocked and does not represent provider or public-ingress latency.

## Raw and split contract

| Current chapter resources | Translation | Raw | Split | Raw compact |
|---|---:|---:|---:|---:|
| Source + translation | enabled | enabled | enabled | enabled |
| Source only | fallback to Raw | enabled | disabled | disabled |
| Translation only | enabled | disabled with reason | disabled with reason | disabled with reason |
| Neither | empty/error state | disabled | disabled | disabled |

A persisted mode that is not supported by the new chapter falls back to a valid mode instead of displaying stale or blank content.

## Offline policy

### Cache Storage

The service worker caches only:

- app-shell navigation files;
- production hashed `/assets/` JS/CSS referenced by `index.html`;
- declared public PWA icons/manifest/offline fallback;
- same-origin public static destinations.

It explicitly bypasses private paths including `/api/`, `/covers/`, `/book-assets/`, `/exports/`, `/backup`, `/backups/`, and `/data/`. The Playwright test verifies that a protected translation API response is absent from Cache Storage.

### Private Reader data

Private chapter text, raw/source, rich HTML, assets, audio, dictionary packs, manifests, and resume state use the existing Reader IndexedDB/local stores and are written only through explicit offline actions. Manual chapter/book caching now stores raw source when available. Source failure is optional and cannot prevent the translation from being cached.

Cached rich content carries a revision key. A selected chapter with a different current revision rejects the stale cached chapter.

### Offline boot and logout

- Offline reload renders the application shell and restores the last explicitly cached chapter.
- If no usable chapter cache exists, the Reader exposes an explicit offline state instead of a blank DOM.
- Network/auth failures are not treated as an expired session solely when the browser is offline and a local access token still exists.
- Logout attempts private Reader cache deletion and server/session logout concurrently. Successful logout clears private Reader data while preserving non-content display preferences.

## Files changed

Primary implementation:

- `web/src/App.tsx`
- `web/src/api/client.ts`
- `web/src/components/ReaderView.tsx`
- `web/src/components/reader/ReaderQuickControls.tsx`
- `web/src/components/reader/ReaderSettingsSheet.tsx`
- `web/src/components/reader/useReaderOfflineCache.ts`
- `web/src/state/useLibrary.ts`
- `web/src/state/useReaderChapterData.ts`
- `web/src/state/useChapterText.ts`
- `web/src/state/useQa.ts`
- `web/src/state/useSession.ts`
- `web/src/state/readerCache.ts`
- `web/src/state/readerOfflineCache.ts`
- `web/src/state/readerPrivateData.ts`
- `web/src/state/readerResume.ts`
- `web/src/state/serviceWorker.ts`
- `web/public/reader-offline-sw.js`
- `web/playwright.config.ts`

Related Vitest and Playwright files were updated or added beside these modules.

## Commits

1. `75179f6` — `fix(reader): centralize chapter data ownership`
2. `4a90765` — `fix(reader): prevent stale and duplicate chapter requests`
3. `e075175` — `fix(reader): restore raw and split mode availability`
4. `28677db` — `fix(pwa): provide safe offline reader reload`
5. `d0f8577` — `test(pwa): verify production offline reload`

The last commit also closes the browser-discovered shell-asset gap by precaching hashed production assets and changes Playwright from the dev server to a production build/preview. It is retained separately because the first browser run demonstrated that application-state tests alone did not prove a bootable offline shell.

## Verification evidence

Targeted Reader/PWA suite:

- 12 Vitest files, 179 tests passed after the final offline changes.
- Service worker focused suite: 3 files, 10 tests passed.

Complete frontend:

- `npm --prefix web test`: **85 files, 756 tests passed**.
- `npm --prefix web run typecheck`: passed.
- `npm --prefix web run build`: passed; Vite transformed 1,855 modules.
- `npm --prefix web run test:e2e -- --project=chromium`: **10 Playwright tests passed** against a production build/preview.
- Mobile checks include 360×740, 390×844, and 412×915 with no horizontal overflow.

Complete mandatory gate:

```text
PYTHON_BIN=/home/thenam176/Novel-TNN/.venv/bin/python \
NOVEL_PIPELINE_IGNORE_DOTENV=1 \
NOVEL_PIPELINE_PRODUCTION_ENV_FILE=/home/thenam176/.config/novel-tnn/production.env \
scripts/verify.sh
```

Result:

- Python compile: pass;
- shell syntax: pass;
- environment validation: pass without sourcing or printing secrets;
- lint/typecheck: pass;
- backend: **1,161 tests passed**, 2 dependency deprecation warnings;
- pip consistency: pass;
- frontend: **756 tests passed**;
- production build: pass;
- aggregate exit status: 0.

The first worktree run exposed one environment-only failure because a backup fixture invokes `.venv/bin/python` by relative path. An ignored worktree symlink to the project's existing locked Python 3.11 venv resolved it; the failed test then passed alone and in the complete rerun.

Read-only runtime probes after verification:

- local `/health`: HTTP 200;
- local `/api/ready`: HTTP 200.

`git diff --check` passed. No runtime/Docker files changed, so no Docker rebuild was required. No public probe was performed because nothing was deployed.

## Security, data, and rollback review

- No production data, schema, artifact path, job state, browser-challenge behavior, TTS behavior, secrets, or ingress changed.
- Service worker private-route exclusions remain explicit and tested.
- Resume metadata excludes chapter content and credentials.
- Optional source failure cannot corrupt or block a cached translation.
- Rollback is code-only: revert/cherry-pick back the Workstream 2 commits and rebuild the frontend. Service worker cache version `v5` causes old shell/runtime caches to be removed during activation.
- Because the Workstream 2 branch is based on the Workstream 1 actual branch while the main worktree contains rebased Workstream 1 hashes, controlled integration should cherry-pick only the Workstream 2 commits rather than merge duplicate Workstream 1 history blindly.

## Remaining limitations

1. First-ever PWA installation needs the service worker to activate/control a page before offline navigation can work. The E2E test performs one online reload after worker readiness, matching the standard first-install lifecycle.
2. Manual whole-book caching has operator-visible cleanup but no automatic LRU/size quota beyond browser storage limits. This is a P2 retention enhancement, not a READ-002 blocker.
3. Offline authorization is appropriate for the current private single-operator model but is not a multi-user encrypted cache namespace. Workstream 3 must preserve logout clearing and the offline boot test while changing token storage.
4. Browser storage/IndexedDB deletion is best effort when the browser itself denies storage access; server/session logout still proceeds.
5. Dictionary, sync, X-Ray, and audio remain optional owners in ReaderView. They no longer own source/translation/QA and do not block core text, but broader Reader decomposition is reserved for Workstream 6.
6. Memory trend was covered indirectly by cancellation/cleanup tests and browser smoke tests; no long-duration heap profile was claimed.

## Workstream 3 recommendation

**GO after operator review and controlled integration of Workstream 2.** Workstream 3 may proceed in a new dedicated worktree after the main branch contains these commits and its own baseline verification is green.

Workstream 3 must treat these as non-regression gates:

- offline cached Reader reload remains functional while refresh-token storage changes;
- logout still clears private Reader caches;
- no browser-readable persistent refresh token remains;
- CSRF/session migration tests cover offline and multi-tab behavior;
- production deployment stops at the explicit approval gate.
