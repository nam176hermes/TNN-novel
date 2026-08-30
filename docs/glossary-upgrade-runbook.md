# Glossary upgrade operator runbook

This runbook rolls out the additive glossary schema, API, and operator UI without
rewriting or deleting glossary history. Run every database rehearsal against a
copied database. Replace placeholders only after recording the exact operator
data root, backup archive, release commit, and rollback artifact.

## Non-negotiable data rules

- Create no normalized unique index until the copied-database audit reports
  `normalized_same_book_collisions.groups` equal to `0`. This release does not
  create that index; a later index change requires its own reviewed migration.
- Never purge archived glossary rows. Archive/restore and conflict merge depend
  on those rows remaining readable for history, evidence, and rollback.
- Do not run repair SQL against the operator database. Conflict cleanup uses the
  authenticated preview/apply API or operator UI, one reviewed group at a time.
- Keep the additive columns and tables readable during rollback. Do not drop
  glossary columns, evidence, history, settings, or archived rows.

## 1. Record the release and take a recoverable backup

From the reviewed release checkout, record `git rev-parse HEAD`, the configured
`DATA_DIR`, database size, and current application version. Then follow
[`backup-restore.md`](backup-restore.md) to create a system backup:

```bash
export REPO_ROOT="$(git rev-parse --show-toplevel)"
export DATA_DIR="${DATA_DIR:-$REPO_ROOT/data}"
cd "$REPO_ROOT"
scripts/backup-local.sh
```

Record the exact new archive and sidecar names. Run a restore drill against that
exact archive and require exit `0` before continuing:

```bash
.venv/bin/python scripts/ops.py restore-drill \
  backups/SAFE_BACKUP_ARCHIVE.tar.gz
```

If the backup or drill fails, stop. Do not start the glossary rollout.

## 2. Restore a copy and run the read-only audit

Create a Linux-native private rehearsal directory, restore the exact verified
archive into it, and never point the new process at the operator data root:

```bash
REHEARSAL_DIR="$(mktemp -d /tmp/novel-tnn-glossary-rollout-XXXXXX)"
.venv/bin/python scripts/ops.py restore \
  backups/SAFE_BACKUP_ARCHIVE.tar.gz \
  --target-dir "$REHEARSAL_DIR/restored"
.venv/bin/python scripts/audit_glossary_baseline.py \
  --db "$REHEARSAL_DIR/restored/data/pipeline.db" \
  >"$REHEARSAL_DIR/glossary-audit.json"
```

The audit is query-only and its report contains aggregate counts. Review all
counts, especially state mismatches, approved blank targets, global/book
conflicts, and normalized same-book collisions. A command exit `0` means the
audit ran; it does not mean findings are zero.

On the copied data, start the candidate backend on loopback and let normal
startup run the idempotent additive migration. Restart it once more to prove the
migration is repeatable. Re-run the audit and API smoke against this copy. Stop
if rows disappear, old fields change meaning, the copied database fails
`PRAGMA integrity_check`, or startup is not idempotent.

**Index gate:** even after conflict cleanup, create no normalized unique index
unless a fresh copied-database audit reports exactly zero normalized collision
groups. Zero collisions is necessary, not automatic authorization to add the
index.

## 3. Deploy the additive schema and API

Use the normal reviewed release process. Deploy the backend first, with the old
frontend still served. Startup applies only backward-compatible schema changes;
there is no destructive down migration.

Before exposing the new UI, require:

1. health and authenticated login smoke pass;
2. the old glossary list/search client can still read its existing fields;
3. an existing glossary create/update call still returns its compatible shape;
4. authenticated `GET /api/ops/metrics` retains every prior top-level field and
   adds `observability`;
5. no response or log contains glossary text, chapter text, provider secrets,
   or filesystem paths from telemetry.

Keep extraction mode `deterministic` for every book during this stage. A schema
or legacy-client regression is a stop condition: roll the application artifact
back, keep the additive database intact, and investigate from a new copy.

## 4. Deploy and smoke the operator UI

Deploy the reviewed web artifact only after the API/legacy smoke is green. With
an operator test book, exercise the queue, search, pagination, create/edit,
approve/lock, bulk action, conflict preview without apply, import preview without
apply, export, archive/restore, and deterministic chapter re-extraction. Check a
desktop viewport, a mobile viewport with no horizontal page overflow, and
keyboard focus/activation for the primary workflow.

Do not use an operator book for destructive smoke. Import and merge apply are
certified before rollout on the isolated synthetic fixture; production apply is
an explicit operator data decision.

## 5. Clean conflicts in bounded batches

Open **Xung đột & hợp nhất**, load one page, and inspect each group. Select the
canonical record, generate a fresh preview, verify canonical and duplicate IDs
plus the evidence count, then apply that exact digest. A stale digest or version
conflict must be reloaded and previewed again; never force it through.

Large groups are intentionally bounded. Apply one displayed batch, reload the
same group, and repeat until it disappears. Merge archives duplicate rows and
transfers evidence; it does not authorize deletion. Periodically export a
readable snapshot and rerun the copied-database aggregate audit. Keep hybrid
disabled until the conflict backlog and QA trend are understood.

## 6. Enable hybrid extraction per book

Enable hybrid mode for one low-risk book at a time from **Trích xuất thuật ngữ**.
Choose only an already-configured provider, save the per-book setting, and
re-extract one chapter. Review candidates before approving them. Watch the
authenticated operations snapshot for extraction outcomes, provider failure
codes, query latency, active-conflict inventory, effective-term counts, state
transitions, and QA violation counts. Correlate those metrics with the
structured operational event logs, which carry the non-reversible glossary
fingerprint identifiers; fingerprint identifiers are not metric-snapshot
fields.

Expand only when provider failures, conflicts, latency, and QA remain within the
operator's recorded thresholds. Provider credentials and paid calls are an
operator-controlled rollout decision; they are not required for migration.

## Rollback

Rollback is application-only unless the verified backup itself must be restored.

1. Set each hybrid-enabled book back to `deterministic`; do not re-extract while
   investigating a provider incident.
2. Remove the new glossary UI from service by redeploying the last known-good
   compatible web artifact. Keep the additive API available for legacy clients
   if its smoke remains green.
3. If the backend is implicated, deploy the last known-good compatible backend
   artifact. Do not run a down migration or drop additive glossary schema.
4. Confirm legacy glossary reads, exports, Reader dictionary behavior, and
   authenticated operations metrics still work against the retained schema.
5. Restore the verified backup only for confirmed data corruption and only by
   the staged procedure in [`backup-restore.md`](backup-restore.md). Preserve the
   failed data tree for investigation; never overwrite it in place.

Archived rows remain archived and readable throughout rollback. They are never
purged as cleanup. Record the rollback commit/artifact, affected books, first
bad observation, metrics window, and the backup chosen before any restore.
