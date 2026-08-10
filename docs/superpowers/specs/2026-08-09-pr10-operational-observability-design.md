# PR10 Operational Observability Design

## Goal

Deliver four operational alert classes through a generic HTTPS webhook with bounded retry and redacted atomic receipts, and make the production release report real immutable local Docker image IDs instead of `image_digest=unknown`.

## Scope

The PR covers:

- backup failure;
- wrong-release recovery receipts;
- stale required worker heartbeat;
- stuck queued jobs;
- a standalone alert dispatcher and periodic systemd unit examples;
- synthetic loopback delivery evidence for every alert class;
- a new release overlay containing real local API and worker image IDs;
- `/api/version` verification against the pinned API image ID.

It does not deploy or restart production, enable timers, send a request to an external service, register a provider account, or modify DNS, Cloudflare, firewall, or reverse-proxy configuration.

## Alert production

Existing operational metrics remain the source of truth. Alert evaluation adds or preserves stable codes required by the dispatcher:

| Alert class | Source alert codes |
| --- | --- |
| `backup_failure` | `backup_failed` |
| `wrong_release_receipt` | `external_backup_wrong_release`, `restore_drill_wrong_release` |
| `worker_stale` | `worker_stale` |
| `stuck_jobs` | `queue_stale` |

`backup_failed` is derived from failed backup mobile jobs or failed `backup_job_terminal` state without exposing job IDs or filenames. `worker_stale` is emitted only when a required worker reports the explicit `stale` heartbeat state; the broader existing `worker_not_ready` rule remains intact.

## Dispatcher architecture

A standalone application service owns delivery logic. A thin CLI constructs the operational snapshot, selects the four supported classes, and dispatches them. Production scheduling is represented by reviewed user-level systemd service/timer examples; the PR does not enable them.

Running delivery outside the API request path keeps webhook latency and failure isolated from API and worker correctness.

### Webhook contract

The outbound JSON contains only:

- schema version;
- alert class;
- stable alert code;
- severity;
- release ID;
- observed timestamp;
- deterministic incident fingerprint.

It excludes alert free text, webhook URL, bearer token, response body, job or user identifiers, filenames, chapter or book data, and filesystem paths.

Production webhook URLs must use HTTPS. Plain HTTP is accepted only for an explicit loopback synthetic mode. An optional bearer token is read from environment at dispatch time and is never logged or persisted.

### Retry and deduplication

- At most three attempts per incident per invocation.
- Each request has a bounded timeout.
- Retry delay is bounded and injectable for tests.
- Network errors and non-2xx responses produce a redacted failed receipt and a non-zero CLI result; they never crash API or worker processes.
- A delivered receipt with the same fingerprint suppresses duplicate delivery.
- A changed class/code/release/incident state produces a new fingerprint and is delivered.

## Delivery receipts

Each class owns one atomic receipt under `DATA_DIR/logs/runtime/`:

- `alert-backup_failure.receipt.json`;
- `alert-wrong_release_receipt.receipt.json`;
- `alert-worker_stale.receipt.json`;
- `alert-stuck_jobs.receipt.json`.

Receipts are regular files written through a same-directory temporary file, `fsync`, atomic replace, and final mode `0600`. The bounded schema contains delivery state, alert class, code, attempt count, observed/delivered timestamp, release ID, fingerprint, and HTTP status when available. It contains no endpoint, credential, response body, private data, or absolute path.

## Synthetic delivery evidence

A smoke command starts a loopback receiver, generates one synthetic incident for each supported class, dispatches all four through the production delivery component, and validates four delivered receipts. Synthetic mode uses isolated temporary directories and synthetic release values. It performs no external network request and does not touch the operator database or production receipt directory.

Unit tests additionally cover payload allowlisting, HTTPS enforcement, loopback-only HTTP, retry success, exhausted retry, failed-receipt redaction, atomic permission, and fingerprint deduplication.

## Image provenance

After implementation and tests are green:

1. commit the source implementation;
2. build API and worker images from that exact source commit with a shared release ID and explicit tags;
3. inspect each immutable local Docker image ID (`sha256:...`);
4. add a release overlay that pins the reviewed image tags and passes the corresponding literal ID as `NOVEL_IMAGE_DIGEST` to each service;
5. render Compose configuration and run isolated container probes;
6. verify `/api/version.image_digest` equals the API image ID and is not `unknown`;
7. verify the worker identity carries its own pinned image ID where worker identity is exposed.

The overlay-only provenance commit does not change the Docker build inputs copied by the Dockerfile (`app/`, `scripts/`, and built `web/`), so the recorded IDs remain the immutable artifacts built from the source implementation commit.

## Configuration

A sanitized environment example documents:

- webhook URL;
- optional bearer token placeholder;
- request timeout;
- maximum attempts;
- dispatch interval;
- API and worker image IDs.

No live endpoint or credential is committed.

## Validation

Run:

1. focused operational alert evaluation and delivery tests;
2. synthetic four-class receiver/receipt smoke;
3. runtime identity and production release contract tests;
4. shell syntax checks for new operational scripts;
5. backend lint/typecheck and full backend suite;
6. API and worker Docker builds;
7. Compose configuration render;
8. isolated `/api/version` and worker identity probes;
9. `git diff --check`.

## Definition of done

- Each of the four alert classes produces a successful synthetic webhook delivery and a redacted mode-`0600` receipt.
- Retry and deduplication behavior are deterministic and tested.
- No external webhook is contacted by tests or smoke validation.
- The reviewed release overlay contains real immutable API and worker image IDs.
- The isolated production-style `/api/version` response reports the exact API image ID, never `unknown`.
- No deployment, restart, timer enablement, or external-service mutation occurs.
