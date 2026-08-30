# Glossary upgrade Phase 6 implementation note

## Scope and result

Phase 6 adds privacy-bounded glossary observability to the existing in-process
stack, exposes that shared snapshot through the existing authenticated
operations response, adds cumulative 10,000-row integration coverage and a
real Chromium operator journey, and documents the staged migration and
rollback procedure.

The production implementation was committed as `0b3cac1` on
`codex/glossary-phase6-ops-e2e`, based on
`1a83b693c57247ef1e54d9938440d2092066aa76`. Verification used only isolated,
synthetic data on the Linux-native `/tmp` filesystem. No operator database,
production deployment, remote Git state, or live/paid provider was touched.

## Changed files

- `app/observability.py` adds bounded glossary query, transition, extraction,
  provider-failure, resolution/fingerprint, and QA recording methods to the
  existing `Observability`, `InMemoryMetrics`, and `StructuredEventLogger`
  stack. Metric labels are fixed allow-listed dimensions.
- `app/database/glossary_repository.py` records state transitions at the shared
  history boundary, preserves explicit save-and-approve semantics, and avoids
  the quadratic all-pairs primary/variant conflict scan by joining only rows
  that actually contain variants.
- `app/database/glossary_resolver.py` records effective-term counts and the
  existing non-reversible SHA-256 glossary fingerprint.
- `app/mobile_api/services/glossary_service.py` records query latency, result
  and conflict counts, extraction outcomes, and sanitized provider failure
  codes at shared service boundaries.
- `app/mobile_api/services/qa_service.py` records glossary QA run and violation
  counts without emitting source or translation text.
- `app/mobile_api/services/operational_metrics_service.py` adds the shared
  observability snapshot to the existing authenticated operations payload
  while retaining every prior top-level field.
- `web/src/components/GlossaryStyleView.tsx` keeps create actions scoped to the
  selected book when the query omits its redundant `book_id` field.
- `web/src/components/GlossaryStyleView.test.tsx` adds cumulative stateful UI
  coverage for the operator workflow and the selected-book create contract.
- `tests/test_glossary_phase6_operations.py` covers all required telemetry
  categories, sentinel privacy boundaries, additive operations exposure, and
  the complete 10,000-row authenticated API journey.
- `scripts/prepare_glossary_phase6_fixture.py` reuses the Phase 0 fixture helper
  to create exactly 10,000 glossary rows plus deterministic queue, conflict,
  book, and chapter data in an empty caller-supplied directory.
- `scripts/glossary_phase6_browser_journey.js` is a CLI-first Playwright driver
  for queue, search, pagination, create/edit, approve/lock, bulk approve,
  conflict preview/apply, import preview/apply, export, archive/restore,
  re-extraction, responsive overflow, and keyboard activation.
- `docs/glossary-upgrade-runbook.md` gives the backup, copied-database audit,
  additive API/schema rollout, legacy-client smoke, UI rollout, conflict
  cleanup, per-book hybrid enablement, and application-only rollback sequence.
- `docs/glossary-upgrade-phase6-implementation-note.md` records this evidence.

## Privacy and operational contract

The shared snapshot now contains these glossary series:

- counters: queries, state transitions, extractions, provider failures,
  resolutions, QA runs, and QA violations;
- gauges: current query-scope conflict count and effective term count;
- latency: bounded query-latency samples with count, p50, and p95;
- structured events: query, state transition, extraction, resolution, and QA.

Events contain only controlled action/state/mode/extractor/error codes,
durations, counts, numeric IDs/versions, and the existing 64-character
non-reversible fingerprint. They do not accept source terms, target terms,
variants, notes, title/body/context/prompt content, provider credentials, or
filesystem paths. The privacy test injects private chapter-body, title,
translation, provider-secret, and path sentinels and proves none enter logs,
metric labels/snapshots, the operations snapshot, or operational persistence;
chapter/provider/path sentinels also do not enter glossary evidence or history.

The runbook makes two data rules unconditional: create no normalized unique
index until a fresh copied-database audit reports exactly zero normalized
same-book collision groups, and never purge archived glossary rows. Rollback
disables hybrid extraction and the new UI/application artifact while leaving
the additive schema readable; it does not run a destructive down migration.

## TDD evidence

The first telemetry/API test run was a genuine RED:

```text
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q -s \
  tests/test_glossary_phase6_operations.py
exit 1: 2 failed in 0.99s
```

It failed because the glossary metric/event categories and `observability`
operations field did not exist. After the focused implementation, the same two
tests exited `0`: `2 passed in 0.86s`.

The real browser then exposed two cumulative contracts that were locked with
focused RED tests before their production fixes:

```text
npm --prefix web test -- src/components/GlossaryStyleView.test.tsx \
  -t 'cumulative 10k operator workflow'
exit 1: expected create book_id 42, received 0; 1 failed, 10 skipped

NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q -s \
  tests/test_glossary_phase6_operations.py -k ten_thousand
exit 1: save-and-approve PATCH expected 200, received 409;
1 failed, 2 deselected, 4 warnings in 2.59s
```

Focused GREEN results were `1 passed, 10 skipped` in `3.26s` for the frontend
contract and `1 passed, 2 deselected, 4 warnings` in `3.66s` for the API
contract. A cumulative Phase 0-6 run then caught an over-broad unlock action
classification (`1 failed, 142 passed, 81 warnings in 103.15s`). The action was
narrowed so `locked=0` remains an unlock unless the same request explicitly
asks for approval. The exact regression plus the 10,000-row API journey passed
`2 passed, 4 warnings in 4.20s`; the cumulative rerun passed `143 passed, 81
warnings in 108.84s`.

The original conflict query also revealed a production-scale blocker: the
all-pairs primary/variant scan did not return after 91 seconds on 10,000 rows.
Restricting that join to rows with a non-empty variants payload preserved the
same conflict pairs and reduced the focused 10,000-row journey to `3.67s` (`1
passed, 2 deselected, 4 warnings`).

## Focused and cumulative validation

All commands ran from the Phase 6 worktree.

- `NOVEL_PIPELINE_IGNORE_DOTENV=1 TMPDIR=/tmp TMP=/tmp TEMP=/tmp
  scripts/lint.sh` — initial exit `1` for one unused test-local `db_path`;
  after removing it, exit `0` with TypeScript typecheck green. The final rerun
  after the action fix also exited `0` in `14.5s`.
- `NOVEL_PIPELINE_IGNORE_DOTENV=1 NOVEL_PIPELINE_TEST_TMPDIR=/tmp
  TMPDIR=/tmp TMP=/tmp TEMP=/tmp .venv/bin/python -m pytest -q -s
  tests/test_glossary_phase0_baseline.py tests/test_glossary_phase1_state.py
  tests/test_glossary_phase2_resolver.py
  tests/test_glossary_phase3_review_query.py
  tests/test_glossary_phase4_bulk_import.py
  tests/test_glossary_phase5_extraction.py
  tests/test_glossary_phase6_operations.py tests/test_glossary_qa_phase4.py
  tests/test_glossary_service_logic.py tests/test_mobile_api_glossary.py` —
  exit `0`; `143 passed, 81 warnings in 108.84s`.
- `npm --prefix web test -- src/api/glossary.test.ts
  src/components/GlossaryReviewQueue.test.tsx
  src/components/GlossaryStyleView.test.tsx
  src/state/useGlossary.test.tsx` — exit `0`; `4` files and `37` tests passed
  in `5.22s`.
- `node --check scripts/glossary_phase6_browser_journey.js` and Python compile
  checks for the fixture/test files — exit `0`.

## Canonical post-commit gates

The first literal canonical invocation,
`NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/verify.sh`, exited `1` at the
environment preflight before tests. The isolated worktree lacked the ignored
local-development prerequisites `.env`, `data/pipeline.db`, `data/`, and
`data/logs`; this was a worktree setup failure, not a source/test failure.

For the retry, `.env` was an ignored, credential-free marker and `data` was an
ignored symlink to a newly initialized disposable directory under `/tmp`; no
operator data or credentials were copied or read. The exact same literal
command then exited `0`:

- compile, shell syntax, environment, lint/typecheck: pass;
- backend: `1450 passed, 469 warnings in 490.69s`;
- dependency consistency: pass;
- frontend: `87` files and `799` tests passed in `31.12s`;
- frontend build: `1858` modules transformed, built in `736ms`.

The separately required `git diff --check && npm --prefix web run build`
exited `0`; the explicit build transformed `1858` modules and completed in
`717ms`. A subsequent ignored browser-only build with
`VITE_API_BASE_URL=http://127.0.0.1:17860` also exited `0` (`1858` modules,
`733ms`); this merely directed the local SPA at the isolated loopback server.

## Final Chromium evidence

The final run used commit `0b3cac1`, real headless Chromium, and a newly created
`/tmp/novel-tnn-phase6-final-browser-iIrqhQ/data` fixture. Fixture preparation
exited `0` with:

```json
{"book_id": 1, "chapter_id": 1, "rows": 10000}
```

The Playwright skill wrapper could not execute on this Linux host because its
checked-in launcher has CRLF (`/usr/bin/env: 'bash\r': No such file or
directory`, exit `127`). Directly invoking the same CLI package initially
inherited a Windows temporary path and returned `ENOTSUP`; setting
`TMPDIR=/tmp TMP=/tmp TEMP=/tmp` resolved that host-only issue. No wrapper,
dependency, lockfile, or global configuration was modified.

The final CLI command ran from `output/playwright/final/` so every artifact is
contained below the ignored `output/playwright/` tree:

```text
TMPDIR=/tmp TMP=/tmp TEMP=/tmp \
npx --yes --package @playwright/cli playwright-cli \
  --session phase6-final run-code \
  --filename /home/thenam176/Novel-TNN/.worktrees/glossary-phase6-ops-e2e/scripts/glossary_phase6_browser_journey.js
exit 0 in 13.9s
```

The structured receipt was:

```json
{
  "datasetRows": 10000,
  "desktop": {"height": 900, "noHorizontalOverflow": true, "width": 1440},
  "download": "glossary.json",
  "extractionStatus": "5 thuật ngữ mới · 0 cập nhật · 0 cảnh báo",
  "httpFailures": [],
  "keyboard": {
    "activated": true,
    "focusVisible": true,
    "tag": "SUMMARY",
    "text": "Profile văn phong (phụ)"
  },
  "mobile": {
    "bodyScrollWidth": 390,
    "innerWidth": 390,
    "noHorizontalOverflow": true,
    "rootScrollWidth": 390
  }
}
```

This receipt follows the complete journey: default four-row queue, all-terms
page 1 and page 2, search for row 10,000, create, edit plus approve, lock, bulk
approve, conflict preview/apply, import preview/apply, JSON export,
archive/restore, and deterministic chapter re-extraction. Keyboard-only `Tab`
reached a visible-focus `SUMMARY`, and `Enter` opened it. Separate viewport
receipts confirmed desktop root/inner widths `1440/1440` and mobile
body/root/inner widths `390/390/390`.

Artifacts:

- `output/playwright/final/.playwright-cli/glossary.json`
- `output/playwright/final/.playwright-cli/page-2026-08-30T19-44-44-328Z.png`
  (390 x 844 mobile)
- `output/playwright/final/.playwright-cli/page-2026-08-30T19-44-51-786Z.png`
  (1440 x 900 desktop)

The browser console contains one expected pre-authentication
`POST /api/auth/refresh` `401` while the login screen establishes that no prior
session exists. The post-authentication journey installed its own response
listener and completed with `httpFailures: []`. Chromium ran headless, so this
is functional/responsive/accessibility smoke evidence rather than a manual
visual-design sign-off. Artifacts are local and ignored, not release assets.

Independent review was intentionally not dispatched in this implementation
task. The task-level instruction prohibited subagents/reviewers, so the final
Critical/Important review gate remains for the parent integration workflow.
