# Operations and Observability

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Strong signals

- Health and readiness endpoints distinguish core readiness from degraded optional TTS.
- Release identity and schema revision are exposed.
- Worker heartbeat is fresh.
- Container health, resource limits, restart count, and OOM state are inspectable.
- Status UI exposes job, queue, capability, security, and recovery sections.

[Source] live API probes, Docker inspection, Status screenshots

## Gaps

1. External backup freshness and restore freshness are outside the runtime evidence boundary.
2. No tested external notification path was found for health, queue, failed-job, backup, or restore alerts.
3. Cloudflare Analytics CSP noise reduces console signal quality.
4. Worker log volume is minimal, which is acceptable while healthy but leaves limited process-level history.

## Verdict

Observability: **6.8/10, GO_WITH_LIMITATIONS**. Local diagnosis is good. Unattended failure notification and recovery freshness need a small external watchdog or signed receipt ingestion.
