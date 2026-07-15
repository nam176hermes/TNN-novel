# P05 — Persistent import-job models

## Scope

P05 adds only durable SQLite models, owner-scoped repository operations, and
state-transition rules for future import jobs. It does **not** start a worker,
claim work, schedule retry, expose HTTP endpoints, or add SSE.

The existing `mobile_jobs` runner remains unchanged. P05 uses independent
tables so a later worker can migrate deliberately rather than changing active
translation/TTS job behaviour.

## Tables

- `import_jobs`: import-level ownership, source metadata, state, timestamps,
  cancellation request, sanitized configuration snapshot, and task-derived
  counters.
- `chapter_tasks`: one canonical source chapter identity per job, durable
  status/stage, attempts, retry timestamp, safe error metadata, fetch metadata,
  persistence result references, timestamps, and optimistic version.
- `import_job_events`: monotonically sequenced, owner-scoped event stream.

No table accepts chapter HTML/text, cookies, tokens, passwords, authorization
headers, or other secrets in `config_snapshot_json` or `payload_json`. The
repository filters these keys before serializing JSON.

## State machine

Job states are `queued`, `running`, `succeeded`, `partially_succeeded`,
`failed`, and `cancelled`.

Task statuses are `queued`, `running`, `waiting_retry`, `succeeded`, `failed`,
`cancelled`, and `user_verification_required`. Task stages are `queued`,
`fetching`, `waiting_retry`, `parsing`, `validating`, `importing`, `succeeded`,
`failed`, `cancelled`, and `user_verification_required`.

Terminal tasks cannot transition back to running. `retry_task` is the only
explicit operation that returns a failed/cancelled/user-verification task to
`queued`; it retains the attempt count. A transition, counter refresh, and
event append are committed in the same SQLite transaction. Update methods use
the row `version` as a compare-and-set guard.

## Migration and rollback

`init_db` applies additive, idempotent migration checks before and after the
canonical schema. The first pass makes a partially-created legacy P05 table
safe for canonical index creation; the second handles fresh tables. No legacy
rows are deleted, rewritten, or automatically queued.

Rollback is application-only: deploy the previous application version, which
does not read these new tables. Do not drop `import_jobs`, `chapter_tasks`, or
`import_job_events` from an operator database without an explicit backup and
data-retention decision. Their data is isolated from existing `mobile_jobs`.

## Validation

```bash
export NOVEL_PIPELINE_IGNORE_DOTENV=1
.venv/bin/python -m pytest -q -s tests/test_import_job_repository.py
scripts/verify.sh
```
