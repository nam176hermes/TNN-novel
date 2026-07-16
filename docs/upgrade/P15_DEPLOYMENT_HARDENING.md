# P15 — Deployment hardening

## Scope and process boundary

Production Compose runs two non-root processes built from separate Docker
targets:

- `api` serves FastAPI and the built SPA. It creates and observes durable
  import jobs, but sets `IMPORT_JOB_RUN_IN_API=0` so it does not execute them.
- `import-worker` runs `python -m app.import_worker`, claims P05/P06 SQLite
  tasks atomically, owns source/browser activity, and maintains a safe
  heartbeat under the mounted data directory.

The worker uses the same P14 quota, retry, circuit-breaker, URL-policy, and
observability factory as the API. SQLite task leases remain the source of truth:
an API restart does not remove queued work, and an expired worker lease is
recovered before the next worker claim. The deployment defaults to one worker;
additional workers must be introduced only after validating cross-worker
chapter-order behavior for the affected workload.

`IMPORT_JOB_RUN_IN_API=1` is retained as a local-development compatibility
mode. Do not enable it in the production Compose deployment.

## Verification status

The implementation is covered by mocked worker/browser and static deployment
tests; it does not call a live source or launch Chromium. The targeted P15
suite completed with `49 passed, 1 warning in 111.07s (0:01:51)`. The warning
is the existing `passlib/crypt` deprecation. Full backend verification also
completed with `1030 passed, 2 warnings in 1684.10s (0:28:04)`; the additional
warning is the existing `jieba/pkg_resources` deprecation.

`scripts/lint.sh`, Python `compileall`, shell syntax checks,
`scripts/check-environment.sh`, frontend typecheck, production build, and
`git diff --check` passed. The build retains the known
`sidebar-scenery.png` runtime-resolution warning. The unchanged full Vitest
run reached its startup banner but produced no reporter output for about ten
minutes and was stopped; rerun it in an environment without the known worker
startup/stall issue before release.

The current Codex environment has no Docker CLI (`docker: command not found`),
so image build, `docker compose up`, and in-container health checks could not
be executed here. These are release gates, not optional documentation: run the
commands in the Setup section on the deployment host and attach their output to
the release record.

## Containers and resource boundaries

Both targets run as UID/GID `10001` (`novel`), have a read-only root filesystem,
drop Linux capabilities, set `no-new-privileges`, use an init process, and have
CPU, memory, PID, healthcheck, and stop-grace limits in `compose.yaml`.

Only `import-worker` includes Chromium. It writes its profile and cookie state
to `/tmp` tmpfs, so browser state and cookies are not persisted to the image or
the shared data mount. A worker restart may therefore require normal operator
verification again; never copy a browser profile or cookie file into an image.

The worker healthcheck calls:

```bash
python -m app.import_worker --healthcheck
```

It requires both a reachable SQLite database and a heartbeat no older than
`IMPORT_WORKER_HEARTBEAT_MAX_AGE_SECONDS` (45 seconds by default).

## Network and browser containment

The API and browser worker use separate Compose networks. The browser worker
does not receive the API service name, `host.docker.internal`, API auth secrets,
provider keys, or an internal database network. The shared SQLite file is its
only job-store connection.

Browser request interception validates every top-level request and subresource
through the P02 URL policy. Requests resolving to loopback, private, link-local,
multicast, unspecified, reserved, or metadata addresses are aborted before the
browser can send them. `data:`, `blob:`, and `about:` are local browser values,
not egress requests.

Compose alone cannot express a complete allowlist of Internet destinations or
private CIDRs. Apply an equivalent host/firewall policy to the browser worker
network. The policy must allow only HTTP/HTTPS and DNS egress for the browser
container, then block all internal and metadata ranges. Example nftables rules
for the container address set managed by the operator:

```nft
table inet novel_tnn {
  set browser_workers { type ipv4_addr; flags interval; elements = { 172.30.0.0/24 } }
  chain forward {
    type filter hook forward priority filter; policy accept;
    ip saddr @browser_workers ip daddr { 127.0.0.0/8, 10.0.0.0/8,
      172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 100.64.0.0/10,
      0.0.0.0/8, 224.0.0.0/4, 240.0.0.0/4 } drop
    ip saddr @browser_workers tcp dport { 80, 443 } accept
    ip saddr @browser_workers udp dport 53 accept
    ip saddr @browser_workers tcp dport 53 accept
    ip saddr @browser_workers drop
  }
}
```

Use the actual Docker-assigned worker subnet instead of the illustrative
`172.30.0.0/24`. Keep the P02 in-process policy even with host firewall rules;
both layers are required.

## Secrets and configuration

- `.env` is excluded from image context and is never copied into either image.
- Inject API credentials and provider keys only into `api` through the deployment
  environment or a secret manager. Do not use `env_file` to mount them into the
  browser worker.
- Rotate `MOBILE_API_SECRET` and `MOBILE_API_ADMIN_PASSWORD` in the secret
  store, deploy the new values, then invalidate sessions according to the
  existing auth runbook. Never put a secret in Compose, a command line, a log,
  a browser profile, or a backup manifest.

For public deployments, set `PUBLIC_DEPLOY=1` and exact HTTPS CORS origins. The
existing FastAPI startup gate rejects default credentials and broad public CORS.

## Production runbook

### Setup and migration

1. Create a writable host data directory owned by UID/GID `10001`.
2. Inject the API-only secrets using the deployment secret manager; do not copy
   `.env` to the server or into a container.
3. Build the API and worker targets and inspect their Compose configuration.
4. Start Compose. The API initializes idempotent SQLite migrations on startup;
   the worker then recovers expired task leases before claiming new work.

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose exec api curl -fsS http://127.0.0.1:7860/api/ready
docker compose exec import-worker python -m app.import_worker --healthcheck
```

### Start, stop, and health

```bash
docker compose up -d api import-worker
docker compose stop --timeout 75 import-worker
docker compose stop --timeout 30 api
docker compose logs --tail=200 api import-worker
```

`SIGTERM` causes the worker to stop taking new jobs at the next durable batch
boundary and to close its browser manager. If a process is forcibly stopped,
do not reset the database: allow lease expiry and startup recovery to requeue
the uncompleted task.

### Recover a stuck job or worker crash

1. Inspect the authenticated job snapshot and persisted events; do not inspect
   or log raw source HTML/cookies.
2. Confirm the worker healthcheck and shared data mount.
3. Restart only `import-worker`; it recovers expired leases and idempotent P04
   imports prevent duplicate chapter rows.
4. Use retry only for tasks marked retryable. Cancel deliberately if the source
   requires user verification.

```bash
docker compose restart import-worker
docker compose exec import-worker python -m app.import_worker --healthcheck
```

### Tune limits

Tune only via deployment environment variables and restart the worker:

- `IMPORT_JOB_MAX_CHAPTERS`, `IMPORT_JOB_MAX_ACTIVE_PER_USER`
- `IMPORT_JOB_MAX_RETRIES_PER_TASK`, `IMPORT_JOB_MAX_BYTES_PER_CHAPTER`
- `IMPORT_JOB_MAX_DURATION_SECONDS`
- `SOURCE_CIRCUIT_FAILURE_THRESHOLD`, `SOURCE_CIRCUIT_WINDOW_SECONDS`,
  `SOURCE_CIRCUIT_COOLDOWN_SECONDS`
- `IMPORT_WORKER_POLL_INTERVAL_SECONDS`, resource limits, and the single-worker
  deployment count.

Keep browser concurrency at the P07 default unless a benchmark and source
rate-limit review justify a change. Do not scale worker replicas casually.

### Backup, rollback, and incident response

Before an image/configuration rollout, verify a recent off-site backup and a
restore drill. Roll back by deploying the previous API and worker image tags;
do not roll back or delete SQLite data files. If a migration is involved, use
the documented idempotent migration/rollback note and test it against a copy.

For an incident: isolate public ingress, stop the browser worker first, rotate
suspected credentials, retain only redacted operational evidence, verify backup
integrity, and resume with the worker after the source/network issue is fixed.
Never add CAPTCHA evasion, proxy rotation, fingerprint spoofing, or automatic
challenge solving as an incident workaround.
