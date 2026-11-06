# Production Operations and Observability

## Health

Both production containers were running, healthy, and had zero restarts. Local and public health/readiness returned HTTP 200. [Source: Docker inspect and curl probes]

## OPS-002: API hardening drift

| Control | API | Worker |
|---|---|---|
| Read-only root | yes | yes |
| Non-root user | yes | yes |
| Drop all capabilities | not observed | yes |
| No new privileges | not observed | yes |
| Memory limit | none | 1.5 GiB |
| CPU limit | none | 2 CPUs |
| PID limit | none | 384 |

[Source: Docker inspect]

Classification: P1, REPRODUCED.

## OPS-003: provenance gap

API and worker use different historical image tags. `/api/version` returns version `0.1.0` but no Git SHA or image digest. [Source: Docker inspect and version endpoint]

Classification: P2, REPRODUCED.

## OPS-004: readiness blind spot

`/api/ready` reports database, storage, disk, jobs table, and public configuration. Its jobs check counts database rows and does not inspect the worker heartbeat. TTS CUDA/runtime availability is also absent. [Source: readiness response and `app/mobile_api/routers/health.py:129-136`]

Classification: P1, CODE_EVIDENCE.

## Resource snapshot

- API: 2.93 percent CPU, 233 MiB memory, 3 PIDs.
- Worker: 0.33 percent CPU, 87.67 MiB memory, 2 PIDs.

This snapshot did not show immediate pressure. [Source: `docker stats --no-stream`]

## OBS-001: metrics do not leave the process

The code has bounded in-memory metrics and a snapshot method, but no route or exporter caller was found. No Prometheus, Grafana, Loki, OpenTelemetry, Sentry, or Alertmanager configuration was found in the audited repository. [Source: source and configuration search]

Classification: P2, CODE_EVIDENCE.

API logs for the previous 24 hours contained 2,302 lines with no matched error, warning, traceback, or 5xx token. Worker Docker logs contained zero lines. Absence of logged errors is not equivalent to alert coverage. [Source: aggregate Docker log probe]

Verdict: operational observability NO-GO.
