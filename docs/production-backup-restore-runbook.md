# Production Backup and Restore Drill Runbook

This runbook is for the native-WSL production deployment. It keeps all backup
credentials outside the repository and never restores into live `data/`.

## Ownership and retention

The `novel-tnn-backup` and `novel-tnn-restore-drill` systemd **user** services
are owned by `thenam176`. They invoke a short-lived Docker container because
live data is deliberately private to container UID/GID `10001`.

Default policy:

| Location | Retention | Contents |
|---|---:|---|
| Local WSL backup directory | 14 encrypted archives | Encrypted archive, READY sidecar, SHA-256 file |
| Private Cloudflare R2 prefix | 35 encrypted archives | The same three files |
| Restore drill | No automatic deletion | Isolated restored data plus validation evidence |

The runner deletes only expired files whose names match
`novel-pipeline-backup-*.tar.gz.enc` and their matching sidecar/checksum files.
It never removes populated drill data or evidence. If pathname identity changes
during descriptor-backed creation, it attempts only to remove the newly created
empty child relative to the held root descriptor. Any other drill cleanup
requires separate operator approval.

## One-time secure configuration

R2 must be enabled in the Cloudflare account before enabling the timer. Create
a **private** bucket named `novel-tnn-backups` (or another lowercase bucket
name chosen for this deployment) and an R2 S3 API token with **Object Read &
Write** permission scoped only to that bucket. Do not attach a public bucket
domain or a custom domain to backup data.

Create the private configuration from the tracked template:

```bash
set -euo pipefail
install -d -m 700 "$HOME/.config/novel-tnn"
install -m 600 deploy/production/backup.env.example \
  "$HOME/.config/novel-tnn/backup.env"
install -d -m 0700 "$HOME/Novel-TNN-restore-drills"
```

Set these values in the external file:

- `BACKUP_PASSPHRASE`: a random passphrase retained in the operator password
  manager, not in Git or shell history.
- `R2_ACCOUNT_ID`: the 32-character Cloudflare account ID.
- `R2_BUCKET`: the private bucket name.
- `R2_PREFIX`: a non-public object-key prefix such as
  `novel-tnn-production`.
- `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY`: the R2 S3 API credential,
  scoped only to the selected bucket. The secret is displayed only once by
  Cloudflare; record it directly in `backup.env` without placing it in shell
  history or chat.
- `BACKUP_IMAGE`: the immutable image pin reviewed for the production release.
- `RECOVERY_PRODUCER_VERSION`: the exact release ID embedded in that image and
  intended for the running API. Do not infer it from an image tag.

Both values are mandatory. Existing installations must explicitly migrate
`BACKUP_IMAGE` and `RECOVERY_PRODUCER_VERSION`; there is no legacy image
fallback. Build the reviewed image from the clean committed source so it
contains `scripts.verify_recovery_publisher`, then pin its exact digest. The
runners execute the helper from that exact image and never mount a mutable host
helper.

Keep `BACKUP_DATA_DIR=/home/thenam176/Novel-TNN/data`, local output under
`$HOME/.local/share/novel-tnn-backups`, and the current production image pin.
Provision the dedicated receipt directory without granting the API access to
the archive tree:

```bash
set -euo pipefail
sudo install -d -o 10001 -g 10001 -m 0700 \
  /home/thenam176/Novel-TNN/data/logs/runtime
```

Before every release, verify that `BACKUP_IMAGE`, its embedded
`NOVEL_RELEASE_ID`, `RECOVERY_PRODUCER_VERSION`, and the intended API release ID
are identical. A receipt from a different release is deliberately classified
as `wrong_release` by the authenticated runtime status endpoints.

## Stage the schedule with the timer stopped

Stop both the timer and its service and prove both are inactive before creating
the staging snapshot or replacing any recovery runner, unit, drop-in, or
external configuration. Capture and hash the complete currently deployed state
first. Keep the printed rollback directory for the entire rollout and
incident-review window:

```bash
set -euo pipefail

recovery_units=(
  novel-tnn-backup.service
  novel-tnn-backup.timer
  novel-tnn-restore-drill.service
)
systemctl --user stop novel-tnn-backup.timer novel-tnn-backup.service
for unit in novel-tnn-backup.timer novel-tnn-backup.service; do
  state="$(systemctl --user show "$unit" --property=ActiveState --value)"
  [[ "$state" == "inactive" ]] || { printf '%s is %s, expected inactive\n' "$unit" "$state" >&2; exit 1; }
done
systemctl --user disable novel-tnn-backup.timer

export RECOVERY_ROLLBACK_DIR="$HOME/.local/state/novel-tnn/recovery-rollout-$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
install -d -m 0700 \
  "$RECOVERY_ROLLBACK_DIR/runners" \
  "$RECOVERY_ROLLBACK_DIR/systemd-user"

for runner in production_backup.sh production_restore_drill.sh; do
  deployed="/home/thenam176/Novel-TNN/scripts/$runner"
  [[ -f "$deployed" && ! -L "$deployed" ]] || { printf 'unsafe runner: %s\n' "$runner" >&2; exit 1; }
  install -m 0755 "$deployed" "$RECOVERY_ROLLBACK_DIR/runners/$runner"
done

private_env="$HOME/.config/novel-tnn/backup.env"
[[ -f "$private_env" && ! -L "$private_env" ]] || { printf 'backup.env is not a regular file\n' >&2; exit 1; }
[[ "$(stat --format='%u:%a' -- "$private_env")" == "$(id -u):600" ]] \
  || { printf 'backup.env must be invoking-UID owned mode 0600\n' >&2; exit 1; }
install -m 0600 "$private_env" "$RECOVERY_ROLLBACK_DIR/backup.env"

: >"$RECOVERY_ROLLBACK_DIR/rollback-presence.txt"
for unit in "${recovery_units[@]}"; do
  unit_path="$HOME/.config/systemd/user/$unit"
  drop_in_path="${unit_path}.d"
  [[ -f "$unit_path" && ! -L "$unit_path" ]] || { printf 'unsafe or missing unit: %s\n' "$unit" >&2; exit 1; }
  install -m 0644 "$unit_path" "$RECOVERY_ROLLBACK_DIR/systemd-user/$unit"
  if [[ -d "$drop_in_path" ]]; then
    [[ ! -L "$drop_in_path" ]] || { printf 'symlinked drop-in directory: %s\n' "$unit" >&2; exit 1; }
    if find "$drop_in_path" -type l -print -quit | grep -q .; then
      printf 'symlink in drop-ins: %s\n' "$unit" >&2
      exit 1
    fi
    cp -a -- "$drop_in_path" "$RECOVERY_ROLLBACK_DIR/systemd-user/"
    printf '%s drop-in=present\n' "$unit" >>"$RECOVERY_ROLLBACK_DIR/rollback-presence.txt"
  else
    [[ ! -e "$drop_in_path" && ! -L "$drop_in_path" ]] \
      || { printf 'invalid drop-in path: %s\n' "$unit" >&2; exit 1; }
    printf '%s drop-in=absent\n' "$unit" >>"$RECOVERY_ROLLBACK_DIR/rollback-presence.txt"
  fi
done

(
  cd "$RECOVERY_ROLLBACK_DIR"
  find backup.env rollback-presence.txt runners systemd-user -type f -print0 \
    | sort -z \
    | xargs -0 sha256sum
) >"$RECOVERY_ROLLBACK_DIR/SHA256SUMS"
chmod 0600 "$RECOVERY_ROLLBACK_DIR/SHA256SUMS" "$RECOVERY_ROLLBACK_DIR/rollback-presence.txt"
(cd "$RECOVERY_ROLLBACK_DIR" && sha256sum --check SHA256SUMS)

set -a
. "$RECOVERY_ROLLBACK_DIR/backup.env"
set +a
backup_image_pattern='^([a-z0-9]+([.-][a-z0-9]+)*(:[0-9]{1,5})?/)?[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*@sha256:[0-9a-f]{64}$'
[[ "$BACKUP_IMAGE" != -* && "$BACKUP_IMAGE" =~ $backup_image_pattern ]] \
  || { printf 'frozen BACKUP_IMAGE is not digest pinned\n' >&2; exit 1; }
[[ "$RECOVERY_PRODUCER_VERSION" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$ ]] \
  || { printf 'frozen RECOVERY_PRODUCER_VERSION is invalid\n' >&2; exit 1; }
printf 'rollback directory: %s\n' "$RECOVERY_ROLLBACK_DIR"
```

Deploy only clean committed runner bytes and reviewed units, but do not enable
or start the timer. The timer must remain stopped through every gate below:

```bash
set -euo pipefail
systemctl --user stop novel-tnn-backup.timer novel-tnn-backup.service
for unit in novel-tnn-backup.timer novel-tnn-backup.service; do
  state="$(systemctl --user show "$unit" --property=ActiveState --value)"
  [[ "$state" == "inactive" ]] || { printf '%s is %s, expected inactive\n' "$unit" "$state" >&2; exit 1; }
done
systemctl --user disable novel-tnn-backup.timer

chmod 0755 scripts/production_backup.sh scripts/production_restore_drill.sh
install -d -m 0700 "$HOME/.config/systemd/user"
install -m 0644 deploy/systemd/user/novel-tnn-backup.service \
  deploy/systemd/user/novel-tnn-backup.timer \
  deploy/systemd/user/novel-tnn-restore-drill.service \
  "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user stop novel-tnn-backup.timer novel-tnn-backup.service
for unit in novel-tnn-backup.timer novel-tnn-backup.service; do
  [[ "$(systemctl --user show "$unit" --property=ActiveState --value)" == "inactive" ]]
done
```

Load the private configuration into the operator shell without printing it,
then run both static validations. These commands perform no network or Docker
operation:

```bash
set -euo pipefail
for unit in novel-tnn-backup.timer novel-tnn-backup.service; do
  [[ "$(systemctl --user show "$unit" --property=ActiveState --value)" == "inactive" ]]
done
set -a
. "$HOME/.config/novel-tnn/backup.env"
set +a
/home/thenam176/Novel-TNN/scripts/production_backup.sh --validate-config
/home/thenam176/Novel-TNN/scripts/production_restore_drill.sh --validate-config
```

Run the image-owned publisher preflight while the timer remains stopped. It
receives no backup credentials and has no network:

```bash
set -euo pipefail
for unit in novel-tnn-backup.timer novel-tnn-backup.service; do
  [[ "$(systemctl --user show "$unit" --property=ActiveState --value)" == "inactive" ]]
done
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
```

Each recovery preflight mounts the full data root read-only to verify its
captured device/inode identity and the `logs/runtime` path component by
component. The receipt directory is mounted separately at `/receipts` and is
the only writable recovery metadata mount. Normal backup creation also mounts
the full data root read-only and rechecks its identity inside the same pinned
image container immediately before archive creation.

## Manual backup and restore gate

Run the first backup manually, followed by the restore drill, without starting
the timer. Each runner repeats the image-owned preflight before processing an
archive:

```bash
set -euo pipefail
for unit in novel-tnn-backup.timer novel-tnn-backup.service; do
  [[ "$(systemctl --user show "$unit" --property=ActiveState --value)" == "inactive" ]]
done
/home/thenam176/Novel-TNN/scripts/production_backup.sh
/home/thenam176/Novel-TNN/scripts/production_restore_drill.sh
for unit in novel-tnn-backup.timer novel-tnn-backup.service; do
  [[ "$(systemctl --user show "$unit" --property=ActiveState --value)" == "inactive" ]]
done
```

Success requires all of the following:

1. An encrypted `.tar.gz.enc` archive with a matching READY `.manifest.json`.
2. A local `.sha256` file that verifies before upload.
3. HTTPS-only SigV4 upload to the private R2 bucket of archive, sidecar, and
   checksum.
4. Re-download of the R2 archive, checksum, and READY sidecar, each compared
   byte for byte with the verified local objects.

The runner uploads small archives as one R2 object and automatically switches
to the R2 multipart protocol at the configured threshold (5 GiB by default).
Multipart uploads use bounded 256 MiB parts, record the returned ETags in the
completion request, and abort an incomplete upload on failure.  It refuses an
archive that would exceed R2's 10,000-part limit rather than publishing a
partial object. `--upload-existing ARCHIVE_BASENAME` safely retries only the
off-site upload of an already verified local archive; it does not create a
second archive. A successful retry preserves the UTC creation time encoded in
the canonical archive basename as the external-backup receipt `completed_at`;
it can never refresh the apparent age of an old snapshot.

The passphrase is never written to output. The archive itself contains no
production environment file; encryption protects private application data when
the archive leaves the host.

## Isolated restore drill

The restore drill selects the newest encrypted archive, verifies its local
checksum/READY metadata, and creates a fresh directory below the already
existing `$HOME/Novel-TNN-restore-drills` without writing to live data. The
configured root must be canonical, contain no symlink component, be owned by
the invoking UID, and have exact mode `0700`; it is never created by the
runner. Static validation rejects a drill root equal to or below the canonical
live data directory.

Creation opens the validated root with `O_DIRECTORY|O_NOFOLLOW`, creates the
random child relative to that descriptor, and checks root and child
device/inode identity before and after pathname-based use. A Docker daemon does
not inherit the operator process's directory descriptor, so a portable
descriptor-backed bind mount is not available without daemon-specific
assumptions. Exact owner/mode checks prevent other UIDs from substituting the
path; an attacker already running as the same UID remains inside the documented
host-account trust boundary and could still race between a final identity check
and daemon pathname resolution.

It validates:

- SQLite `integrity_check` and `foreign_key_check`;
- all populated approved artifact-path fields after an in-drill remap from the
  production data root;
- book and chapter row counts;
- an API container launched with `--network none`, including `/api/health` and
  `/api/ready`;
- a read-only authenticated Reader smoke test against the restored API.

The drill leaves its restored files and a validation JSON report in place.
Do not delete either without a separate cleanup approval.

Verify both receipts are fresh for the reviewed producer version before the
timer is enabled:

```bash
set -euo pipefail
.venv/bin/python - "$BACKUP_DATA_DIR" "$RECOVERY_PRODUCER_VERSION" <<'PY'
from pathlib import Path
import sys

from app.recovery_receipts import read_recovery_receipt

data_dir = Path(sys.argv[1])
expected_release = sys.argv[2]
for kind in ("external_backup", "restore_drill"):
    receipt = read_recovery_receipt(data_dir, kind, expected_release=expected_release)
    if receipt["state"] != "fresh":
        raise SystemExit(f"{kind} receipt is not fresh")
    print(kind, receipt["state"], receipt["completed_at"])
PY
```

Only after configuration validation, the image-owned preflight, the manual
backup, the isolated restore drill, and both fresh receipt checks have passed
may the timer be enabled and started. Verify that systemd computed a real next
elapse time:

```bash
set -euo pipefail
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

The timer runs daily at 03:15 with a bounded randomized delay and catches up
after a missed WSL session. It uses `UMask=0077`; archive, sidecar, checksum,
and external configuration are mode `0600`.

## Recovery rollout rollback

If any gate fails, keep the timer stopped. Set `RECOVERY_ROLLBACK_DIR` to the
printed pre-rollout directory. These commands first preserve the rejected
runner, config, units, and drop-ins, then restore the frozen runner bytes,
`BACKUP_IMAGE`, `RECOVERY_PRODUCER_VERSION`, and systemd state:

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
install -m 0600 "$RECOVERY_ROLLBACK_DIR/backup.env" \
  "$HOME/.config/novel-tnn/backup.env"

for unit in novel-tnn-backup.service novel-tnn-backup.timer novel-tnn-restore-drill.service; do
  deployed="$HOME/.config/systemd/user/$unit"
  deployed_drop_in="${deployed}.d"
  if [[ -f "$deployed" ]]; then
    mv -- "$deployed" "$rollback_attempt/systemd-user/"
  fi
  if [[ -d "$deployed_drop_in" ]]; then
    mv -- "$deployed_drop_in" "$rollback_attempt/systemd-user/"
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

Do not automatically delete or overwrite receipts, archives, restored drill
directories, validation reports, logs, rejected rollout bytes, or images.
There is no automatic evidence deletion. Evidence cleanup requires separate
operator approval. Revalidate the restored configuration before any separately
approved attempt to re-enable the timer.
