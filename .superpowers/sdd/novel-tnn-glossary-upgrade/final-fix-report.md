# Novel-TNN glossary upgrade final-fix report

Date: 2026-08-30

## Scope and baseline

- Worktree: `/home/thenam176/Novel-TNN/.worktrees/glossary-final-fixes`
- Branch: `codex/glossary-final-fixes`
- Authorized base: `d9a93a19ac6ddf1b1e65062cab2635b5b68794d2`
- Final production/browser-driver SHA under certification: `b4a94dcc974737f63b704e43712a3b90f39a2850`
- No dependency, schema, CI, deployment, remote Git, operator database, or live/provider mutation was performed.

This was the single authorized final-fix wave. It closes C1, I1, I2, I3, I4, and all three minor findings without changing the public API schema or the unbound background/service behavior.

## Implemented fixes

### C1: centralized owner authorization

- Added repository ownership and term-participant predicates.
- Bound API-created `GlossaryService` instances to the authenticated `user_id` and configured admin identity.
- Direct `all`/`global` access and global-term create, mutation, import, and export now require the admin identity.
- Book/effective list, search, detail (including evidence/history), create, update, bulk, merge, import, export, archive, restore, extraction settings, and re-extraction require exact book ownership by `user_id`.
- Missing and unauthorized glossary resources use the same `404 {"detail":{"code":"not_found"}}` boundary.
- Bulk, merge, and import authorize every participant before entering the write path; mixed-owner requests do not partially mutate.
- Unbound `GlossaryService`, `from_db_path`, pipeline, and legacy `object.__new__` internal callers retain trusted service/background behavior. Class-level access defaults make this explicit even when `__init__` is bypassed.
- Owned effective views continue inheriting matching global terms.

### I1: bounded private history evidence

- `before_json` and `after_json` now retain exact bounded audit metadata for type/category, genre/gender/mode, priority/confidence, occurrence/chapter/first-seen/evidence counts, scope/owner/book identifiers, timestamps, review/status/archive state, approval/lock state, and version.
- Content-bearing fields (`source_term`, `target_term`, `variants`, `notes_vi`, `source_context`, and `alternatives`) are represented in snapshots only by per-field domain-separated SHA-256, length, and presence metadata.
- Legacy `glossary_history.source_term` and `target_term` columns remain unchanged for compatibility; raw free-form content is not duplicated into JSON snapshots.
- Extraction reconciliation captures evidence counts before evidence deletion/update, and merge history captures exact pre/post evidence counts after evidence movement and alias creation.

### I2: selected styleguide genre

- The effective resolver now passes the chosen style profile genre to `_styleguide_rows`.
- Genre-specific terms are mutually exclusive while explicitly genre-neutral rows remain available.
- The corrected resolver feeds translate mappings, prompt terms, Reader dictionary packs, deterministic QA, fingerprints, and cache identity consistently.
- The legacy default-profile seed assertion now verifies that cross-genre terms are absent rather than expecting the old all-genre leak.

### I3: immutable merge/import preview context

- Merge previews bind to book, selected conflict/canonical/duplicates, participant book/version data, and the visible glossary revision.
- Import previews bind to book, exact text, parsed items, policy, and glossary revision.
- Relevant book/control/revision changes synchronously hide and invalidate accepted previews.
- Deferred stale success/error responses cannot restore an apply action.
- Apply paths compare the accepted binding with the current binding and refuse stale execution.

### I4: mutation/query race

- Mutation callbacks capture the exact book, enabled state, query token, and generation at mutation start.
- Completion uses the current refresh function only when that exact context is still current.
- A deferred mutation therefore cannot abort a newer search/scope/page request or repaint old rows.

### Minor fixes

- A blank CSV `scope_book_id` for book scope is rejected before numeric conversion.
- Glossary status filters now use ordinary grouped buttons with `aria-pressed`, not incomplete ARIA tabs.
- The mobile second-column generated label now targets `td:nth-child(2)`.
- The self-contained browser journey was updated to query the pressed-button contract, wait for a cleared queue request before previewing, and scroll the mobile merge action into the unobstructed viewport before a normal click.

## Genuine RED and focused GREEN evidence

Backend commands below used `NOVEL_PIPELINE_IGNORE_DOTENV=1` and isolated `/tmp` test paths. Frontend commands ran from the repository root through `npm --prefix web test -- ...`.

| Cluster | Genuine RED | Focused GREEN |
| --- | --- | --- |
| C1 | `pytest -q -s tests/test_glossary_owner_authorization.py` -> 4 failed: foreign/global reads and creates returned success; mixed bulk mutated; mixed imports were accepted. | Same file -> 4 passed, including direct all/global enumeration, global export/mutation/import, evidence/history detail, all single mutation families, and mixed-owner atomic failures. |
| I1 | Phase 1 bounded-history test plus Phase 5 stale-reconciliation test -> 2 failed: categorical metadata was absent and evidence reconciliation counts were not auditable. | Same two nodes -> 2 passed; raw sentinel content absent and exact `2/1/1 -> 0/0/0` occurrence/chapter/evidence reconciliation recorded. |
| I2 | `test_selected_genre_filters_styleguide_across_runtime_consumers_and_cache_identity` -> 1 failed because the `tien_hiep` result contained the `kiem_hiep` term. | New cross-consumer test plus existing Reader styleguide test -> 2 passed. |
| I3 | `GlossaryStyleView.test.tsx` with two deferred preview tests -> 2 failed, 11 passed; stale merge/import responses restored apply controls after selection/text/book/revision changes. | Component file -> 13 passed. |
| I4 | `useGlossary.test.tsx` with deferred mutation followed by search/scope/page change -> 1 failed, 10 passed; the newest request's `AbortSignal` was aborted. | Hook file -> 11 passed; newest signal remained live, no third stale query ran, and the newest rows won. |
| Minors | ReviewQueue + StyleView parser + PWA CSS tests -> 8 failed, 18 passed. Three root assertions were red; the incorrect tab-role test left fake timers active and caused five same-file cascades. | The same three files -> 26 passed. |

The first cumulative glossary backend run was `129 passed, 6 failed`. All six failures were expected contract/fixture drift: two API tests used nonexistent book IDs, three import round trips omitted destination books, and one bulk test expected the old distinguishable `409 term_not_found`. After creating owned destination books and adopting the required indistinguishable `404`, the seven focused regressions passed and the cumulative glossary selection completed as `135 passed, 87 warnings`.

The complete frontend suite then passed as `87` files and `802` tests. The production frontend build transformed `1858` modules successfully.

## Canonical verification evidence

### Environment preflight and full-suite debugging

The first literal committed-tree command:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/verify.sh
```

failed closed at the environment gate because the isolated worktree had no `.env`, `data/pipeline.db`, `data`, or `data/logs` (four expected preflight errors). For verification only, an ignored credential-free comment `.env`, ignored worktree `data/logs`, and a symlink to a freshly initialized `/tmp` SQLite database were supplied. No operator file was copied.

The next full run reached `1452 passed, 8 failed, 477 warnings`. Seven failures showed that trusted tests constructing `GlossaryService` with `object.__new__` did not have access fields; one legacy test still expected all styleguide genres from the selected default profile. Class-level unbound defaults and the corrected genre assertion resolved these causes. The exact eight failures then passed, and the owner/genre focused set remained green (`12 passed` and `6 passed`, respectively).

On committed production SHA `6abf0f4fc80743e63f0d13b58ebe13db09bd2da0`, the literal canonical command exited `0`:

- Python compile: pass.
- Shell syntax: pass.
- Environment: pass using only the disposable ignored prerequisites.
- Lint and frontend typecheck: pass.
- Backend: `1460 passed, 477 warnings in 472.41s`.
- Python dependency consistency: pass.
- Frontend: `87` files, `802` tests in `31.49s`.
- Frontend production build: `1858` modules, built in `1.30s`.

The later production-tree changes only corrected the tracked browser certification driver. A final canonical rerun is performed after this report commit so the returned handoff can cite the final HEAD directly.

`git diff --check` passed before each production commit and before the report.

## Browser certification

Command:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 \
PHASE6_BROWSER_ARTIFACT_DIR=<fresh-/tmp-directory> \
scripts/certify_glossary_phase6_browser.sh
```

The first post-UI-commit journey exposed the obsolete `role=tab` driver selector. After aligning it with `role=group`/`aria-pressed`, desktop passed and mobile exposed a pending cleared-search query invalidating the preview while the fixed navigation bar covered the minimally scrolled apply button. The driver was corrected to wait for that exact queue response and scroll the normal button click to viewport center. One intermediate run exposed that Playwright CLI's response callback lacked the global `URL` constructor; a portable raw URL predicate replaced it.

Final certification on `b4a94dcc974737f63b704e43712a3b90f39a2850` exited `0`:

- `PHASE6_BROWSER_CERTIFICATION_OK fixtures=2 rows_each=10000 viewports=desktop:1440x900,mobile:390x844`.
- Both viewports completed create/edit/approve/lock, two-row bulk approval, conflict preview/apply, import preview/apply, JSON export parsing, archive/restore, deterministic re-extraction, and keyboard activation.
- Both exported `10002` rows before re-extraction and verified the `10007` post-extraction total and five expected extracted sources.
- Both reported `httpFailures: []`.
- Desktop initial/final width was `1440/1440`; mobile was `390/390`; both reported no horizontal overflow.
- Keyboard focus was visible on the expected `SUMMARY`, and Enter activated it in both viewports.

## Changed files

Production and service boundaries:

- `app/database/glossary_repository.py`
- `app/database/glossary_resolver.py`
- `app/mobile_api/routers/books.py`
- `app/mobile_api/routers/glossary.py`
- `app/mobile_api/services/glossary_service.py`

Frontend and certification:

- `web/src/components/GlossaryStyleView.tsx`
- `web/src/state/useGlossary.ts`
- `web/src/styles/features.css`
- `scripts/glossary_phase6_browser_journey.js`

Tests:

- `tests/test_database_db.py`
- `tests/test_glossary_owner_authorization.py`
- `tests/test_glossary_phase1_state.py`
- `tests/test_glossary_phase2_resolver.py`
- `tests/test_glossary_phase4_bulk_import.py`
- `tests/test_glossary_phase5_extraction.py`
- `web/src/components/GlossaryReviewQueue.test.tsx`
- `web/src/components/GlossaryStyleView.test.tsx`
- `web/src/pwaMobileStyles.test.js`
- `web/src/state/useGlossary.test.tsx`

## Cleanup, boundaries, and residual concerns

- The ignored `.env`, ignored `data` tree, synthetic SQLite database, and all browser artifact directories created by this wave were removed and moved to trash where supported.
- No live network provider, paid API, operator database, production runtime, deploy, push, PR, or other remote mutation was used.
- No new dependency, lockfile, schema, migration, CI, or deployment configuration was added.
- The canonical suite still emits pre-existing Passlib `crypt` deprecation and short test HMAC-key warnings; these are warnings, not failures, and were not broadened into this scoped fix.
- The browser starts from an unauthenticated session, so its expected pre-login refresh request logs one `401` before the journey attaches its post-login HTTP failure collector. Both certified journeys themselves report zero HTTP failures.
