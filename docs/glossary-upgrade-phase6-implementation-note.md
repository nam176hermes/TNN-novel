# Glossary upgrade Phase 6 implementation note

## Scope and result

Phase 6 adds privacy-bounded glossary observability to the existing in-process
stack, exposes it through the existing authenticated operations response, and
provides cumulative 10,000-row backend, frontend, and real-browser
certification. The original Phase 6 implementation ended at `9146bfe`; the
review-fix production commit is
`8ee219564bbf6f6dc02a46c35bc745d67e303974` on
`codex/glossary-phase6-ops-e2e`.

The review fix closes every reported Important and Minor finding:

- transition telemetry is emitted only after the containing SQLite commit;
- a filtered queue query cannot overwrite the unfiltered active-conflict
  inventory gauge;
- extraction observation uses the fixed `observe` action label;
- primary/variant conflict matching is regression-tested in both ID directions
  and reciprocal matches are de-duplicated;
- the runbook distinguishes metric snapshots from structured fingerprint
  events;
- one committed command now builds and serves the final app, creates two fresh
  10,000-row fixtures, logs into fresh Chromium sessions, runs the full journey
  independently at desktop and mobile widths, and cleans up its temporary
  servers, sessions, and databases;
- the mobile **Thêm** menu exposes **Raw chưa dịch**, so the same chapter-first
  journey is keyboard- and touch-reachable on mobile.

All verification used synthetic, Linux-native `/tmp` data. No operator
database, production service, deployment, remote Git state, or live/paid
provider was read or changed.

## Exact cumulative Task 7 tracked-file inventory

The following is the exact path set returned for the final Task 7 round-2 tree
by:

```bash
git diff --name-only 1a83b693c57247ef1e54d9938440d2092066aa76..HEAD
```

```text
app/database/glossary_repository.py
app/database/glossary_resolver.py
app/mobile_api/services/glossary_service.py
app/mobile_api/services/operational_metrics_service.py
app/mobile_api/services/qa_service.py
app/observability.py
docs/glossary-upgrade-phase6-implementation-note.md
docs/glossary-upgrade-runbook.md
scripts/certify_glossary_phase6_browser.sh
scripts/glossary_phase6_browser_journey.js
scripts/prepare_glossary_phase6_fixture.py
tests/test_glossary_phase4_bulk_import.py
tests/test_glossary_phase6_browser_orchestrator.py
tests/test_glossary_phase6_operations.py
web/src/components/GlossaryStyleView.test.tsx
web/src/components/GlossaryStyleView.tsx
web/src/components/WorkflowShell.test.tsx
web/src/components/WorkflowShell.tsx
```

Thirteen of those paths were already in the original implementation through
`9146bfe`. The review fixes added these five paths to the cumulative set:
`scripts/certify_glossary_phase6_browser.sh`,
`tests/test_glossary_phase4_bulk_import.py`,
`tests/test_glossary_phase6_browser_orchestrator.py`,
`web/src/components/WorkflowShell.test.tsx`, and
`web/src/components/WorkflowShell.tsx`. Review fixes also strengthened several
of the original thirteen paths; the canonical list above is the authoritative
complete Task 7 set.

## Review fix round 2 — conflict-direction regression

Round 2 changes only this note and
`tests/test_glossary_phase4_bulk_import.py`; production, frontend, browser,
dependency, lockfile, and configuration files are unchanged. The conflict
regression now uses three disjoint pairs:

1. a lower-ID term whose variants contain the higher-ID primary;
2. a higher-ID term whose variants contain the lower-ID primary;
3. a reciprocal pair in which each term names the other as a variant.

It requires exactly three unique `primary_variant` groups, the literal three
member pairs, the lower member ID as canonical, and two members per group.
Mutation checks prove the test catches all requested regressions:

- current production before mutation: exit `0`, `1 passed, 1 warning in
  1.82s`;
- temporary `variant.id < term.id` restriction: exit `1`, expected three
  groups but received two; `1 failed, 1 warning in 1.83s`;
- temporary `variant.id > term.id` restriction: exit `1`, expected three
  groups but received two; `1 failed, 1 warning in 1.80s`;
- temporary removal of `SELECT DISTINCT`: exit `1`, expected three groups but
  received four; `1 failed, 1 warning in 1.71s`;
- production restored byte-for-byte: exit `0`, `1 passed, 1 warning in
  1.64s`.

No production fix was needed. The affected Phase 4/6 and orchestrator-contract
suite exited `0` with `31 passed, 49 warnings in 30.73s`. `scripts/lint.sh`
and `git diff --check` also exited `0`.

The round-2 test/docs commit is
`adc6f71813406926beddb6ec803e31efc1656bef`, tree
`1cbe1cfb9c36b2cd0c37d3910ac1ed0aa6e087c3`. On that committed tree, the
literal canonical command
`NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/verify.sh` exited `0`:

- compile, shell syntax, environment, lint/typecheck, and Python dependency
  consistency passed;
- backend: `1455 passed, 469 warnings in 491.75s`;
- frontend: `87` files and `799` tests passed in `34.66s`;
- frontend build: `1858` modules transformed and built in `945ms`.

That run used only an ignored comment-only `.env` and a symlink to a newly
initialized synthetic `/tmp/novel-tnn-phase6-round2-verify1-a6uNhu/data`
tree. The symlink, ignored file, and exact temporary tree were removed after
the run. Browser certification was not repeated because round 2 changes no
production, frontend, or browser code.

## Implementation boundaries

The implementation continues to reuse
`app.observability.default_observability`, `InMemoryMetrics`, and
`StructuredEventLogger`; it adds no telemetry dependency or parallel stack.
Instrumentation remains at shared repository, query/extraction service,
resolver, QA, and operations-response boundaries.

`GlossaryRepository._log` still writes the bounded history record inside the
caller transaction, but now returns an allow-listed numeric/state transition
payload. `_commit_and_emit_transitions` commits first and publishes those
payloads only after SQLite reports success. Standalone create/update/state and
archive/restore paths use the same helper. Extraction, bulk update, conflict
merge, and import collect their already-bounded transition payloads and emit
them after the single transaction commit. A forced SQLite trigger failure on
the second bulk history insert proves that rolled-back rows produce neither a
transition counter nor a structured transition event.

Queue telemetry now exposes `glossary_active_conflicts`, calculated from all
unarchived `CONFLICT` rows independently of the current queue search/status
filter. The filtered conflict count remains in the bounded `glossary_query`
event. Existing authenticated operations response fields remain unchanged.

Structured events contain only controlled action/state/mode/extractor/error
codes, durations, counts, numeric IDs/versions, and existing non-reversible
fingerprint identifiers. Source/target terms, variants, notes, title/body,
context/prompt content, provider credentials, and filesystem paths remain
excluded. Fingerprint identifiers are available in structured event logs, not
as fields in the operations metric snapshot.

The operator runbook keeps these rules unconditional:

1. Do not create a normalized unique index until a fresh copied-database audit
   reports zero same-book normalized collision groups.
2. Never purge archived glossary rows.
3. Roll back the application/UI and disable hybrid extraction without a
   destructive schema down-migration.

## Review-fix TDD ledger

The first combined regression run was:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 TMPDIR=/tmp TMP=/tmp TEMP=/tmp \
  .venv/bin/python -m pytest -q -s \
  tests/test_glossary_phase6_operations.py::test_filtered_query_does_not_overwrite_active_conflict_inventory \
  tests/test_glossary_phase6_operations.py::test_bulk_rollback_emits_no_transition_telemetry \
  tests/test_glossary_phase6_operations.py::test_extraction_observe_transition_uses_a_fixed_action_label \
  tests/test_glossary_phase6_browser_orchestrator.py \
  tests/test_glossary_phase4_bulk_import.py::test_primary_variant_conflict_query_is_symmetric_and_deduplicated
```

It exited `1`: `5 failed, 1 warning in 2.25s`. The production gaps were the
missing active-inventory gauge, one leaked rolled-back transition, the
`unknown` extraction action, and the absent orchestrator. The first variant
fixture also used a non-canonical serialization and was corrected before using
that regression as evidence; with canonical delimiter storage, the existing
query already returned the expected symmetric pair. The focused non-browser
GREEN then exited `0`: `4 passed, 1 warning in 2.09s`. The orchestrator contract
test separately passed `1 passed in 0.03s`.

The first real orchestrator run failed before Chromium because the legacy
`ops.py wait-health` helper expects `status=ok`, while the current readiness
endpoint correctly returned HTTP 200 with
`ready_with_degraded_capabilities`. The orchestrator now performs a bounded,
stdlib-only semantic readiness check accepting `ready` and
`ready_with_degraded_capabilities`; it does not treat HTTP 2xx alone as ready.

The first complete desktop journey then exposed that newly extracted blank-
target candidates are intentionally omitted from the default
`include_weak=false` review query. The certification therefore proves their
durable post-state by parsing a second browser download after re-extraction:
the total changes from `10002` to `10007`, and all five exact extracted rows
have `NEEDS_REVIEW` plus chapter IDs/numbers of `1`.

The first full mobile run exposed a genuine navigation RED:

```bash
npm --prefix web test -- src/components/WorkflowShell.test.tsx \
  -t 'keeps mobile workflow navigation wired'
```

It exited `1` because the mobile **Thêm** dialog had no accessible
**Raw chưa dịch** button. The minimal route action made the same command exit
`0`: `1 passed, 5 skipped`.

## Focused and cumulative GREEN evidence

All commands ran from the Phase 6 worktree before the production commit.

- Phase 4 + Phase 6 + orchestrator contract:
  `31 passed, 49 warnings in 30.97s`, exit `0`.
- Affected frontend API/state/view/shell suite: `4` files and `36` tests
  passed in `5.35s`, exit `0`.
- `scripts/lint.sh`, shell syntax, JavaScript syntax, and `git diff --check`:
  exit `0`.
- Cumulative Phase 0–6, QA, service, and API suite: `148 passed, 81 warnings
  in 101.49s`, exit `0`.
- Pre-commit self-contained browser certification: exit `0`, with two fresh
  10,000-row fixtures and complete desktop/mobile receipts.

## Canonical gates after production commit

Production SHA under test:
`8ee219564bbf6f6dc02a46c35bc745d67e303974`.

The isolated worktree had no local development `.env` or `data` tree. For the
canonical gate only, `.env` was an ignored credential-free comment and `data`
was an ignored symlink to a freshly initialized
`/tmp/novel-tnn-phase6-fix-verify-46vxOf/data`. No operator file was copied.
Both entries and the temporary tree were removed after verification.

The literal canonical command:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/verify.sh
```

exited `0` with:

- Python compile, shell syntax, environment, lint/typecheck: pass;
- backend: `1455 passed, 469 warnings in 493.91s`;
- Python dependency consistency: pass;
- frontend: `87` files and `799` tests passed in `34.48s`;
- frontend build: `1858` modules transformed, built in `900ms`.

The separately required command also exited `0`:

```bash
git diff --check && npm --prefix web run build
```

The explicit build transformed `1858` modules and completed in `748ms`.

## Reproducible Chromium certification

The entire setup/build/start/open/login/journey/cleanup sequence is one
committed command:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 TMPDIR=/tmp TMP=/tmp TEMP=/tmp \
  scripts/certify_glossary_phase6_browser.sh
```

The script:

1. selects a loopback-only ephemeral port and builds the final SPA for it;
2. creates an empty Linux-native temporary root;
3. prepares a fresh exact 10,000-row fixture for desktop;
4. starts `python -m app.mobile_api` with final static serving, synthetic local
   credentials, authentication enabled, and every external provider key empty;
5. waits for semantic readiness, opens a fresh direct CLI Chromium session,
   resizes to `1440x900`, logs in, and runs the complete driver;
6. closes the session and server;
7. repeats steps 3–6 with an independent fixture at `390x844`;
8. removes both fixture trees through its exit trap while retaining only
   ignored receipts under `output/playwright/`.

The final post-commit invocation exited `0` and printed:

```text
PHASE6_BROWSER_CERTIFICATION_OK fixtures=2 rows_each=10000 \
viewports=desktop:1440x900,mobile:390x844 \
artifacts=.../output/playwright/phase6-certification-20260830T203548Z-742410
```

Each viewport independently asserted:

- initial pending queue rows `1–4 / 4`;
- all-list page 1 and page 2 each containing 50 distinct rows;
- search result `synthetic-source-09999 → synthetic-target-09999`;
- created row and initial target, edited target, approved queue, then locked
  queue;
- both bulk-selected rows absent from pending and present with approved state;
- merge preview, no remaining conflict group, active canonical row, and
  archived duplicate row;
- import preview and the applied imported row/target;
- suggested filename `glossary.json`, parsed JSON schema/scope/total, locked
  created content, imported content, archived merge duplicate, and fixture
  tail;
- archive intermediate state and restored final locked state;
- exact re-extraction status and a parsed post-extraction export containing all
  five exact new rows (`10007` total);
- visible keyboard focus on the profile `SUMMARY` and successful Enter
  activation;
- no post-auth HTTP response at or above 400;
- no horizontal page overflow before or after the journey.

Desktop receipt: export total `10002`, `httpFailures=[]`, initial/final
body/root/inner widths `1440/1440/1440`, keyboard activation `true`.

Mobile receipt: export total `10002`, `httpFailures=[]`, initial/final
body/root/inner widths `390/390/390`, keyboard activation `true`.

Final ignored artifacts include:

- `output/playwright/phase6-certification-20260830T203548Z-742410/desktop/phase6-desktop-final.png`;
- `output/playwright/phase6-certification-20260830T203548Z-742410/mobile/phase6-mobile-final.png`;
- each viewport's `fixture.json`, `journey.log`, `server.log`, CLI snapshot,
  console receipt, and final parsed download.

The only server `4xx` before each journey listener is the expected fresh-session
`POST /api/auth/refresh` `401`; the driver attaches its HTTP failure listener
after successful login and reports no failures. Chromium is headless, so this
is functional, responsive, and accessibility smoke evidence rather than a
manual visual-design sign-off.

No dependency, lockfile, CI/global configuration, operator database, provider,
deployment, push, or main-branch merge was involved. Independent review was
not dispatched because this fix assignment explicitly prohibited subagents and
reviewers.
