# API and Runtime Evidence

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Live identity

- Release ID: `ws7-production-20260723-r1`.
- Git SHA: `5dd78353bbff3244af03eda054084b323b63d3c2`.
- Schema revision: `2026-07-14-import-job-persistence-phase5`.
- Readiness: `ready_with_degraded_capabilities`.
- TTS reason: `gpu_unavailable`.

[Source] internal `/api/version`, `/api/ready`, and `/api/health` probes

## Container state

API and worker were healthy with restart count `0`, OOM `false`, non-root user `novel`, read-only root filesystems, dropped capabilities, no-new-privileges, and CPU, memory, and PID limits. The worker heartbeat was fresh at under one second. [Source] fresh `docker inspect`, `docker stats`, heartbeat stat, and `scripts/check-runtime-contract.py`

## Queue state

Production contained 313 completed, 17 failed historical, and 2 interrupted historical mobile jobs. No running, stale-running, or failed-without-error jobs were observed. [Source] read-only SQLite query on `/data/pipeline.db`

## Logs

A 24-hour aggregate found zero traceback, ERROR, CRITICAL, WARNING, Authorization header, bearer token, cookie header, or obvious secret-assignment matches in API and worker container logs. No raw log content was copied into reports. [Source] fresh redacted aggregate script
