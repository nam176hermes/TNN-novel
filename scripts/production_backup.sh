#!/usr/bin/env bash
set -euo pipefail

# Invoked by the novel-tnn-backup systemd user service. The service runs as
# thenam176; Docker executes the short-lived backup container as root because
# live data deliberately belongs only to UID/GID 10001.

readonly RUNNER_NAME="novel-tnn production backup"
readonly BACKUP_NAME_PATTERN='^novel-pipeline-backup-[0-9]{8}-[0-9]{6}(-[A-Za-z0-9._-]+)?(-[a-f0-9]{12})?\.tar\.gz\.enc$'

fail() {
  printf '%s: %s\n' "$RUNNER_NAME" "$*" >&2
  exit 2
}

require_value() {
  local variable_name="$1"
  [[ -n "${!variable_name:-}" ]] || fail "${variable_name} is required"
}

require_positive_integer() {
  local variable_name="$1"
  [[ "${!variable_name:-}" =~ ^[1-9][0-9]*$ ]] || fail "${variable_name} must be a positive integer"
}

require_absolute_path() {
  local variable_name="$1"
  [[ "${!variable_name:-}" == /* ]] || fail "${variable_name} must be an absolute path"
}

validate_remote_destination() {
  [[ "$OFFSITE_SFTP_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || fail "OFFSITE_SFTP_HOST must be an SSH host alias"
  [[ "$OFFSITE_SFTP_DIR" =~ ^/[A-Za-z0-9._/-]*$ ]] || fail "OFFSITE_SFTP_DIR contains unsafe characters"
  [[ "$OFFSITE_SFTP_DIR" != *"//"* && "$OFFSITE_SFTP_DIR" != *"/../"* && "$OFFSITE_SFTP_DIR" != */.. ]] \
    || fail "OFFSITE_SFTP_DIR must not contain path traversal"
}

validate_config() {
  require_value BACKUP_PASSPHRASE
  require_value BACKUP_IMAGE
  require_value BACKUP_DATA_DIR
  require_value BACKUP_LOCAL_DIR
  require_value OFFSITE_SFTP_HOST
  require_value OFFSITE_SFTP_DIR
  require_positive_integer BACKUP_KEEP_LOCAL
  require_positive_integer BACKUP_KEEP_OFFSITE
  require_absolute_path BACKUP_DATA_DIR
  require_absolute_path BACKUP_LOCAL_DIR
  [[ -d "$BACKUP_DATA_DIR" ]] || fail "BACKUP_DATA_DIR does not exist"
  [[ "$BACKUP_IMAGE" != *[[:space:]]* ]] || fail "BACKUP_IMAGE must not contain whitespace"
  validate_remote_destination

  local data_root backup_root
  data_root="$(realpath -m "$BACKUP_DATA_DIR")"
  backup_root="$(realpath -m "$BACKUP_LOCAL_DIR")"
  [[ "$backup_root" != "$data_root" && "$backup_root" != "$data_root"/* ]] \
    || fail "BACKUP_LOCAL_DIR must not be inside BACKUP_DATA_DIR"
}

run_container_backup() {
  local archive_name
  archive_name="$(
    docker run --rm --network none --user 0:0 \
      --mount "type=bind,src=${BACKUP_DATA_DIR},dst=/data" \
      --mount "type=bind,src=${BACKUP_LOCAL_DIR},dst=/backups" \
      --env BACKUP_PASSPHRASE \
      --env "BACKUP_KEEP_LOCAL=${BACKUP_KEEP_LOCAL}" \
      --env "BACKUP_OWNER_UID=$(id -u)" \
      --env "BACKUP_OWNER_GID=$(id -g)" \
      "$BACKUP_IMAGE" \
      python -c '
import os
from pathlib import Path
from scripts.ops import backup_sidecar_path, create_encrypted_backup

archive = create_encrypted_backup(
    data_dir=Path("/data"),
    out_dir=Path("/backups"),
    passphrase=os.environ["BACKUP_PASSPHRASE"],
    keep=int(os.environ["BACKUP_KEEP_LOCAL"]),
)
for path in (archive, backup_sidecar_path(archive)):
    os.chown(path, int(os.environ["BACKUP_OWNER_UID"]), int(os.environ["BACKUP_OWNER_GID"]))
print(archive.name)
'
  )"
  [[ "$archive_name" =~ $BACKUP_NAME_PATTERN ]] || fail "container returned an unexpected archive name"
  printf '%s\n' "$archive_name"
}

verify_local_backup() {
  local archive_path="$1"
  local sidecar_path="${archive_path}.manifest.json"
  [[ -f "$archive_path" && ! -L "$archive_path" ]] || fail "encrypted archive was not published"
  [[ -f "$sidecar_path" && ! -L "$sidecar_path" ]] || fail "encrypted archive sidecar was not published"
  chmod 0600 "$archive_path" "$sidecar_path"

  .venv/bin/python - "$archive_path" <<'PY'
from pathlib import Path
import sys

from scripts.ops import read_backup_sidecar

archive = Path(sys.argv[1])
metadata = read_backup_sidecar(archive)
if metadata.get("artifact_state") != "READY" or not metadata.get("encrypted"):
    raise SystemExit("backup metadata is not encrypted READY state")
if metadata.get("backup_filename") != archive.name:
    raise SystemExit("backup metadata filename does not match archive")
PY
}

write_and_verify_checksum() {
  local archive_name="$1"
  local checksum_name="${archive_name}.sha256"
  (
    cd "$BACKUP_LOCAL_DIR"
    sha256sum -- "$archive_name" >"$checksum_name"
    chmod 0600 "$checksum_name"
    sha256sum --check --status "$checksum_name"
  )
  printf '%s\n' "$checksum_name"
}

sftp_batch() {
  sftp -oBatchMode=yes -oConnectTimeout=30 -oStrictHostKeyChecking=yes -b - "$OFFSITE_SFTP_HOST"
}

upload_and_verify_remote() {
  local archive_name="$1"
  local checksum_name="$2"
  local remote_archive="${OFFSITE_SFTP_DIR}/${archive_name}"
  local remote_sidecar="${remote_archive}.manifest.json"
  local remote_checksum="${OFFSITE_SFTP_DIR}/${checksum_name}"
  local downloaded_checksum
  downloaded_checksum="$(mktemp "${BACKUP_LOCAL_DIR}/.remote-checksum.XXXXXX")"

  sftp_batch <<EOF
put ${BACKUP_LOCAL_DIR}/${archive_name} ${remote_archive}
put ${BACKUP_LOCAL_DIR}/${archive_name}.manifest.json ${remote_sidecar}
put ${BACKUP_LOCAL_DIR}/${checksum_name} ${remote_checksum}
ls -l ${remote_archive}
ls -l ${remote_sidecar}
ls -l ${remote_checksum}
EOF

  if ! sftp_batch <<EOF
get ${remote_checksum} ${downloaded_checksum}
EOF
  then
    rm -f "$downloaded_checksum"
    fail "could not re-read remote checksum metadata"
  fi
  if ! cmp --silent "${BACKUP_LOCAL_DIR}/${checksum_name}" "$downloaded_checksum"; then
    rm -f "$downloaded_checksum"
    fail "remote checksum metadata does not match the local checksum"
  fi
  rm -f "$downloaded_checksum"
}

rotate_remote_backups() {
  local remote_listing
  remote_listing="$(sftp_batch <<EOF
ls -1 ${OFFSITE_SFTP_DIR}/novel-pipeline-backup-*.tar.gz.enc
EOF
)"

  local -a archive_names=()
  local entry archive_name
  while IFS= read -r entry; do
    archive_name="${entry##*/}"
    [[ "$archive_name" =~ $BACKUP_NAME_PATTERN ]] || continue
    archive_names+=("$archive_name")
  done <<<"$remote_listing"
  ((${#archive_names[@]} > BACKUP_KEEP_OFFSITE)) || return 0

  mapfile -t archive_names < <(
    printf '%s\n' "${archive_names[@]}" | sort -r | tail -n "+$((BACKUP_KEEP_OFFSITE + 1))"
  )
  {
    for archive_name in "${archive_names[@]}"; do
      printf 'rm %s/%s\n' "$OFFSITE_SFTP_DIR" "$archive_name"
      printf 'rm %s/%s.manifest.json\n' "$OFFSITE_SFTP_DIR" "$archive_name"
      printf 'rm %s/%s.sha256\n' "$OFFSITE_SFTP_DIR" "$archive_name"
    done
  } | sftp_batch
}

main() {
  BACKUP_IMAGE="${BACKUP_IMAGE:-novel-pipeline-api:runtime-hardening-20260718-r1}"
  BACKUP_DATA_DIR="${BACKUP_DATA_DIR:-$HOME/Novel-TNN/data}"
  BACKUP_LOCAL_DIR="${BACKUP_LOCAL_DIR:-$HOME/.local/share/novel-tnn-backups}"
  OFFSITE_SFTP_HOST="${OFFSITE_SFTP_HOST:-}"
  OFFSITE_SFTP_DIR="${OFFSITE_SFTP_DIR:-}"
  BACKUP_KEEP_LOCAL="${BACKUP_KEEP_LOCAL:-14}"
  BACKUP_KEEP_OFFSITE="${BACKUP_KEEP_OFFSITE:-35}"

  validate_config
  if [[ "${1:-}" == "--validate-config" ]]; then
    printf 'backup configuration validated\n'
    return 0
  fi
  [[ $# -eq 0 ]] || fail "usage: $0 [--validate-config]"
  command -v docker >/dev/null || fail "docker is required"
  command -v sftp >/dev/null || fail "sftp is required"

  umask 077
  install -d -m 0700 "$BACKUP_LOCAL_DIR"
  local archive_name archive_path checksum_name
  archive_name="$(run_container_backup)"
  archive_path="${BACKUP_LOCAL_DIR}/${archive_name}"
  verify_local_backup "$archive_path"
  checksum_name="$(write_and_verify_checksum "$archive_name")"
  upload_and_verify_remote "$archive_name" "$checksum_name"
  rotate_remote_backups
  printf 'backup complete: %s\n' "$archive_name"
}

main "$@"
