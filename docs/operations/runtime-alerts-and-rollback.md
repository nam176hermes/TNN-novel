# Runtime alerts, deployment, and rollback

This runbook covers the private single-operator deployment. It does not grant
approval to restart or deploy production.

## Operational endpoints

- `GET /api/health` is the minimal liveness probe.
- `GET /api/ready` is the dependency and capability readiness probe.
- `GET /api/version` exposes non-secret release provenance.
- `GET /api/ops/metrics` is authenticated and returns low-cardinality
  operational state plus evaluated alert rules.

Readiness has three states:

- `ready`: all required components and configured capabilities are ready;
- `ready_with_degraded_capabilities`: the core application and required worker
  are ready, but an optional capability such as GPU TTS is unavailable;
- `not_ready`: a required core check or required worker check failed.

Do not page on `ready_with_degraded_capabilities` solely because F5/ViVoice is
unavailable. F5/ViVoice remains GPU-only and must fail closed without CUDA.

## Alert rules

Poll the authenticated metrics endpoint from the operator monitor. Alert codes
are stable and deliberately contain no book, chapter, filename, token, user, or
session identifiers.

| Code | Severity | Trigger |
| --- | --- | --- |
| `worker_not_ready` | critical | Required import worker cannot claim queued work |
| `worker_stale` | critical | Required import worker heartbeat is explicitly stale |
| `release_mismatch` | critical | API and worker release IDs differ |
| `disk_critical` | critical | Free space below 100 MiB |
| `disk_low` | warning | Free space below 1 GiB |
| `queue_stale` | warning | Oldest queued work exceeds one hour |
| `jobs_failed` | warning | Failed or interrupted work exists |
| `backup_failed` | warning | A backup mobile job failed |
| `external_backup_missing`, `restore_drill_missing` | warning | Required receipt is absent |
| `external_backup_stale`, `restore_drill_stale` | warning | Receipt exceeds its configured maximum age |
| `external_backup_invalid`, `restore_drill_invalid` | warning | Receipt JSON, schema, size, or file type is invalid |
| `external_backup_future`, `restore_drill_future` | warning | Completion time exceeds allowed clock skew |
| `external_backup_wrong_release`, `restore_drill_wrong_release` | warning | Producer version differs from the running release |
| `backup_stale`, `restore_drill_stale` | warning | Compatibility aliases emitted with every non-fresh recovery state |
| `artifact_integrity` | critical | Active artifact scan finds unavailable files |

Container restart count is reported only when an external orchestrator provides
it. Docker socket access is intentionally not mounted into the API container.
Public reachability also remains an external probe.

## Operational webhook delivery

The standalone dispatcher selects exactly four low-cardinality alert classes
from a fresh, non-cached operational snapshot:

| Delivery class | Source alert codes |
| --- | --- |
| `backup_failure` | `backup_failed` |
| `wrong_release_receipt` | `external_backup_wrong_release`, `restore_drill_wrong_release` |
| `worker_stale` | `worker_stale` |
| `stuck_jobs` | `queue_stale` |

It is intentionally outside API and worker request paths. A webhook outage or
receipt error makes the command return non-zero; it does not change API or
worker health. Command output is limited to an alert class and bounded status.
It never prints the endpoint, bearer token, response body, or receipt path.

### Isolated synthetic validation

The synthetic command is the safe preflight. It binds a temporary receiver to
the literal loopback address `127.0.0.1`, generates one incident per supported
class, and uses the production dispatcher to write four isolated receipts. It
does not read the operator database, contact an external host, or write anywhere
in the resolved `DATA_DIR` subtree.

```bash
set -euo pipefail
ALERT_SMOKE_DIR="$(mktemp -d)"
chmod 0700 "$ALERT_SMOKE_DIR"
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python \
  -m scripts.smoke_operational_alerts --receipt-dir "$ALERT_SMOKE_DIR"
find "$ALERT_SMOKE_DIR" -maxdepth 1 -type f \
  -name 'alert-*.receipt.json' -print
```

Expect one `class=... status=delivered` line and one receipt for each of the
four classes. The command rejects filesystem root, the repository tree, the
resolved `DATA_DIR` tree (including `logs/runtime` and every other descendant),
relative paths, parent traversal, missing/non-directory paths, and paths reached
through symlinks. Validation finishes before the receiver or dispatcher starts,
so a rejected path cannot overwrite production receipts. Retain the temporary
evidence until reviewed; remove it only after confirming the exact `mktemp`
path and its four bounded receipt files.

### Private configuration and manual dispatch

Start from `deploy/production/alert.env.example`. The committed URL uses the
reserved `.invalid` domain and the token is empty; replace them only in the
private installed file. The dispatcher reads only these variables:

- `NOVEL_ALERT_WEBHOOK_URL` (required HTTPS endpoint);
- `NOVEL_ALERT_WEBHOOK_BEARER_TOKEN` (optional);
- `NOVEL_ALERT_TIMEOUT_SECONDS` (finite request timeout, normalized to safe bounds);
- `NOVEL_ALERT_MAX_ATTEMPTS` (normalized to one through three attempts).

Prepare the private file without printing its contents:

```bash
install -d -m 0700 "$HOME/.config/novel-tnn"
install -m 0600 deploy/production/alert.env.example \
  "$HOME/.config/novel-tnn/alert.env"
chmod 0600 "$HOME/.config/novel-tnn/alert.env"
stat --format='%a %n' "$HOME/.config/novel-tnn" \
  "$HOME/.config/novel-tnn/alert.env"
```

Do not place a live URL or token in the repository, shell history, command
arguments, logs, or receipts. Loading the private environment and running
`python -m scripts.dispatch_operational_alerts` performs real external
delivery. That manual command requires explicit operator approval.

Each outbound JSON object contains exactly `schema_version`, `alert_class`,
`code`, `severity`, `release_id`, `observed_at`, and `fingerprint`. It contains
no alert message, URL, token, response body, job/user identifier, filename,
content, or filesystem path.

### Receipts, retries, and deduplication

The dispatcher stores one atomic mode-`0600` regular file per class below
`DATA_DIR/logs/runtime/`:

- `alert-backup_failure.receipt.json`;
- `alert-wrong_release_receipt.receipt.json`;
- `alert-worker_stale.receipt.json`;
- `alert-stuck_jobs.receipt.json`.

Each receipt contains exactly `schema_version`, `status`, `alert_class`, `code`,
`attempt_count`, `observed_at`, `delivered_at`, `release_id`, `fingerprint`, and
`http_status`. Network errors and non-2xx statuses are retried at most three
times with bounded timeout/backoff. Response bodies are never read into output
or receipts. A delivered receipt with the same deterministic fingerprint
suppresses another POST. An inactive class becomes `resolved`, so a later
recurrence is deliverable. Failed receipts do not suppress a later invocation.

### Inert systemd examples

The reviewed examples use a five-minute persistent user timer and a mode-`0077`
oneshot service. Repository changes do not install, enable, or start them.
Static review and inspection are safe:

```bash
systemd-analyze verify \
  deploy/systemd/user/novel-tnn-alert-dispatch.service \
  deploy/systemd/user/novel-tnn-alert-dispatch.timer
systemctl --user is-enabled novel-tnn-alert-dispatch.timer || true
systemctl --user status novel-tnn-alert-dispatch.timer --no-pager || true
systemctl --user list-timers novel-tnn-alert-dispatch.timer --no-pager
```

Installing the examples, running `daemon-reload`, enabling/starting the timer,
or executing the service can change operator state or send an external request.
Each action requires explicit operator approval. Never use the synthetic
loopback HTTP exception for a production endpoint.

## Release build

Build API and worker from the same clean commit and release ID. Replace the
example variables with the reviewed release values.

```bash
set -euo pipefail
export NOVEL_GIT_SHA="$(git rev-parse HEAD)"
export NOVEL_BUILD_TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export NOVEL_RELEASE_ID="release-${NOVEL_GIT_SHA:0:12}"
export NOVEL_API_IMAGE_TAG="novel-pipeline-api:${NOVEL_RELEASE_ID}"
export NOVEL_WORKER_IMAGE_TAG="novel-pipeline-import-worker:${NOVEL_RELEASE_ID}"

docker build --target api \
  --build-arg NOVEL_GIT_SHA="$NOVEL_GIT_SHA" \
  --build-arg NOVEL_BUILD_TIMESTAMP="$NOVEL_BUILD_TIMESTAMP" \
  --build-arg NOVEL_RELEASE_ID="$NOVEL_RELEASE_ID" \
  --build-arg NOVEL_IMAGE_TAG="$NOVEL_API_IMAGE_TAG" \
  -t "$NOVEL_API_IMAGE_TAG" .

docker build --target import-worker \
  --build-arg NOVEL_GIT_SHA="$NOVEL_GIT_SHA" \
  --build-arg NOVEL_BUILD_TIMESTAMP="$NOVEL_BUILD_TIMESTAMP" \
  --build-arg NOVEL_RELEASE_ID="$NOVEL_RELEASE_ID" \
  --build-arg NOVEL_IMAGE_TAG="$NOVEL_WORKER_IMAGE_TAG" \
  -t "$NOVEL_WORKER_IMAGE_TAG" .
```

Record both immutable local image IDs before staging. At cutover, provide the
resolved image digests through `NOVEL_API_IMAGE_DIGEST` and
`NOVEL_WORKER_IMAGE_DIGEST`. API and worker must report the same release ID.

## Pre-deployment gate

1. Confirm the worktree is clean and the release commit was reviewed.
2. Run the complete repository verification gate.
3. Build both pinned images from that exact commit.
4. Run them against an isolated data volume and alternate loopback port.
5. Verify health, readiness, version, authenticated metrics, import, Reader,
   export, and backup-list smoke paths.
6. Run `scripts/check-runtime-contract.py` against both staging containers.
7. Confirm `tts.status=unavailable` on a host without supported CUDA and verify
   there is no CPU model load.
8. Record prior production image tags, IDs, release ID, and database schema.
9. Create and validate a fresh encrypted backup.
10. Obtain explicit operator approval before production restart or deployment.

## Cutover gate

After approval, update only the reviewed image variables and use the repository
Compose configuration. Do not edit Cloudflare, DNS, tunnel, or reverse-proxy
configuration as part of this workstream.

Immediately verify:

```text
local /api/health = 200
local /api/ready = 200 and not not_ready
public /api/health = 200
public /api/ready = 200 and not not_ready
API release ID = worker release ID = approved release ID
worker heartbeat is fresh and queue_claim_capable=true
authenticated metrics are available and redacted
container restart counts remain stable
```

## Rollback

Rollback is required if a mandatory probe fails, release IDs differ, the worker
cannot claim work, protected downloads fail, or logs show repeated startup or
database errors.

1. Stop new job creation through the existing operator procedure.
2. Preserve logs and record the failing image IDs and release payloads.
3. Restore the previously recorded API and worker image tags in the deployment
   environment; do not use a floating `latest` tag.
4. Recreate both services with the repository Compose configuration.
5. Re-run local health/readiness/version and authenticated smoke checks.
6. Re-enable job creation only after the worker heartbeat and release match are
   healthy.
7. Restore data only if a separately approved data rollback is actually
   required. This workstream introduces no database migration.

Never delete the current database, artifact tree, backup, or image during an
application rollback. Retain the failed images until the incident is reviewed.

### Recovery producer rollout and rollback

The backup timer is a final rollout action, not a preflight mechanism. Keep it
stopped through static config validation, the digest-pinned image-owned
publisher preflight, one manual backup, one isolated restore drill, and fresh
verification of both recovery receipts. Only then enable and start it and
require a non-empty `NextElapseUSecRealtime`:

```bash
set -euo pipefail
: "${RECOVERY_ROLLBACK_DIR:?run the production runbook snapshot block first}"

systemctl --user stop novel-tnn-backup.timer novel-tnn-backup.service
for unit in novel-tnn-backup.timer novel-tnn-backup.service; do
  state="$(systemctl --user show "$unit" --property=ActiveState --value)"
  [[ "$state" == "inactive" ]] || { printf '%s is %s, expected inactive\n' "$unit" "$state" >&2; exit 1; }
done

[[ -d "$RECOVERY_ROLLBACK_DIR" && ! -L "$RECOVERY_ROLLBACK_DIR" ]]
[[ "$(stat --format='%u:%a' -- "$RECOVERY_ROLLBACK_DIR")" == "$(id -u):700" ]]
[[ -f "$RECOVERY_ROLLBACK_DIR/SHA256SUMS" && ! -L "$RECOVERY_ROLLBACK_DIR/SHA256SUMS" ]]
[[ -f "$RECOVERY_ROLLBACK_DIR/rollback-presence.txt" && ! -L "$RECOVERY_ROLLBACK_DIR/rollback-presence.txt" ]]
(cd "$RECOVERY_ROLLBACK_DIR" && sha256sum --check SHA256SUMS)
for runner in production_backup.sh production_restore_drill.sh; do
  frozen="$RECOVERY_ROLLBACK_DIR/runners/$runner"
  [[ -f "$frozen" && ! -L "$frozen" && "$(stat --format='%a' -- "$frozen")" == "755" ]]
done
frozen_env="$RECOVERY_ROLLBACK_DIR/backup.env"
[[ -f "$frozen_env" && ! -L "$frozen_env" ]]
[[ "$(stat --format='%u:%a' -- "$frozen_env")" == "$(id -u):600" ]]
for unit in novel-tnn-backup.service novel-tnn-backup.timer novel-tnn-restore-drill.service; do
  frozen_unit="$RECOVERY_ROLLBACK_DIR/systemd-user/$unit"
  [[ -f "$frozen_unit" && ! -L "$frozen_unit" && "$(stat --format='%a' -- "$frozen_unit")" == "644" ]]
  if grep -Fxq "$unit drop-in=present" "$RECOVERY_ROLLBACK_DIR/rollback-presence.txt"; then
    frozen_drop_in="${frozen_unit}.d"
    [[ -d "$frozen_drop_in" && ! -L "$frozen_drop_in" ]]
    ! find "$frozen_drop_in" -type l -print -quit | grep -q .
  elif grep -Fxq "$unit drop-in=absent" "$RECOVERY_ROLLBACK_DIR/rollback-presence.txt"; then
    [[ ! -e "${frozen_unit}.d" && ! -L "${frozen_unit}.d" ]]
  else
    printf 'rollback presence is incomplete for %s\n' "$unit" >&2
    exit 1
  fi
done

set -a
. "$frozen_env"
set +a
backup_image_pattern='^([a-z0-9]+([.-][a-z0-9]+)*(:[0-9]{1,5})?/)?[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*@sha256:[0-9a-f]{64}$'
[[ "$BACKUP_IMAGE" != -* && "$BACKUP_IMAGE" =~ $backup_image_pattern ]]
[[ "$RECOVERY_PRODUCER_VERSION" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$ ]]
systemctl --user disable novel-tnn-backup.timer

set -a
. "$HOME/.config/novel-tnn/backup.env"
set +a
[[ "$BACKUP_IMAGE" != -* && "$BACKUP_IMAGE" =~ $backup_image_pattern ]]
[[ "$RECOVERY_PRODUCER_VERSION" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$ ]]
scripts/production_backup.sh --validate-config
scripts/production_restore_drill.sh --validate-config

BACKUP_DATA_ROOT_IDENTITY="$(stat --format='%d:%i' -- "$BACKUP_DATA_DIR")"
docker run --rm --network none --user 10001:10001 \
  --mount "type=bind,src=${BACKUP_DATA_DIR},dst=/data-root,readonly" \
  --mount "type=bind,src=${BACKUP_DATA_DIR}/logs/runtime,dst=/receipts" \
  -- "$BACKUP_IMAGE" \
  python -m scripts.verify_recovery_publisher \
  --data-root /data-root \
  --receipt-dir /receipts \
  --expected-release "$RECOVERY_PRODUCER_VERSION" \
  --expected-data-root-identity "$BACKUP_DATA_ROOT_IDENTITY"

scripts/production_backup.sh
scripts/production_restore_drill.sh

.venv/bin/python - "$BACKUP_DATA_DIR" "$RECOVERY_PRODUCER_VERSION" <<'PY'
from pathlib import Path
import sys
from app.recovery_receipts import read_recovery_receipt

for kind in ("external_backup", "restore_drill"):
    result = read_recovery_receipt(Path(sys.argv[1]), kind, expected_release=sys.argv[2])
    if result["state"] != "fresh":
        raise SystemExit(f"{kind} receipt is not fresh")
PY

systemctl --user enable --now novel-tnn-backup.timer
systemctl --user is-enabled --quiet novel-tnn-backup.timer
[[ "$(systemctl --user show novel-tnn-backup.timer --property=ActiveState --value)" == "active" ]]
backup_service_state="$(systemctl --user show novel-tnn-backup.service --property=ActiveState --value)"
[[ -n "$backup_service_state" && "$backup_service_state" != "failed" ]]
next_elapse="$(systemctl --user show novel-tnn-backup.timer \
  --property=NextElapseUSecRealtime --value)"
[[ -n "$next_elapse" && "$next_elapse" != "n/a" ]]
printf 'NextElapseUSecRealtime=%s\n' "$next_elapse"
systemctl --user list-timers novel-tnn-backup.timer
```

Before rollout, use the existing **Stage the schedule with the timer stopped**
block in `docs/production-backup-restore-runbook.md`. It stops and verifies both
the timer and service before staging mutation, freezes both runner files, all
three user units and their drop-in presence, and private mode-0600 `backup.env`
in a mode-0700 rollback directory, then verifies its SHA-256 manifest and both
mandatory pins. That snapshot is authoritative for `BACKUP_IMAGE` and
`RECOVERY_PRODUCER_VERSION`.

If a recovery gate or the timer verification fails, execute this rollback with
the pre-rollout directory. It preserves displaced state instead of deleting
it:

```bash
set -euo pipefail
export RECOVERY_ROLLBACK_DIR=/home/thenam176/.local/state/novel-tnn/recovery-rollout-YYYYMMDDTHHMMSSZ

systemctl --user stop novel-tnn-backup.timer novel-tnn-backup.service
for unit in novel-tnn-backup.timer novel-tnn-backup.service; do
  state="$(systemctl --user show "$unit" --property=ActiveState --value)"
  [[ "$state" == "inactive" ]] || { printf '%s is %s, expected inactive\n' "$unit" "$state" >&2; exit 1; }
done

[[ -d "$RECOVERY_ROLLBACK_DIR" && ! -L "$RECOVERY_ROLLBACK_DIR" ]]
[[ "$(stat --format='%u:%a' -- "$RECOVERY_ROLLBACK_DIR")" == "$(id -u):700" ]]
[[ -f "$RECOVERY_ROLLBACK_DIR/SHA256SUMS" && ! -L "$RECOVERY_ROLLBACK_DIR/SHA256SUMS" ]]
[[ -f "$RECOVERY_ROLLBACK_DIR/rollback-presence.txt" && ! -L "$RECOVERY_ROLLBACK_DIR/rollback-presence.txt" ]]
(cd "$RECOVERY_ROLLBACK_DIR" && sha256sum --check SHA256SUMS)

for runner in production_backup.sh production_restore_drill.sh; do
  frozen="$RECOVERY_ROLLBACK_DIR/runners/$runner"
  [[ -f "$frozen" && ! -L "$frozen" && "$(stat --format='%a' -- "$frozen")" == "755" ]]
done
frozen_env="$RECOVERY_ROLLBACK_DIR/backup.env"
[[ -f "$frozen_env" && ! -L "$frozen_env" ]]
[[ "$(stat --format='%u:%a' -- "$frozen_env")" == "$(id -u):600" ]]
set -a
. "$frozen_env"
set +a
frozen_backup_image="$BACKUP_IMAGE"
frozen_producer_version="$RECOVERY_PRODUCER_VERSION"
backup_image_pattern='^([a-z0-9]+([.-][a-z0-9]+)*(:[0-9]{1,5})?/)?[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*@sha256:[0-9a-f]{64}$'
[[ "$frozen_backup_image" != -* && "$frozen_backup_image" =~ $backup_image_pattern ]]
[[ "$frozen_producer_version" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$ ]]

for unit in novel-tnn-backup.service novel-tnn-backup.timer novel-tnn-restore-drill.service; do
  frozen_unit="$RECOVERY_ROLLBACK_DIR/systemd-user/$unit"
  [[ -f "$frozen_unit" && ! -L "$frozen_unit" && "$(stat --format='%a' -- "$frozen_unit")" == "644" ]]
  if grep -Fxq "$unit drop-in=present" "$RECOVERY_ROLLBACK_DIR/rollback-presence.txt"; then
    frozen_drop_in="${frozen_unit}.d"
    [[ -d "$frozen_drop_in" && ! -L "$frozen_drop_in" ]]
    ! find "$frozen_drop_in" -type l -print -quit | grep -q .
  elif grep -Fxq "$unit drop-in=absent" "$RECOVERY_ROLLBACK_DIR/rollback-presence.txt"; then
    [[ ! -e "${frozen_unit}.d" && ! -L "${frozen_unit}.d" ]]
  else
    printf 'rollback presence is incomplete for %s\n' "$unit" >&2
    exit 1
  fi
done

systemctl --user disable novel-tnn-backup.timer
umask 077
rollback_attempt="$(mktemp -d "$RECOVERY_ROLLBACK_DIR/rejected-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"
install -d -m 0700 "$rollback_attempt/runners" "$rollback_attempt/systemd-user"

for runner in production_backup.sh production_restore_drill.sh; do
  deployed="/home/thenam176/Novel-TNN/scripts/$runner"
  cp -a -- "$deployed" "$rollback_attempt/runners/"
  install -m 0755 "$RECOVERY_ROLLBACK_DIR/runners/$runner" "$deployed"
done
cp -a -- "$HOME/.config/novel-tnn/backup.env" "$rollback_attempt/backup.env"
install -m 0600 "$RECOVERY_ROLLBACK_DIR/backup.env" "$HOME/.config/novel-tnn/backup.env"

for unit in novel-tnn-backup.service novel-tnn-backup.timer novel-tnn-restore-drill.service; do
  deployed="$HOME/.config/systemd/user/$unit"
  if [[ -f "$deployed" ]]; then
    mv -- "$deployed" "$rollback_attempt/systemd-user/"
  fi
  if [[ -d "${deployed}.d" ]]; then
    mv -- "${deployed}.d" "$rollback_attempt/systemd-user/"
  fi
  if [[ -f "$RECOVERY_ROLLBACK_DIR/systemd-user/$unit" ]]; then
    install -m 0644 "$RECOVERY_ROLLBACK_DIR/systemd-user/$unit" "$deployed"
  fi
  if [[ -d "$RECOVERY_ROLLBACK_DIR/systemd-user/${unit}.d" ]]; then
    cp -a -- "$RECOVERY_ROLLBACK_DIR/systemd-user/${unit}.d" \
      "$HOME/.config/systemd/user/"
  fi
done

systemctl --user daemon-reload
systemctl --user stop novel-tnn-backup.timer novel-tnn-backup.service
systemctl --user disable novel-tnn-backup.timer
for unit in novel-tnn-backup.timer novel-tnn-backup.service; do
  [[ "$(systemctl --user show "$unit" --property=ActiveState --value)" == "inactive" ]]
done

for runner in production_backup.sh production_restore_drill.sh; do
  cmp --silent "$RECOVERY_ROLLBACK_DIR/runners/$runner" \
    "/home/thenam176/Novel-TNN/scripts/$runner"
done
cmp --silent "$RECOVERY_ROLLBACK_DIR/backup.env" "$HOME/.config/novel-tnn/backup.env"
set -a
. "$HOME/.config/novel-tnn/backup.env"
set +a
[[ "$BACKUP_IMAGE" == "$frozen_backup_image" ]]
[[ "$RECOVERY_PRODUCER_VERSION" == "$frozen_producer_version" ]]
printf 'rollback snapshot retained: %s\nrejected rollout retained: %s\n' \
  "$RECOVERY_ROLLBACK_DIR" "$rollback_attempt"
```

Do not automatically delete or overwrite recovery receipts, backup objects,
restore-drill directories, validation reports, logs, rejected runner bytes,
drop-ins, or images. There is no automatic evidence deletion. Any evidence
cleanup requires separate operator approval.

## Recovery receipt contract

Runtime reads only these fixed paths below `DATA_DIR`:

- `logs/runtime/external-backup.receipt.json`
- `logs/runtime/restore-drill.receipt.json`

Each receipt has exactly `status`, `completed_at`, `archive_hash_id`,
`validation_counts`, and `producer_version`. Status is `passed`, completion time
is UTC, and the hash identifier is a lowercase SHA-256 identifier. Validation
counts use a bounded allowlist and describe checks that were actually executed.
The runtime requires an exact successful contract per receipt kind before it can
classify a receipt as fresh:

- External backup: `archive_verified=1`, `metadata_verified=1`,
  `checksum_verified=1`, `remote_uploads_verified=3`, and
  `remote_metadata_verified=2`.
- Restore drill: `checksum_verified=1`, `sqlite_integrity_checks=1`,
  `foreign_key_violations=0`, `artifact_paths_scanned` present and non-negative,
  `api_readiness_checks=1`, and `authenticated_reader_smokes=1`.

Missing, unsuccessful, or cross-kind counters make the receipt `corrupt`.
The producer version must match `NOVEL_RELEASE_ID` for a fresh state.

The maximum ages are configured with
`NOVEL_EXTERNAL_BACKUP_MAX_AGE_SECONDS` (default `172800`) and
`NOVEL_RESTORE_DRILL_MAX_AGE_SECONDS` (default `691200`). Future timestamps use
`NOVEL_RECOVERY_RECEIPT_FUTURE_SKEW_SECONDS` (default `300`). Invalid overrides
fall back to these safe defaults.

`scripts/production_backup.sh` publishes only after local metadata and checksum
verification, off-site upload, remote archive and metadata re-download
comparison, and remote retention rotation succeed. A verification or rotation
failure leaves the previous receipt unchanged.
`scripts/production_restore_drill.sh` publishes only after SQLite integrity,
foreign-key, artifact, API readiness, and authenticated Reader checks succeed.
Its drill root must already exist as a canonical, non-symlink, invoking-UID
owned mode-0700 directory outside live data. Random children are created
relative to an `O_DIRECTORY|O_NOFOLLOW` descriptor and root/child identities
are checked around pathname use. Docker bind sources are still resolved by the
daemon, which cannot portably inherit that descriptor; same-UID pathname
substitution between the final check and daemon resolution remains within the
documented host-account trust boundary.
Both producers publish through the pinned `BACKUP_IMAGE` as UID/GID
`10001:10001`, with networking disabled. They mount the full data root read-only
at `/data-root` for captured device/inode identity and component checks. The
dedicated `DATA_DIR/logs/runtime` directory is mounted separately at
`/receipts` and is the only writable recovery metadata mount. The directory
must already exist, resolve to that fixed location, and be owned for UID 10001
access. The preflight helper comes from the exact digest-pinned reviewed image,
not host source. `BACKUP_IMAGE` and `RECOVERY_PRODUCER_VERSION` are mandatory
explicit configuration and must be migrated together; the producer version is
verified against the image's embedded `NOVEL_RELEASE_ID`, and operators must set
both to the intended API release ID. The producer does not receive API
credentials or query the running service. If the running API uses another
release, its bounded receipt reader classifies the result as `wrong_release`
and emits the stable recovery alert.
The publisher receives only the archive hash identifier, validation counts,
producer version, an optional bounded canonical UTC completion timestamp, and
its fixed in-container output path. Backup secrets,
R2 credentials, archive and report paths, and `production.env` are never passed
to the publisher container.

Publication uses a mode `0700` parent, a mode `0600` temporary file, file fsync,
atomic replacement, and directory fsync. Runtime rejects symlinks, non-regular
files, oversized payloads, unknown keys, and malformed values.

The API never reads or returns backup archives, checksum sidecars, backup
directories, archive names, remote object keys, report paths, passphrases, R2
configuration, credentials, parser exceptions, or arbitrary receipt fields.
Only authenticated metrics and system status expose the bounded derived state,
age, safe completion timestamp, hash identifier, allowlisted counts, producer
version, and threshold.

Keep the backup timer stopped until clean committed runner bytes and a reviewed
helper-containing image have been deployed, both mandatory pins are explicit,
the image-owned preflight succeeds, the manual backup and restore drill pass,
and both receipts are freshly verified. An older image cannot run these
runners.
