#!/usr/bin/env bash
set -euo pipefail

# Invoked by the novel-tnn-backup systemd user service. The service runs as
# thenam176; Docker executes the short-lived backup container as root because
# live data deliberately belongs only to UID/GID 10001. Off-site copies use
# Cloudflare R2's private S3-compatible endpoint with HTTPS-only SigV4 calls.

readonly RUNNER_NAME="novel-tnn production backup"
readonly BACKUP_NAME_PATTERN='^novel-pipeline-backup-[0-9]{8}-[0-9]{6}(-[A-Za-z0-9._-]+)?(-[a-f0-9]{12})?\.tar\.gz\.enc$'
readonly R2_SINGLE_PUT_MAX_BYTES=$((5 * 1024 * 1024 * 1024))
readonly R2_MIN_MULTIPART_PART_BYTES=$((5 * 1024 * 1024))
readonly R2_MAX_MULTIPART_PARTS=10000

fail() {
  printf '%s: %s\n' "$RUNNER_NAME" "$*" >&2
  exit 2
}

require_value() {
  local variable_name="$1"
  [[ -n "${!variable_name:-}" ]] || fail "${variable_name} is required"
}

require_bounded_decimal() {
  local variable_name="$1"
  local maximum="$2"
  local value="${!variable_name:-}"
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || fail "${variable_name} must be a positive integer"
  if [[ ${#value} -gt ${#maximum} ]] \
    || { [[ ${#value} -eq ${#maximum} ]] && [[ "$value" > "$maximum" ]]; }; then
    fail "${variable_name} must be at most ${maximum}"
  fi
}

require_absolute_path() {
  local variable_name="$1"
  [[ "${!variable_name:-}" == /* ]] || fail "${variable_name} must be an absolute path"
}

require_safe_absolute_path() {
  local variable_name="$1"
  local value="${!variable_name:-}"
  require_absolute_path "$variable_name"
  [[ "$value" != "/" && "$value" != *"//"* && "$value" != *"/./"* && "$value" != */. \
    && "$value" != *"/../"* && "$value" != */.. && "$value" != *","* \
    && "$value" != *$'\n'* && "$value" != *$'\r'* ]] \
    || fail "${variable_name} contains an unsafe path"
}

require_canonical_real_directory() {
  local variable_name="$1"
  local identity_variable_name="$2"
  local value="${!variable_name}"
  local normalized_value="${value%/}"
  local canonical_value identity
  canonical_value="$(realpath --canonicalize-existing -- "$normalized_value" 2>/dev/null)" \
    || fail "${variable_name} must be an existing canonical real directory without symlink components"
  [[ -d "$canonical_value" && "$canonical_value" == "$normalized_value" ]] \
    || fail "${variable_name} must be an existing canonical real directory without symlink components"
  identity="$(stat --format='%d:%i' -- "$canonical_value" 2>/dev/null)" \
    || fail "${variable_name} identity is unavailable"
  [[ "$identity" =~ ^[0-9]+:[0-9]+$ ]] || fail "${variable_name} identity is invalid"
  printf -v "$variable_name" '%s' "$canonical_value"
  printf -v "$identity_variable_name" '%s' "$identity"
}

parse_invocation() {
  BACKUP_MODE=""
  REQUESTED_ARCHIVE_NAME=""
  if [[ $# -eq 0 ]]; then
    BACKUP_MODE="create"
  elif [[ $# -eq 1 && "$1" == "--validate-config" ]]; then
    BACKUP_MODE="validate"
  elif [[ $# -eq 2 && "$1" == "--upload-existing" ]]; then
    [[ "$2" =~ $BACKUP_NAME_PATTERN ]] \
      || fail "archive must be a supported encrypted backup basename"
    BACKUP_MODE="upload-existing"
    REQUESTED_ARCHIVE_NAME="$2"
  else
    fail "usage: $0 [--validate-config|--upload-existing archive-basename]"
  fi
}

validate_r2_destination() {
  [[ "$R2_ACCOUNT_ID" =~ ^[A-Fa-f0-9]{32}$ ]] || fail "R2_ACCOUNT_ID must be a Cloudflare account ID"
  [[ "$R2_BUCKET" =~ ^[a-z0-9]([a-z0-9-]{1,61}[a-z0-9])$ ]] || fail "R2_BUCKET must be a 3-63 character lowercase bucket name"
  [[ "$R2_PREFIX" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || fail "R2_PREFIX contains unsafe characters"
  [[ "$R2_PREFIX" != */ && "$R2_PREFIX" != *"//"* && "$R2_PREFIX" != *"/../"* && "$R2_PREFIX" != .. && "$R2_PREFIX" != */.. ]] \
    || fail "R2_PREFIX must not contain path traversal"
  [[ "$R2_ACCESS_KEY_ID" != *[[:space:]]* ]] || fail "R2_ACCESS_KEY_ID must not contain whitespace"
  [[ "$R2_SECRET_ACCESS_KEY" != *[[:space:]]* ]] || fail "R2_SECRET_ACCESS_KEY must not contain whitespace"
}

validate_config() {
  require_value BACKUP_PASSPHRASE
  require_value BACKUP_IMAGE
  require_value BACKUP_DATA_DIR
  require_value BACKUP_LOCAL_DIR
  require_value R2_ACCOUNT_ID
  require_value R2_BUCKET
  require_value R2_PREFIX
  require_value R2_ACCESS_KEY_ID
  require_value R2_SECRET_ACCESS_KEY
  require_value RECOVERY_PRODUCER_VERSION
  require_bounded_decimal BACKUP_KEEP_LOCAL 10000
  require_bounded_decimal BACKUP_KEEP_OFFSITE 10000
  require_bounded_decimal R2_MULTIPART_THRESHOLD_BYTES "$R2_SINGLE_PUT_MAX_BYTES"
  require_bounded_decimal R2_MULTIPART_PART_BYTES "$R2_SINGLE_PUT_MAX_BYTES"
  require_safe_absolute_path BACKUP_DATA_DIR
  require_safe_absolute_path BACKUP_LOCAL_DIR
  require_safe_absolute_path RECOVERY_RECEIPT_DIR
  require_canonical_real_directory BACKUP_DATA_DIR BACKUP_DATA_ROOT_IDENTITY
  [[ "$BACKUP_IMAGE" != -* \
    && "$BACKUP_IMAGE" =~ ^([a-z0-9]+([.-][a-z0-9]+)*(:[0-9]{1,5})?/)?[a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*@sha256:[0-9a-f]{64}$ ]] \
    || fail "BACKUP_IMAGE must be a safe sha256-pinned Docker reference pinned by sha256 digest"
  [[ "$RECOVERY_PRODUCER_VERSION" =~ ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$ ]] \
    || fail "RECOVERY_PRODUCER_VERSION must be a safe release identifier"
  ((R2_MULTIPART_THRESHOLD_BYTES <= R2_SINGLE_PUT_MAX_BYTES)) \
    || fail "R2_MULTIPART_THRESHOLD_BYTES must not exceed the R2 single-upload limit"
  ((R2_MULTIPART_PART_BYTES >= R2_MIN_MULTIPART_PART_BYTES && R2_MULTIPART_PART_BYTES <= R2_SINGLE_PUT_MAX_BYTES)) \
    || fail "R2_MULTIPART_PART_BYTES must be between 5 MiB and 5 GiB"
  validate_r2_destination

  local data_root backup_root
  data_root="$(realpath -m "$BACKUP_DATA_DIR")"
  backup_root="$(realpath -m "$BACKUP_LOCAL_DIR")"
  [[ "$RECOVERY_RECEIPT_DIR" == "${BACKUP_DATA_DIR%/}/logs/runtime" ]] \
    || fail "RECOVERY_RECEIPT_DIR must be the fixed data/logs/runtime directory"
  [[ "$backup_root" != "$data_root" && "$backup_root" != "$data_root"/* ]] \
    || fail "BACKUP_LOCAL_DIR must not be inside BACKUP_DATA_DIR"
}

verify_recovery_publisher_contract() {
  if ! docker run --rm --network none --user 10001:10001 \
    --mount "type=bind,src=${BACKUP_DATA_DIR},dst=/data-root,readonly" \
    --mount "type=bind,src=${RECOVERY_RECEIPT_DIR},dst=/receipts" \
    -- "$BACKUP_IMAGE" \
    python -m scripts.verify_recovery_publisher \
    --data-root /data-root \
    --receipt-dir /receipts \
    --expected-release "$RECOVERY_PRODUCER_VERSION" \
    --expected-data-root-identity "$BACKUP_DATA_ROOT_IDENTITY" >/dev/null 2>&1; then
    fail "recovery publisher preflight failed"
  fi
}

run_container_backup() {
  local archive_name
  archive_name="$(
    docker run --rm --network none --user 0:0 \
      --mount "type=bind,src=${BACKUP_DATA_DIR},dst=/data,readonly" \
      --mount "type=bind,src=${BACKUP_LOCAL_DIR},dst=/backups" \
      --env BACKUP_PASSPHRASE \
      --env "BACKUP_KEEP_LOCAL=${BACKUP_KEEP_LOCAL}" \
      --env "BACKUP_OWNER_UID=$(id -u)" \
      --env "BACKUP_OWNER_GID=$(id -g)" \
      -- "$BACKUP_IMAGE" \
      python -c '
import os
from pathlib import Path
import sys
from scripts.ops import backup_sidecar_path, create_encrypted_backup

data_fd = os.open("/data", os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    data_metadata = os.fstat(data_fd)
finally:
    os.close(data_fd)
if f"{data_metadata.st_dev}:{data_metadata.st_ino}" != sys.argv[1]:
    raise SystemExit("data root identity mismatch")
archive = create_encrypted_backup(
    data_dir=Path("/data"),
    out_dir=Path("/backups"),
    passphrase=os.environ["BACKUP_PASSPHRASE"],
    keep=int(os.environ["BACKUP_KEEP_LOCAL"]),
    record_event=False,
    checkpoint_database=False,
)
for path in (archive, backup_sidecar_path(archive)):
    os.chown(path, int(os.environ["BACKUP_OWNER_UID"]), int(os.environ["BACKUP_OWNER_GID"]))
print(archive.name)
' "$BACKUP_DATA_ROOT_IDENTITY"
  )"
  [[ "$archive_name" =~ $BACKUP_NAME_PATTERN ]] || fail "container returned an unexpected archive name"
  printf '%s\n' "$archive_name"
}

archive_completed_at() {
  local archive_name="$1"
  .venv/bin/python - "$archive_name" <<'PY'
from datetime import datetime, timedelta, timezone
import re
import sys

match = re.fullmatch(
    r"novel-pipeline-backup-(?P<stamp>[0-9]{8}-[0-9]{6})"
    r"(?:-[A-Za-z0-9._-]+)?(?:-[a-f0-9]{12})?\.tar\.gz\.enc",
    sys.argv[1],
)
if match is None:
    raise SystemExit(1)
try:
    completed_at = datetime.strptime(match.group("stamp"), "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
except ValueError:
    raise SystemExit(1) from None
if completed_at > datetime.now(timezone.utc) + timedelta(seconds=300):
    raise SystemExit(1)
print(completed_at.isoformat())
PY
}

publish_recovery_receipt() {
  local archive_hash_id="$1"
  local completed_at="$2"
  if ! docker run --rm --network none --user 10001:10001 \
    --mount "type=bind,src=${BACKUP_DATA_DIR},dst=/data-root,readonly" \
    --mount "type=bind,src=${RECOVERY_RECEIPT_DIR},dst=/receipts" \
    -- "$BACKUP_IMAGE" \
    sh -ec '
expected_release="$1"
expected_data_root_identity="$2"
shift 2
python -m scripts.verify_recovery_publisher \
  --data-root /data-root \
  --receipt-dir /receipts \
  --expected-release "$expected_release" \
  --expected-data-root-identity "$expected_data_root_identity"
exec python "$@"
' _ "$RECOVERY_PRODUCER_VERSION" "$BACKUP_DATA_ROOT_IDENTITY" \
    -m scripts.record_restore_drill_status \
    --output /receipts/external-backup.receipt.json \
    --archive-hash-id "$archive_hash_id" \
    --producer-version "$RECOVERY_PRODUCER_VERSION" \
    --completed-at "$completed_at" \
    --validation-count archive_verified=1 \
    --validation-count metadata_verified=1 \
    --validation-count checksum_verified=1 \
    --validation-count remote_uploads_verified=3 \
    --validation-count remote_metadata_verified=2 >/dev/null 2>&1; then
    fail "recovery receipt publication failed"
  fi
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

read_verified_checksum_hash() {
  local archive_name="$1"
  .venv/bin/python - "${BACKUP_LOCAL_DIR}/${archive_name}.sha256" "$archive_name" <<'PY'
from pathlib import Path
import re
import sys

raw = Path(sys.argv[1]).read_text(encoding="ascii")
match = re.fullmatch(r"([a-f0-9]{64})  ([^\r\n]+)\n", raw)
if match is None or match.group(2) != sys.argv[2]:
    raise SystemExit("checksum file must contain exactly the selected archive")
print(match.group(1))
PY
}

verify_existing_checksum() {
  local archive_name="$1"
  local checksum_name="${archive_name}.sha256"
  local checksum_path="${BACKUP_LOCAL_DIR}/${checksum_name}"
  [[ -f "$checksum_path" && ! -L "$checksum_path" ]] || fail "backup checksum is unavailable"
  chmod 0600 "$checksum_path"
  (
    cd "$BACKUP_LOCAL_DIR"
    sha256sum --check --status "$checksum_name"
  ) || fail "backup checksum does not match archive"
  read_verified_checksum_hash "$archive_name" >/dev/null \
    || fail "backup checksum metadata does not identify the selected archive"
  printf '%s\n' "$checksum_name"
}

r2_endpoint() {
  printf 'https://%s.r2.cloudflarestorage.com\n' "$R2_ACCOUNT_ID"
}

r2_object_key() {
  local filename="$1"
  [[ "$filename" != */* && "$filename" != *".."* ]] || fail "unexpected off-site filename"
  printf '%s/%s\n' "$R2_PREFIX" "$filename"
}

r2_object_url() {
  local key="$1"
  printf '%s/%s/%s\n' "$(r2_endpoint)" "$R2_BUCKET" "$key"
}

r2_url_encode() {
  .venv/bin/python - "$1" <<'PY'
import sys
from urllib.parse import quote

print(quote(sys.argv[1], safe=""))
PY
}

r2_xml_text() {
  local xml_path="$1"
  local tag_name="$2"
  .venv/bin/python - "$xml_path" "$tag_name" <<'PY'
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

root = ET.fromstring(Path(sys.argv[1]).read_text(encoding="utf-8"))
tag_name = sys.argv[2]
for element in root.iter():
    if element.tag.rsplit("}", 1)[-1] == tag_name and element.text:
        print(element.text)
        break
else:
    raise SystemExit(f"missing {tag_name} in R2 XML response")
PY
}

r2_curl() {
  # curl needs the S3 access key and secret to construct the SigV4 signature.
  # Keep them out of the process argument list; systemd already supplies them
  # through the private EnvironmentFile.
  (
    local curl_config
    curl_config="$(mktemp "${TMPDIR:-/tmp}/novel-tnn-r2-curl.XXXXXX")"
    chmod 0600 "$curl_config"
    trap 'rm -f "${curl_config:-}"' EXIT
    printf 'user = "%s:%s"\n' "$R2_ACCESS_KEY_ID" "$R2_SECRET_ACCESS_KEY" >"$curl_config"
    curl --config "$curl_config" --fail --silent --show-error --retry 3 --retry-all-errors --connect-timeout 30 \
      --aws-sigv4 'aws:amz:auto:s3' \
      "$@"
  )
}

r2_put_multipart() (
  local local_path="$1"
  local remote_name="$2"
  local object_url temp_dir initiation_path completion_path part_path header_path
  local upload_id="" encoded_upload_id byte_count byte_offset part_number part_byte_count etag
  local multipart_completed=0

  cleanup_multipart() {
    local status="$?" current_path
    trap - EXIT
    if [[ -n "${upload_id:-}" && "$multipart_completed" -eq 0 ]]; then
      r2_curl --request DELETE "${object_url}?uploadId=${encoded_upload_id}" >/dev/null 2>&1 || true
    fi
    for current_path in "${temp_dir:?}"/*; do
      [[ -e "$current_path" ]] && rm -- "$current_path" || true
    done
    rmdir "$temp_dir" 2>/dev/null || true
    return "$status"
  }

  object_url="$(r2_object_url "$(r2_object_key "$remote_name")")"
  byte_count="$(stat --format='%s' "$local_path")"
  temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/novel-tnn-r2-multipart.XXXXXX")"
  chmod 0700 "$temp_dir"
  trap cleanup_multipart EXIT

  initiation_path="${temp_dir}/initiation.xml"
  r2_curl --request POST --output "$initiation_path" "${object_url}?uploads"
  upload_id="$(r2_xml_text "$initiation_path" UploadId)"
  [[ -n "$upload_id" ]] || fail "R2 multipart initiation did not return an upload ID"
  encoded_upload_id="$(r2_url_encode "$upload_id")"
  completion_path="${temp_dir}/completion.xml"
  printf '%s\n' '<CompleteMultipartUpload>' >"$completion_path"

  byte_offset=0
  part_number=1
  while ((byte_offset < byte_count)); do
    ((part_number <= R2_MAX_MULTIPART_PARTS)) || fail "archive requires more than ${R2_MAX_MULTIPART_PARTS} R2 multipart parts"
    part_byte_count=$((byte_count - byte_offset))
    ((part_byte_count > R2_MULTIPART_PART_BYTES)) && part_byte_count="$R2_MULTIPART_PART_BYTES"
    part_path="${temp_dir}/part-${part_number}.bin"
    header_path="${temp_dir}/part-${part_number}.headers"
    dd if="$local_path" of="$part_path" iflag=skip_bytes,count_bytes skip="$byte_offset" count="$part_byte_count" status=none
    r2_curl --request PUT --upload-file "$part_path" --dump-header "$header_path" \
      "${object_url}?partNumber=${part_number}&uploadId=${encoded_upload_id}" >/dev/null
    etag="$(awk 'BEGIN { IGNORECASE = 1 } /^etag:/{value=$0; sub(/^[^:]*:[[:space:]]*/, "", value); gsub(/\r/, "", value); gsub(/"/, "", value); print value}' "$header_path" | tail -n 1)"
    [[ "$etag" =~ ^[A-Fa-f0-9-]+$ ]] || fail "R2 multipart part ${part_number} did not return a safe ETag"
    printf '  <Part><PartNumber>%s</PartNumber><ETag>"%s"</ETag></Part>\n' "$part_number" "$etag" >>"$completion_path"
    rm -- "$part_path" "$header_path"
    byte_offset=$((byte_offset + part_byte_count))
    part_number=$((part_number + 1))
  done
  printf '%s\n' '</CompleteMultipartUpload>' >>"$completion_path"
  r2_curl --request POST --data-binary "@${completion_path}" "${object_url}?uploadId=${encoded_upload_id}" >/dev/null
  multipart_completed=1
  upload_id=""
)

r2_put() {
  local local_path="$1"
  local remote_name="$2"
  local byte_count
  byte_count="$(stat --format='%s' "$local_path")"
  if ((byte_count > R2_MULTIPART_THRESHOLD_BYTES)); then
    r2_put_multipart "$local_path" "$remote_name"
  else
    r2_curl --request PUT --upload-file "$local_path" "$(r2_object_url "$(r2_object_key "$remote_name")")" >/dev/null
  fi
}

r2_get() {
  local remote_name="$1"
  local local_path="$2"
  r2_curl --request GET --output "$local_path" "$(r2_object_url "$(r2_object_key "$remote_name")")"
}

r2_delete() {
  local remote_name="$1"
  r2_curl --request DELETE "$(r2_object_url "$(r2_object_key "$remote_name")")" >/dev/null
}

upload_and_verify_remote() {
  local archive_name="$1"
  local checksum_name="$2"
  local sidecar_name="${archive_name}.manifest.json"

  r2_put "${BACKUP_LOCAL_DIR}/${archive_name}" "$archive_name"
  r2_put "${BACKUP_LOCAL_DIR}/${sidecar_name}" "$sidecar_name"
  r2_put "${BACKUP_LOCAL_DIR}/${checksum_name}" "$checksum_name"

  (
    local downloaded_archive downloaded_checksum downloaded_sidecar
    downloaded_archive="$(mktemp "${BACKUP_LOCAL_DIR}/.remote-archive.XXXXXX")"
    downloaded_checksum="$(mktemp "${BACKUP_LOCAL_DIR}/.remote-checksum.XXXXXX")"
    downloaded_sidecar="$(mktemp "${BACKUP_LOCAL_DIR}/.remote-sidecar.XXXXXX")"
    trap 'rm -f "${downloaded_archive:-}" "${downloaded_checksum:-}" "${downloaded_sidecar:-}"' EXIT
    r2_get "$archive_name" "$downloaded_archive"
    r2_get "$checksum_name" "$downloaded_checksum"
    r2_get "$sidecar_name" "$downloaded_sidecar"
    cmp --silent "${BACKUP_LOCAL_DIR}/${archive_name}" "$downloaded_archive" \
      || fail "remote archive does not match the verified local archive"
    cmp --silent "${BACKUP_LOCAL_DIR}/${checksum_name}" "$downloaded_checksum" \
      || fail "remote checksum metadata does not match the local checksum"
    cmp --silent "${BACKUP_LOCAL_DIR}/${sidecar_name}" "$downloaded_sidecar" \
      || fail "remote READY metadata does not match the local sidecar"
  )
}

r2_list_archive_names() {
  local list_url listing
  list_url="$(r2_endpoint)/${R2_BUCKET}?list-type=2&prefix=${R2_PREFIX}/novel-pipeline-backup-"
  listing="$(r2_curl --request GET "$list_url")"
  printf '%s' "$listing" | .venv/bin/python -c '
import re
import sys
import xml.etree.ElementTree as ET

prefix = sys.argv[1]
pattern = re.compile(rf"^{re.escape(prefix)}/(novel-pipeline-backup-[0-9]{{8}}-[0-9]{{6}}(?:-[A-Za-z0-9._-]+)?(?:-[a-f0-9]{{12}})?\.tar\.gz\.enc)$")
try:
    root = ET.fromstring(sys.stdin.read())
except ET.ParseError as exc:
    raise SystemExit(f"R2 list response was not valid XML: {exc}")
for element in root.iter():
    if element.tag.rsplit("}", 1)[-1] != "Key" or not element.text:
        continue
    match = pattern.fullmatch(element.text)
    if match:
        print(match.group(1))
' "$R2_PREFIX"
}

rotate_remote_backups() {
  local -a archive_names=()
  local listing
  listing="$(r2_list_archive_names)" || fail "failed to list remote backups for rotation"
  if [[ -n "$listing" ]]; then
    mapfile -t archive_names <<<"$listing"
  fi
  ((${#archive_names[@]} > BACKUP_KEEP_OFFSITE)) || return 0

  mapfile -t archive_names < <(
    printf '%s\n' "${archive_names[@]}" | sort -r | tail -n "+$((BACKUP_KEEP_OFFSITE + 1))"
  )
  local archive_name
  for archive_name in "${archive_names[@]}"; do
    r2_delete "$archive_name"
    r2_delete "${archive_name}.manifest.json"
    r2_delete "${archive_name}.sha256"
  done
}

main() {
  BACKUP_IMAGE="${BACKUP_IMAGE:-}"
  BACKUP_DATA_DIR="${BACKUP_DATA_DIR:-$HOME/Novel-TNN/data}"
  BACKUP_LOCAL_DIR="${BACKUP_LOCAL_DIR:-$HOME/.local/share/novel-tnn-backups}"
  R2_ACCOUNT_ID="${R2_ACCOUNT_ID:-}"
  R2_BUCKET="${R2_BUCKET:-}"
  R2_PREFIX="${R2_PREFIX:-novel-tnn-production}"
  R2_ACCESS_KEY_ID="${R2_ACCESS_KEY_ID:-}"
  R2_SECRET_ACCESS_KEY="${R2_SECRET_ACCESS_KEY:-}"
  R2_MULTIPART_THRESHOLD_BYTES="${R2_MULTIPART_THRESHOLD_BYTES:-$R2_SINGLE_PUT_MAX_BYTES}"
  R2_MULTIPART_PART_BYTES="${R2_MULTIPART_PART_BYTES:-$((256 * 1024 * 1024))}"
  BACKUP_KEEP_LOCAL="${BACKUP_KEEP_LOCAL:-14}"
  BACKUP_KEEP_OFFSITE="${BACKUP_KEEP_OFFSITE:-35}"
  RECOVERY_PRODUCER_VERSION="${RECOVERY_PRODUCER_VERSION:-}"
  RECOVERY_RECEIPT_DIR="${RECOVERY_RECEIPT_DIR:-${BACKUP_DATA_DIR%/}/logs/runtime}"

  parse_invocation "$@"
  validate_config
  if [[ "$BACKUP_MODE" == "validate" ]]; then
    printf 'backup configuration validated\n'
    return 0
  fi
  local archive_name archive_path checksum_name checksum_hash completed_at
  if [[ "$BACKUP_MODE" == "upload-existing" ]]; then
    archive_name="$REQUESTED_ARCHIVE_NAME"
    completed_at="$(archive_completed_at "$archive_name")" \
      || fail "archive timestamp is invalid or exceeds allowed clock skew"
  fi
  command -v curl >/dev/null || fail "curl is required"
  command -v docker >/dev/null || fail "docker is required"
  command -v sha256sum >/dev/null || fail "sha256sum is required"
  curl --help all | grep --quiet -- '--aws-sigv4' || fail "curl with --aws-sigv4 support is required"
  verify_recovery_publisher_contract

  umask 077
  install -d -m 0700 "$BACKUP_LOCAL_DIR"
  if [[ "$BACKUP_MODE" != "upload-existing" ]]; then
    archive_name="$(run_container_backup)"
    completed_at="$(archive_completed_at "$archive_name")" \
      || fail "archive timestamp is invalid or exceeds allowed clock skew"
  fi
  archive_path="${BACKUP_LOCAL_DIR}/${archive_name}"
  verify_local_backup "$archive_path"
  if [[ "$BACKUP_MODE" == "upload-existing" ]]; then
    checksum_name="$(verify_existing_checksum "$archive_name")"
  else
    checksum_name="$(write_and_verify_checksum "$archive_name")"
  fi
  upload_and_verify_remote "$archive_name" "$checksum_name"
  checksum_hash="$(read_verified_checksum_hash "$archive_name")"
  [[ "$checksum_hash" =~ ^[a-f0-9]{64}$ ]] || fail "verified checksum is not a SHA-256 identifier"
  rotate_remote_backups
  publish_recovery_receipt "sha256:${checksum_hash}" "$completed_at"
  printf 'backup complete: %s\n' "$archive_name"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
