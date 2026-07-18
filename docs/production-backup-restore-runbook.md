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

Keep `BACKUP_DATA_DIR=/home/thenam176/Novel-TNN/data`, local output under
`$HOME/.local/share/novel-tnn-backups`, and the current production image pin.
Before enabling the timer, validate the external configuration; this performs
no network or Docker operation:

```bash
/home/thenam176/Novel-TNN/scripts/production_backup.sh --validate-config
```

## Install and enable the schedule

```bash
chmod 0755 scripts/production_backup.sh scripts/production_restore_drill.sh
install -d -m 700 "$HOME/.config/systemd/user"
install -m 644 deploy/systemd/user/novel-tnn-backup.service \
  deploy/systemd/user/novel-tnn-backup.timer \
  deploy/systemd/user/novel-tnn-restore-drill.service \
  "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now novel-tnn-backup.timer
systemctl --user list-timers novel-tnn-backup.timer
```

The timer runs daily at 03:15 with a bounded randomized delay and catches up
after a missed WSL session. It uses `UMask=0077`; archive, sidecar, checksum,
and external configuration are mode `0600`.

## Backup verification

Run the first backup manually before relying on its timer:

```bash
systemctl --user start novel-tnn-backup.service
journalctl --user -u novel-tnn-backup.service -n 100 --no-pager
```

Success requires all of the following:

1. An encrypted `.tar.gz.enc` archive with a matching READY `.manifest.json`.
2. A local `.sha256` file that verifies before upload.
3. HTTPS-only SigV4 upload to the private R2 bucket of archive, sidecar, and
   checksum.
4. Re-download of the R2 checksum and READY sidecar, each compared byte for
   byte with local metadata.

The runner uploads small archives as one R2 object and automatically switches
to the R2 multipart protocol at the configured threshold (5 GiB by default).
Multipart uploads use bounded 256 MiB parts, record the returned ETags in the
completion request, and abort an incomplete upload on failure.  It refuses an
archive that would exceed R2's 10,000-part limit rather than publishing a
partial object.  `--upload-existing ARCHIVE_BASENAME` safely retries only the
off-site upload of an already verified local archive; it does not create a
second archive.

The passphrase is never written to output. The archive itself contains no
production environment file; encryption protects private application data when
the archive leaves the host.

## Isolated restore drill

The restore drill selects the newest encrypted archive, verifies its local
checksum/READY metadata, creates a fresh directory below
`$HOME/Novel-TNN-restore-drills`, and never writes to live data.

```bash
systemctl --user start novel-tnn-restore-drill.service
journalctl --user -u novel-tnn-restore-drill.service -n 150 --no-pager
```

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
