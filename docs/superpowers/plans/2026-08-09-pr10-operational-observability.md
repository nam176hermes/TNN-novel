# PR10 Operational Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver backup failure, wrong-release receipt, stale worker, and stuck-job alerts through a generic HTTPS webhook with redacted receipts, and pin real local Docker image IDs so production-style `/api/version` never reports `unknown`.

**Architecture:** Extend the existing read-only operational snapshot with two missing stable alert codes, then add an isolated delivery service used by a CLI/systemd timer rather than API request handling. Delivery uses an allowlisted payload, bounded `requests` retries, atomic mode-`0600` receipts, and a loopback-only synthetic smoke. Build API/worker images from the implementation commit, inspect their immutable IDs, and record those literal IDs in a release overlay.

**Tech Stack:** Python 3.11, raw `sqlite3`, `requests`, pytest, Docker Compose, systemd user units, POSIX atomic file replacement.

## Global Constraints

- Supported alert classes are exactly `backup_failure`, `wrong_release_receipt`, `worker_stale`, and `stuck_jobs`.
- Production delivery requires HTTPS; HTTP is allowed only for explicit loopback synthetic validation.
- No webhook URL, bearer token, response body, job/user identifier, filename, content, or absolute path may enter payloads or receipts.
- Delivery attempts are bounded to three with finite timeout/backoff.
- Receipts are atomic regular files with mode `0600` under `DATA_DIR/logs/runtime/`.
- No external post, production restart, timer enablement, DNS/Cloudflare change, or operator-database mutation is authorized.
- API and worker use separate real immutable local Docker image IDs.

---

### Task 1: Add stable alert sources for backup failure and stale worker

**Files:**
- Modify: `app/mobile_api/services/operational_metrics_service.py`
- Modify: `tests/test_operational_metrics.py`

**Interfaces:**
- Consumes: `OperationalMetricsService.snapshot()` and `evaluate_operational_alerts(snapshot)`.
- Produces: `jobs.backup_failed`, alert code `backup_failed`, and alert code `worker_stale` while preserving existing codes.

- [ ] **Step 1: Write failing alert-evaluation tests**

Add focused tests equivalent to:

```python
def test_alert_rules_emit_dispatchable_backup_failure_and_worker_stale_codes() -> None:
    snapshot = {
        "worker": {"required": True, "status": "stale", "queue_claim_capable": False},
        "release": {"worker_match": True},
        "storage": {"disk_free_bytes": 2 * 1024**3},
        "queue": {"oldest_age_seconds": None},
        "jobs": {"failed_or_interrupted": 0, "backup_failed": 1},
        "backup": {"state": "fresh"},
        "restore_drill": {"state": "fresh"},
        "artifacts": {"error_count": 0},
    }

    codes = {item["code"] for item in evaluate_operational_alerts(snapshot)}

    assert {"worker_not_ready", "worker_stale", "backup_failed"}.issubset(codes)
```

Extend the bounded snapshot test by inserting one failed `mobile_jobs` row with `job_type='backup'` and asserting `snapshot["jobs"]["backup_failed"] == 1`.

- [ ] **Step 2: Run the new tests and verify RED**

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python \
  -m pytest -q -s tests/test_operational_metrics.py \
  -k "backup_failure or worker_stale or bounded"
```

Expected: FAIL because the codes/count do not exist.

- [ ] **Step 3: Implement the two bounded metrics**

Add a count query limited to failed backup mobile jobs:

```sql
SELECT COUNT(*) FROM mobile_jobs
WHERE lower(job_type) = 'backup' AND lower(status) = 'failed'
```

Expose the integer as `snapshot["jobs"]["backup_failed"]`. In `evaluate_operational_alerts`:

```python
if worker.get("required") and worker.get("status") == "stale":
    add("worker_stale", "critical", "Required import worker heartbeat is stale")
if snapshot["jobs"].get("backup_failed", 0) > 0:
    add("backup_failed", "warning", "A backup job failed")
```

Keep `worker_not_ready`, `jobs_failed`, recovery receipt, disk, artifact, and queue rules unchanged.

- [ ] **Step 4: Run all operational metrics tests**

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python \
  -m pytest -q -s tests/test_operational_metrics.py
```

- [ ] **Step 5: Commit alert source changes**

```bash
git add app/mobile_api/services/operational_metrics_service.py tests/test_operational_metrics.py
git commit -m "feat: expose dispatchable operational alert classes"
```

---

### Task 2: Build the redacted webhook dispatcher and atomic receipts

**Files:**
- Create: `app/services/operational_alert_delivery.py`
- Create: `tests/test_operational_alert_delivery.py`

**Interfaces:**
- Produces: `AlertIncident`, `AlertDeliveryConfig`, `DeliveryReceipt`, `incidents_from_snapshot(snapshot)`, and `OperationalAlertDispatcher.dispatch(snapshot)`.
- Consumes: operational snapshot dictionaries and an injected `requests.Session`-compatible client.

- [ ] **Step 1: Write failing tests for class mapping and payload allowlisting**

Create parameterized fixtures for these mappings:

```python
SUPPORTED_ALERT_CLASSES = {
    "backup_failure": {"backup_failed"},
    "wrong_release_receipt": {
        "external_backup_wrong_release",
        "restore_drill_wrong_release",
    },
    "worker_stale": {"worker_stale"},
    "stuck_jobs": {"queue_stale"},
}
```

Assert the serialized request payload has exactly:

```python
{
    "schema_version",
    "alert_class",
    "code",
    "severity",
    "release_id",
    "observed_at",
    "fingerprint",
}
```

and contains none of the configured URL/token or injected private sentinels.

- [ ] **Step 2: Write failing tests for URL policy, retry, receipts, and dedupe**

Cover:

- production `http://example.test/hook` raises `ValueError`;
- `http://127.0.0.1:18765/hook` is allowed only with `allow_loopback_http=True`;
- two retryable failures followed by HTTP 202 produce `attempt_count == 3`;
- three failures produce a redacted `failed` receipt and no response body;
- a delivered same-fingerprint receipt suppresses the next POST;
- an invocation with no active class writes `resolved`, allowing a later recurrence;
- the final receipt is a regular file with `stat.S_IMODE(...) == 0o600`.

- [ ] **Step 3: Run the new test module and verify RED**

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python \
  -m pytest -q -s tests/test_operational_alert_delivery.py
```

Expected: collection fails only because the new module/API does not exist. After adding the empty module and test imports, tests must fail on missing behavior rather than syntax.

- [ ] **Step 4: Implement immutable incident and receipt records**

Use frozen dataclasses with these public fields:

```python
@dataclass(frozen=True)
class AlertIncident:
    alert_class: str
    code: str
    severity: str
    release_id: str
    observed_at: str
    fingerprint: str

@dataclass(frozen=True)
class AlertDeliveryConfig:
    webhook_url: str
    bearer_token: str = ""
    timeout_seconds: float = 5.0
    max_attempts: int = 3
    allow_loopback_http: bool = False
```

Fingerprint input is canonical JSON containing only alert class, selected stable code, and release ID. Absence of an active class moves its receipt to `resolved`; recurrence is therefore deliverable even with the same fingerprint.

- [ ] **Step 5: Implement atomic receipt storage**

Write to the class-specific filename from the approved spec. Use `tempfile.mkstemp` in the target directory, `os.fchmod(fd, 0o600)`, JSON serialization with sorted keys, file flush plus `os.fsync`, `os.replace`, directory `fsync`, and cleanup of an uncommitted temporary file in `finally`.

Reject unsupported class names before deriving a path.

- [ ] **Step 6: Implement bounded POST delivery**

Use `requests.Session.post` with:

```python
headers = {
    "Content-Type": "application/json",
    **({"Authorization": f"Bearer {token}"} if token else {}),
}
```

Never inspect or store `response.text`. Treat only `200 <= status_code < 300` as delivered. Clamp attempts to `1..3`, timeout to a finite positive value, and inject the sleep function for zero-delay tests.

- [ ] **Step 7: Run delivery tests until GREEN**

Run the command from Step 3 and require all tests to pass.

- [ ] **Step 8: Commit dispatcher and receipt implementation**

```bash
git add app/services/operational_alert_delivery.py tests/test_operational_alert_delivery.py
git commit -m "feat: deliver redacted operational webhooks"
```

---

### Task 3: Add the dispatcher CLI, synthetic receiver smoke, and timer examples

**Files:**
- Create: `scripts/dispatch_operational_alerts.py`
- Create: `scripts/smoke_operational_alerts.py`
- Create: `tests/test_operational_alert_scripts.py`
- Create: `deploy/production/alert.env.example`
- Create: `deploy/systemd/user/novel-tnn-alert-dispatch.service`
- Create: `deploy/systemd/user/novel-tnn-alert-dispatch.timer`
- Modify: `docs/operations/runtime-alerts-and-rollback.md`

**Interfaces:**
- Consumes: `OperationalMetricsService`, `OperationalAlertDispatcher`, `settings.db_path`, and `settings.resolved_data_dir`.
- Produces: `python -m scripts.dispatch_operational_alerts` and a loopback-only `python -m scripts.smoke_operational_alerts --receipt-dir "$ALERT_SMOKE_DIR"`.

- [ ] **Step 1: Write failing CLI and synthetic-smoke tests**

Test that:

- missing webhook configuration exits `2` without printing its value;
- a fake dispatcher receives a non-cached operational snapshot;
- the synthetic command creates exactly four delivered receipt files;
- captured loopback requests contain exactly the allowlisted payload keys;
- output contains class names and statuses but no URL, token, response body, or absolute receipt path.

- [ ] **Step 2: Run script tests and verify RED**

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python \
  -m pytest -q -s tests/test_operational_alert_scripts.py
```

- [ ] **Step 3: Implement the production CLI**

Read only these environment variables:

```text
NOVEL_ALERT_WEBHOOK_URL
NOVEL_ALERT_WEBHOOK_BEARER_TOKEN
NOVEL_ALERT_TIMEOUT_SECONDS
NOVEL_ALERT_MAX_ATTEMPTS
```

Construct `OperationalMetricsService(settings.db_path, settings.resolved_data_dir)`, request `snapshot(use_cache=False)`, dispatch it, print one bounded status line per supported class, and return non-zero when any active incident exhausts delivery.

- [ ] **Step 4: Implement the loopback synthetic smoke**

Start `ThreadingHTTPServer(("127.0.0.1", 0), handler)` in a background thread, generate one synthetic alert per class, call the real dispatcher with `allow_loopback_http=True`, verify four delivered receipts, then shut down and close the server in `finally`.

The command requires an explicit `--receipt-dir`; reject `/`, the repository root, `DATA_DIR`, and symlink targets.

- [ ] **Step 5: Add sanitized config and systemd examples**

`deploy/production/alert.env.example` contains names and safe non-secret defaults only. The service contract is:

```ini
[Service]
Type=oneshot
WorkingDirectory=%h/Novel-TNN
EnvironmentFile=%h/.config/novel-tnn/alert.env
ExecStart=%h/Novel-TNN/.venv/bin/python -m scripts.dispatch_operational_alerts
UMask=0077
TimeoutStartSec=90
```

The timer uses a five-minute cadence, `Persistent=true`, and is not enabled by repository changes.

- [ ] **Step 6: Document validation and approval boundaries**

Update the runtime alert runbook with configuration permissions (`0700` directory, `0600` environment file), dry synthetic command, receipt schema, retry/dedupe behavior, timer inspection commands, and an explicit statement that external delivery and timer enablement require operator approval.

- [ ] **Step 7: Run script tests and shell syntax checks**

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python \
  -m pytest -q -s tests/test_operational_alert_scripts.py
for script in scripts/*.sh; do bash -n "$script"; done
```

- [ ] **Step 8: Run the four-class synthetic smoke**

```bash
ALERT_SMOKE_DIR="$(mktemp -d)"
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python \
  -m scripts.smoke_operational_alerts --receipt-dir "$ALERT_SMOKE_DIR"
find "$ALERT_SMOKE_DIR" -maxdepth 1 -type f -name 'alert-*.receipt.json' -print
```

Expected: four delivered classes and four receipt files. Remove only the printed temporary directory after validating its exact `mktemp` path.

- [ ] **Step 9: Commit operational entrypoints**

```bash
git add \
  scripts/dispatch_operational_alerts.py \
  scripts/smoke_operational_alerts.py \
  tests/test_operational_alert_scripts.py \
  deploy/production/alert.env.example \
  deploy/systemd/user/novel-tnn-alert-dispatch.service \
  deploy/systemd/user/novel-tnn-alert-dispatch.timer \
  docs/operations/runtime-alerts-and-rollback.md
git commit -m "feat: schedule operational alert delivery"
```

---

### Task 4: Build and pin real local image IDs

**Files:**
- Create after build: `deploy/production/compose.release.operational-observability-20260809-r1.yaml`
- Modify: `tests/test_production_release_contract.py`
- Modify: `tests/test_runtime_identity.py`
- Modify: `docs/operations/runtime-alerts-and-rollback.md`

**Interfaces:**
- Consumes: source implementation commit from Tasks 1-3 and Docker targets `api` / `import-worker`.
- Produces: literal API/worker `sha256:` IDs in a release overlay and verified `/api/version.image_digest`.

- [ ] **Step 1: Add failing release-contract tests before the overlay exists**

Add tests that load the new overlay, extract both `NOVEL_IMAGE_DIGEST` values, and assert:

```python
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
assert DIGEST_PATTERN.fullmatch(api_digest)
assert DIGEST_PATTERN.fullmatch(worker_digest)
assert api_digest != worker_digest
assert "unknown" not in overlay.lower()
```

Extend the version endpoint test to set a 64-hex API digest and assert the response returns it exactly.

- [ ] **Step 2: Run provenance tests and verify RED**

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python \
  -m pytest -q -s tests/test_production_release_contract.py tests/test_runtime_identity.py
```

Expected: FAIL because the new overlay does not exist.

- [ ] **Step 3: Commit the RED provenance contracts before building**

```bash
git add tests/test_production_release_contract.py tests/test_runtime_identity.py
git commit -m "test: require pinned release image identities"
git status --short
```

Require a clean tree after this commit and record `SOURCE_COMMIT="$(git rev-parse HEAD)"`. The test is intentionally RED only because the release overlay is still absent. Do not build from uncommitted source.

- [ ] **Step 4: Build both tagged images from the exact source commit**

```bash
SOURCE_COMMIT="$(git rev-parse HEAD)"
RELEASE_ID="operational-observability-20260809-r1"
BUILD_TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
API_TAG="novel-pipeline-api:${RELEASE_ID}"
WORKER_TAG="novel-pipeline-import-worker:${RELEASE_ID}"

docker build --target api \
  --build-arg NOVEL_GIT_SHA="$SOURCE_COMMIT" \
  --build-arg NOVEL_BUILD_TIMESTAMP="$BUILD_TIMESTAMP" \
  --build-arg NOVEL_RELEASE_ID="$RELEASE_ID" \
  --build-arg NOVEL_IMAGE_TAG="$API_TAG" \
  -t "$API_TAG" .

docker build --target import-worker \
  --build-arg NOVEL_GIT_SHA="$SOURCE_COMMIT" \
  --build-arg NOVEL_BUILD_TIMESTAMP="$BUILD_TIMESTAMP" \
  --build-arg NOVEL_RELEASE_ID="$RELEASE_ID" \
  --build-arg NOVEL_IMAGE_TAG="$WORKER_TAG" \
  -t "$WORKER_TAG" .
```

- [ ] **Step 5: Capture and validate immutable IDs**

```bash
API_DIGEST="$(docker image inspect "$API_TAG" --format '{{.Id}}')"
WORKER_DIGEST="$(docker image inspect "$WORKER_TAG" --format '{{.Id}}')"
[[ "$API_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "$WORKER_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
[[ "$API_DIGEST" != "$WORKER_DIGEST" ]]
printf 'api=%s\nworker=%s\n' "$API_DIGEST" "$WORKER_DIGEST"
```

- [ ] **Step 6: Create the release overlay with the exact observed values**

Use `apply_patch` to create an overlay with exactly two services. `api.image` is `novel-pipeline-api:operational-observability-20260809-r1` and its `NOVEL_IMAGE_DIGEST` is the literal value printed as `api=` in Step 5. `import-worker.image` is `novel-pipeline-import-worker:operational-observability-20260809-r1` and its digest is the literal value printed as `worker=`. The regex tests enforce that both committed values are full lowercase `sha256:` IDs and are different.

- [ ] **Step 7: Render Compose and probe isolated API provenance**

Use sanitized temporary secrets and an isolated data directory:

```bash
docker compose \
  -f compose.yaml \
  -f deploy/production/compose.release.operational-observability-20260809-r1.yaml \
  config > /tmp/novel-pr10-compose.yaml
```

Start only an isolated API container on loopback port `17860` with the overlay and verify:

```python
payload = requests.get("http://127.0.0.1:17860/api/version", timeout=10).json()
assert payload["image_digest"] == API_DIGEST
assert payload["image_digest"] != "unknown"
```

Remove only the isolated container/project and temporary data created by this step; do not touch `novel-tnn-wsl` production containers.

- [ ] **Step 8: Run provenance tests until GREEN**

Run the command from Step 2 and require all tests to pass.

- [ ] **Step 9: Commit the provenance overlay and contracts**

```bash
git add \
  deploy/production/compose.release.operational-observability-20260809-r1.yaml \
  tests/test_production_release_contract.py \
  tests/test_runtime_identity.py \
  docs/operations/runtime-alerts-and-rollback.md
git commit -m "ops: pin operational release image identities"
```

---

### Task 5: Run the complete PR10 verification gate

**Files:**
- Verify all files changed by Tasks 1-4.

**Interfaces:**
- Consumes: completed implementation and provenance commits.
- Produces: fresh verification evidence and a clean PR10 worktree.

- [ ] **Step 1: Run all focused operational tests**

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python -m pytest -q -s \
  tests/test_operational_metrics.py \
  tests/test_operational_alert_delivery.py \
  tests/test_operational_alert_scripts.py \
  tests/test_runtime_identity.py \
  tests/test_production_release_contract.py
```

- [ ] **Step 2: Run backend lint/typecheck and full backend suite**

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/lint.sh
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python -m pytest -q -s
```

- [ ] **Step 3: Validate Python and shell syntax**

```bash
/home/thenam176/Novel-TNN/.venv/bin/python -m compileall -q app scripts tests
for script in scripts/*.sh; do bash -n "$script"; done
```

- [ ] **Step 4: Repeat synthetic delivery and provenance probes**

Run the Task 3 synthetic smoke and Task 4 Compose/API provenance probe using new isolated temporary paths. Confirm four delivered receipt classes and exact API digest equality.

- [ ] **Step 5: Inspect the final branch**

```bash
git diff main...HEAD --check
git status --short --branch
git log --oneline --decorate main..HEAD
```

Expected: all checks exit `0`, no secret or temporary receipt is tracked, and the only image identities committed are validated `sha256:` IDs.
