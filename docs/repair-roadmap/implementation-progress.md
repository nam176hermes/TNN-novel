# Implementation progress — 2026-10-02

Approved plan: continuous implementation T00–T14 from the current chat. No routine milestone approval pauses; repair technical blockers and continue independent tasks. Production deployment, destructive operations and new production dependencies remain outside the authorization.

## Baseline

- HEAD: `a41cd84dae42b745f196fac90a51356cf896a007`
- Branch: `upgrade-b/00-baseline-and-agent-guidance`
- Existing tracked diff SHA-256: `38ab2b3b92701c7d894e60aad3d6c54b6d478db3cbac7aa49744a7fa3bf4198d`
- Python 3.11.15; Node 22.23.0; npm 10.9.8.
- Existing operator edits are preserved, especially Reader/audio/offline, CSS, configuration and operational tests. No operator database is used.
- Earlier audit results are retained evidence, not fresh implementation validation: backend 1324 passed; frontend 782 passed; E2E 15 passed / 1 skipped. Full verification lacked local environment prerequisites; real provider/GPU quality was unverified.

## Tasks

`DONE` means the software change and required local candidate gates passed. It does not certify production or real-provider translation/voice quality. Continue all independent work while an external qualification prerequisite is absent; never substitute mocked quality evidence for real-provider completion.

| Task | Status | Evidence / remaining work |
|---|---|---|
| T00 baseline/regressions | DONE | Runtime/HEAD recorded; new publication, provider, QA and Xray failures reproduced before fixes |
| T01 safe publication | DONE | Immutable source/translation/HTML/audio; guarded DB publication; shared legacy paths retained; DB-first deletion |
| T02 revision/QA/audio | DONE | Idempotent additive migration; edit/QA/audio revision and hash guards; stale audio refused; versioned stream/cache URLs |
| T03 LLM transport/cache | DONE | One retry owner; malformed/permanent/empty/truncated responses rejected; effective-context cache; balanced default; frozen batch providers/style |
| T04 final QA/full coverage | DONE | Full chunk coverage and final rewrite QA; authoritative FAIL; atomic QA envelope tied to revision; legacy/stale reports excluded from qualified totals |
| T05 import follow-ups | DONE | One connection/two transactions with savepoints; 120/500 chapter benchmarks confirm constant connection/commit counts |
| T06 TTS input/resume | DONE | Immutable manifests, per-chapter child jobs, original-input retry, guarded cancellation and output publication |
| T07 normalizer/cache/audio QA | DONE | Numeric speech before punctuation; actual compressed-audio decoding/QA; QA-passed cache receipts include reference fingerprint |
| T08 F5 worker/deadline | DONE | Persistent process, bounded cancellation/deadline, warm reuse and process GPU lock; injected-runtime tests, no real voice qualification yet |
| T09 PCM/M4B | DONE | One PCM merge/filter/encode; chapter markers; complete-book default, explicit partial manifest; concurrent changes reject output |
| T10 Reader loading | DONE | Translation-first display; source/dictionary/playlist on demand; one bootstrap owner; offline/resume and stale-response guards |
| T11 UX/UI | DONE | Library default, read/listen entry, grouped native controls, Vietnamese audio/quality labels, separate translated-title editor; browser layering/44px hit area regressions fixed |
| T12 bounded refactors | DONE | Selected Reader/import/App ownership and book/import/glossary/user/job repository/service boundaries implemented; fresh refactor candidate revision 3 passed all 10 gates, desktop/mobile E2E and controlled performance checks |
| T13 real quality/performance | PARTIAL / BLOCKED_EXTERNAL | Import/library/Reader/build measurements collected. No usable LLM provider, Torch/F5 runtime or configured model/reference voice/transcript; no real quality claim |
| T14 candidate/recovery | LOCAL_VERIFIED | Fresh refactor candidate revision 3: 1377 backend, 787 frontend, 14 desktop + 2 mobile E2E; all 10 wrapper gates exit 0. Operator DB untouched; real-provider qualification remains blocked in T13 |

## Execution evidence

Append command, exit status, result, log path and invalidation reason when applicable. Logs belong under ignored `work/repo-research/novel-tnn/implementation/`; content and credentials must not be logged.

- Publication: original 3 regressions failed, then all 7 publication/revision cases passed (exit 0). Later atomic QA changes require revalidation at freeze.
- `pytest -q -s tests/test_chapter_publication.py tests/test_database_db.py tests/test_mobile_api_db_logic.py tests/test_mobile_api_import_ebook.py tests/test_import_transaction_performance_contracts.py`: 118 passed, exit 0, 64.32 s, `D.log`. Retained intermediate result; QA/import changes invalidate affected paths.
- `pytest` publication + ebook: 31 passed, exit 0, 24.36 s, `D-ebook.log`. Atomic QA additions require final revalidation.
- Provider integrity: all 5 new cases initially failed; shared transport fixes made them pass. Existing transport expectations updated for permanent errors, empty output rejection and source-aware pronouns.
- QA integrity: all 5 new cases initially failed; all pass in subsequent core run. Core run: 118 passed / 2 failed, exit 1, 36.87 s, `Q-core.log`; failures were additive response expectations and missing test import, subsequently fixed.
- `npm --prefix web run typecheck`: PASS, exit 0, `typecheck.log` (before later UI work).

## Candidate freeze

- Candidate: `/tmp/novel-tnn-candidate-n3avcrwc`; source HEAD remains the baseline above. Runtime dependencies are reused; product source is copied and SHA-256 bound in `work/repo-research/novel-tnn/implementation/candidate.json`. Git metadata is used read-only.
- Fresh targeted backend run: 221 passed, exit 0, 91.29 s, `freeze-focused-backend.log`. Includes actual FFmpeg MP3/M4B checks, injected F5 process/lock/cancel checks, publication/revision/QA/recovery and atomic Xray regressions. One existing passlib `crypt` deprecation warning.
- Fresh targeted frontend run: 164 passed in 7 files, exit 0, 23.09 s, `freeze-focused-web.log`; one later library-count regression is included in final aggregate.
- `NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/lint.sh`: PASS, exit 0, `freeze-lint.log`.
- Candidate `scripts/check-environment.sh`: PASS, exit 0, `candidate-environment.log`, with isolated writable data and a sanitized ignored fixture `.env`; this is not operator/production qualification.
- Repository operator `.env` absent; operator database permission denied; no permission changes or database writes. The documented external production env is readable but contains no LLM key or reference audio/transcript configuration. RTX 3080 Ti/12 GiB is present, but Torch/F5/vinorm and configured model/reference files are absent; local Ollama is unreachable. Prerequisite JSON files contain only availability flags, never credential values.
- Candidate revision 3: `NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/verify.sh --with-e2e`, exit 1, `candidate-final-verify.log`. Backend 1373 passed / 1 warning, 410.44 s; frontend 787 passed / 86 files, exit 0; compile/environment/lint/typecheck/dependencies/build passed. Desktop E2E: 11 passed / 3 failed / 2 skipped. The E2E failures were an obsolete default-screen assertion, Reader menu being covered by quick controls, and a mobile book button without its own bounding box.
- Browser repairs: menu above quick controls, bounded scrolling and width; native mobile book button keeps its own hit area; login expects the Library default. `npm --prefix web test -- src/styles.layers.test.ts src/components/LibraryBooksView.test.tsx`: 24 passed, exit 0. Build and the three failed E2E cases subsequently passed, exit 0, `browser-repair-validation.log`. An earlier command incorrectly repeated Vitest's `--run` flag and exited before executing tests (`browser-repair-focused.log`); corrected invocation above.
- Candidate revision 4 freezes 694 source files after the two CSS fixes and E2E update. Revision 3 metadata is retained separately; its failed aggregate is not rebound to revision 4. Final unchanged wrapper: `NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/verify.sh --with-e2e`, exit 0, `candidate-release-verify.log`: all 10 mandatory gates passed, backend 1373 passed / 1 warning / 428.40 s, frontend 787 passed in 86 files, desktop E2E 14 passed / 2 skipped / 21.6 s. The two desktop skips require a touch-device profile and were both executed separately: `npm --prefix web run test:e2e -- --project=mobile-chromium`, exit 0, 2 passed / 15.4 s, `candidate-release-mobile.log`.
- `NOVEL_PIPELINE_IGNORE_DOTENV=1 TTS_PROVIDER=edge_tts .venv/bin/python -m scripts.smoke_tts_audio`: exit 0, 3/3 PASS, `candidate-final-audio-smoke.log`. FFmpeg is real; engine/audio input is a fixture. This is retained from the current turn with its unchanged backend binding revalidated after CSS-only revision 4 changes; it was not rerun or presented as real-provider proof.
- Reader benchmark repeated after CSS changes: `node work/repo-research/novel-tnn/implementation/reader-performance.mjs`, exit 0, `reader-performance-release.log`. 15/15 samples readable; one bootstrap each, zero initial source/dictionary/playlist requests. Medians normal/slow-source/failed-source: 844/858/852 ms. Revision 3 measurements retained separately. Import 500 chapters median 195.195 ms versus audit 672.890 ms, one connection/two commits. Library 1000-book median 36.217 ms versus 35.632 ms, no improvement claim.

## Changed scope and remaining risks

- Storage/database: `chapter_content.py`, new chapter/QA repositories, schema/db compatibility facade, Reader repository connection ownership. API schemas and routes expose additive revision/quality fields and conflict responses.
- Translation/import: shared transport, QA reviewer/envelope/service, pipeline/job services, glossary/import follow-up transactions, immutable source writers. Legacy CLI/daily/dashboard paths use the same publication and TTS guards.
- Audio: F5 process lifecycle, normalizer, compressed-audio QA, immutable TTS manifests/children/cache/publication, shared PCM merger and M4B export.
- Frontend: App/Reader/Workbench, demand-driven chapter/audio/offline state, API types/client, grouped Reader controls, Reader/Library CSS; regression tests and browser E2E. Existing operator edits and dependency/CI configuration are preserved.
- Full tests use an isolated candidate; operator database migration and deployment are not performed. Legacy QA/audio remain explicitly unverified where no qualifying receipt exists. T12 selected structural boundaries are now locally verified by the final refactor candidate. T13 real translation/voice/GPU quality remains `BLOCKED_EXTERNAL` until accessible provider/model/reference prerequisites exist. Full plan qualification is not complete while T13 remains unfinished.

Final scope verification after the mandatory wrapper: `git diff --check`, exit 0; source/candidate binding 694 files, zero mismatches; both report files have zero broken links or trailing-whitespace issues; final build assets match the performance record. Receipt: `work/repo-research/novel-tnn/implementation/validation-final.json`. The owned preview process was stopped after measurements; the isolated candidate and logs remain reviewable. No commit, push or deployment performed.

## Refactor status correction — 2026-10-02

The previous T12 `DONE` label covered only the refactors made alongside correctness fixes. It overstated completion of the broader structural work described in the code-quality audit; status is corrected to `PARTIAL`. Current source review found ReaderView 4273 lines, App 2145, ImportPanel 2454, PipelineService 4410 and db.py 5513. ImportPanel and import route orchestration have no implementation diff; App/Reader have loading/behavior changes, but their larger workflow controllers are still present. Line count is supporting context, not an acceptance target.

Next structural scopes: move Reader progress/sync, selection/marks, dictionary and AI/Xray state/actions to their owning feature hooks/panels; separate import preview/commit workflows by source while reusing existing job helpers; reduce App to shared session/navigation and selection; continue domain repository extraction and remove database imports from the API layer where the domain is touched. Preserve API, cancellation, overwrite confirmation, browser sessions, offline/resume and migrations. These scopes can proceed without LLM/F5 credentials or model assets.

This correction changes reports only. The 694 bound source files still match the final tested candidate; prior test receipts remain dated evidence, not new runs. No product test or build rerun for this documentation correction. Report validation and scope evidence: `work/repo-research/novel-tnn/implementation/refactor-status-review.json`.

## T12 continuation — implemented boundaries, acceptance pending

The user authorized continuing the structural refactor. Saved pre-refactor
sources and diff are under `implementation/refactor/`; existing dirty operator
changes are retained. Ownership is documented in
[code-modularity-plan.md](../code-modularity-plan.md). No schema, dependency,
CI/TypeScript configuration, browser session or operator data change is included.

Fresh focused checks in this continuation:

- `npm --prefix web test -- src/App.integration.test.tsx src/components/ReaderView.test.tsx src/components/ImportPanel.test.tsx src/state/useImportJob.test.tsx`: 182 passed, exit 0, 21.39 s; `refactor/frontend-focused-final-attempt2.log`. An earlier repeated `--run` option exited before tests; that receipt is retained separately.
- `NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/lint.sh`: exit 0 before the final ebook extraction, `refactor/lint-final.log`; final candidate lint still required.
- Focused import/transaction/metadata/DB/job-state tests: 88 passed, exit 0, 33.24 s; `refactor/pipeline-tests.log`.
- Repository-boundary, job/glossary, DB-performance and API-security tests: 79 passed, exit 0, 39.96 s; `refactor/boundaries-security-tests.log`.
- AST comparison: 80 moved database functions/classes retain identical AST; no Pipeline public method missing or signature changed. `refactor/structural-review.json` records modified service plumbing; public behavior is verified by tests rather than AST identity alone.

Prior candidate 4 manifests/logs remain unchanged historical receipts. They do
not qualify the new T12 source. Final full verification, desktop/mobile E2E and
controlled Reader measurements require a new frozen candidate. Real-provider
translation/F5 qualification remains separately blocked in T13.

- Ebook orchestration: `NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q -s tests/test_mobile_api_import_ebook.py tests/test_mobile_api_import_wizard.py tests/test_mobile_api_upload_limits.py tests/test_mobile_api_import_jobs.py`: 47 passed, exit 0, 44.43 s; `refactor/ebook-orchestration-tests.log`. Includes confirmation conflict retry, cross-device staging and cleanup of ordinary failures.
- Final focused lint/typecheck after ebook extraction: `scripts/lint.sh`, exit 0, `refactor/lint-freeze.log`.
- Final review found import benchmark instrumentation still targeting old private helper ownership. Corrected only measurement routing; `pytest -q -s tests/test_import_transaction_performance_contracts.py`: 10 passed, exit 0, 3.19 s, `refactor/benchmark-instrumentation-tests.log`; the new case rejects missing per-stage timings and retains one connection/two commits.
- Candidate revision 1 was already verifying while this measurement correction was made. Its manifest remains `refactor/candidate-revision1.json`; revision 2 must bind the changed benchmark/test and pass the final wrapper before current qualification is marked complete.

- Refactor candidate revision 1 wrapper: exit 1 at backend tests, 1374 passed / 2 failed, 402.30 s; `refactor/candidate-verify.log`. Both failures were stale fault-injection namespaces after extraction (`pipeline_service.upsert_import_chapter_with_connection` and `db.validate_fetch_url`), before the assertions could run. Updated targets to `import_commit_service` and `import_repository`; rollback/no-DNS assertions are unchanged.
- Revision 2 was interrupted once the same two failures were known: exit 2, 635 passed / 2 failed before interruption, 163.66 s; `refactor/candidate-final-verify.log`. It is unqualified and will not be retried with unchanged test targets.
- `NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q -s tests/test_import_idempotency.py tests/test_import_transaction_performance_contracts.py tests/test_repository_boundaries.py`: 19 passed, exit 0, 4.94 s; `refactor/import-compatibility-final.log`. Includes both formerly failing injections, concurrent/idempotent import, rollback, no DNS and stage measurement contracts.
- Final refactor candidate revision 3 is frozen after these focused repairs. Full wrapper and mobile E2E receipts must bind this revision; controlled benchmarks run only after validation stops to avoid load-contaminated timings.

- Final candidate revision 3 mobile: `NOVEL_PIPELINE_IGNORE_DOTENV=1 npm --prefix web run test:e2e -- --project=mobile-chromium`: 2 passed, exit 0, 15.6 s; `refactor/candidate-release-mobile.log`. Built/served the final candidate and exercised touch shell, Library-to-Reader, one bootstrap and on-demand optional data. No port remained listening after Playwright cleanup.

## T12 final acceptance — 2026-10-02

- Final candidate: `/tmp/novel-tnn-refactor-rzkvim8g`, refactor revision 3; 729 source/test/config/doc files bound by SHA-256 in `implementation/refactor/candidate.json`. Only this progress report and implementation-results may change after freeze. Earlier candidate/revision manifests and failed/interrupted logs are retained without rebinding.
- `NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/verify.sh --with-e2e`: **PASS, exit 0, all 10 mandatory gates**; `refactor/candidate-release-verify.log`. Backend 1377 passed / 1 existing warning (395.50 s); frontend 787 passed / 86 files; production build, compile, shell, environment fixture, lint/typecheck and dependency consistency pass. Desktop E2E 14 passed (21.3 s); two mobile-only skips are covered by the separate 2/2 mobile PASS (15.6 s).
- `NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m scripts.benchmark_import_transaction --counts 120,500 --runs 3 --large-bytes 0 --include-followups --work-root /tmp --output ...`: exit 0; `refactor/import-performance.log` and JSON. Median 46.379 / 173.774 ms; every run retains 1 connection / 2 commits and positive phase timings. Synthetic fixtures and real deterministic follow-ups; no LLM invocation.
- `NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m scripts.benchmark_database_library --samples 5 --book-counts 100 1000 --output ...`: exit 0; `refactor/library-performance.log` and JSON. Translated library 1000 books median 34.957 ms, 1 connection / 1 query; timing differences from earlier runs are not attributed to refactor alone.
- `node work/repo-research/novel-tnn/implementation/refactor/reader-performance.mjs`: exit 0; `refactor/reader-performance.log` and JSON. Built final candidate served on an owned local preview; 15/15 translations visible, medians 846 / 843 / 852 ms for normal / slow / failed source, zero initial source/dictionary/playlist requests, exactly one bootstrap per sample.
- Python gzip level 9: main 112087 bytes, Reader 55583, Import 20868, CSS 38091. Main/Reader slightly increased from the prior candidate; no bundle-size improvement claim. All measurements were sequential after validation stopped. `refactor/performance-summary.json` binds the methodology and candidate.
- Changed ownership and line counts: ReaderView 4273 → 2622; App 2145 → 970; ImportPanel 2454 → 1456; db.py 5513 → 3469; PipelineService 4410 → 3727; import routes 1451 → 1299. State/actions and domain logic have real callers in their new owners; line count alone is not acceptance. File list and preservation evidence: `refactor/review-scope.json`; repository contracts: `tests/test_repository_boundaries.py`.
- Final diff, report links and source binding are checked in `refactor/validation-final.json`. Owned preview was stopped after measurement; no production deployment, database migration, dependency/configuration change, commit or push. T12 is complete for the selected boundaries; future source/TTS/client/CSS decomposition requires a concrete gap. T13 still has no real-provider quality receipt.
