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
It never removes a drill directory. Drill cleanup requires separate operator
approval.

## One-time secure configuration

R2 must be enabled in the Cloudflare account before enabling the timer. Create
a **private** bucket named `novel-tnn-backups` (or another lowercase bucket
name chosen for this deployment) and an R2 S3 API token with **Object Read &
Write** permission scoped only to that bucket. Do not attach a public bucket
domain or a custom domain to backup data.

Create the private configuration from the tracked template:

```bash
install -d -m 700 "$HOME/.config/novel-tnn"
install -m 600 deploy/production/backup.env.example \
  "$HOME/.config/novel-tnn/backup.env"
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
sudo install -d -o 10001 -g 10001 -m 0700 \
  /home/thenam176/Novel-TNN/data/logs/runtime
```

Before every release, verify that `BACKUP_IMAGE`, its embedded
`NOVEL_RELEASE_ID`, `RECOVERY_PRODUCER_VERSION`, and the intended API release ID
are identical. A receipt from a different release is deliberately classified
as `wrong_release` by the authenticated runtime status endpoints.

## Stage the schedule with the timer stopped

Stop and disable the timer before replacing any recovery runner, unit, drop-in,
or external configuration. Capture the currently deployed bytes first. Keep
the printed rollback directory for the entire rollout and incident-review
window:

```bash
systemctl --user disable --now novel-tnn-backup.timer

export RECOVERY_ROLLBACK_DIR="$HOME/.local/state/novel-tnn/recovery-rollout-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 \
  "$RECOVERY_ROLLBACK_DIR/runners" \
  "$RECOVERY_ROLLBACK_DIR/systemd-user"
install -m 0755 \
  /home/thenam176/Novel-TNN/scripts/production_backup.sh \
  /home/thenam176/Novel-TNN/scripts/production_restore_drill.sh \
  "$RECOVERY_ROLLBACK_DIR/runners/"
install -m 0600 "$HOME/.config/novel-tnn/backup.env" \
  "$RECOVERY_ROLLBACK_DIR/backup.env"

for unit in novel-tnn-backup.service novel-tnn-backup.timer novel-tnn-restore-drill.service; do
  unit_path="$HOME/.config/systemd/user/$unit"
  drop_in_path="${unit_path}.d"
  if [[ -f "$unit_path" ]]; then
    cp -a -- "$unit_path" "$RECOVERY_ROLLBACK_DIR/systemd-user/"
  fi
  if [[ -d "$drop_in_path" ]]; then
    cp -a -- "$drop_in_path" "$RECOVERY_ROLLBACK_DIR/systemd-user/"
  fi
done
printf 'rollback directory: %s\n' "$RECOVERY_ROLLBACK_DIR"
```

Deploy only clean committed runner bytes and reviewed units, but do not enable
or start the timer. The timer must remain stopped through every gate below:

```bash
chmod 0755 scripts/production_backup.sh scripts/production_restore_drill.sh
install -d -m 0700 "$HOME/.config/systemd/user"
install -m 0644 deploy/systemd/user/novel-tnn-backup.service \
  deploy/systemd/user/novel-tnn-backup.timer \
  deploy/systemd/user/novel-tnn-restore-drill.service \
  "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user disable --now novel-tnn-backup.timer
```

Load the private configuration into the operator shell without printing it,
then run both static validations. These commands perform no network or Docker
operation:

```bash
set -a
. "$HOME/.config/novel-tnn/backup.env"
set +a
/home/thenam176/Novel-TNN/scripts/production_backup.sh --validate-config
/home/thenam176/Novel-TNN/scripts/production_restore_drill.sh --validate-config
```

Run the image-owned publisher preflight while the timer remains stopped. It
receives no backup credentials and has no network:

```bash
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
/home/thenam176/Novel-TNN/scripts/production_backup.sh
/home/thenam176/Novel-TNN/scripts/production_restore_drill.sh
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
checksum/READY metadata, creates a fresh directory below
`$HOME/Novel-TNN-restore-drills`, and never writes to live data.
Static validation rejects a drill root equal to or below the canonical live
data directory, including an existing symlink alias into that tree.

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
systemctl --user enable --now novel-tnn-backup.timer
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
systemctl --user disable --now novel-tnn-backup.timer

export RECOVERY_ROLLBACK_DIR=/home/thenam176/.local/state/novel-tnn/recovery-rollout-YYYYMMDDTHHMMSSZ
rollback_attempt="$RECOVERY_ROLLBACK_DIR/rejected-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$rollback_attempt/runners" "$rollback_attempt/systemd-user"

for runner in production_backup.sh production_restore_drill.sh; do
  deployed="/home/thenam176/Novel-TNN/scripts/$runner"
  cp -a -- "$deployed" "$rollback_attempt/runners/"
  install -m 0755 "$RECOVERY_ROLLBACK_DIR/runners/$runner" "$deployed"
done

install -m 0600 "$HOME/.config/novel-tnn/backup.env" \
  "$rollback_attempt/backup.env"
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
systemctl --user disable --now novel-tnn-backup.timer
awk -F= '$1 == "BACKUP_IMAGE" || $1 == "RECOVERY_PRODUCER_VERSION" {print}' \
  "$HOME/.config/novel-tnn/backup.env"
```

Do not automatically delete or overwrite receipts, archives, restored drill
directories, validation reports, logs, rejected rollout bytes, or images.
There is no automatic evidence deletion. Evidence cleanup requires separate
operator approval. Revalidate the restored configuration before any separately
approved attempt to re-enable the timer.
