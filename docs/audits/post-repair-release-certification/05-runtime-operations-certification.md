# Runtime and operations certification

## Verdict

Runtime/readiness/provenance: **GO**

Observability: **GO_WITH_LIMITATIONS**

## Container controls

| Control | API | Import worker |
|---|---|---|
| User | non-root `novel` | non-root `novel` |
| Read-only root | yes | yes |
| Capability drop | `ALL` | `ALL` |
| `no-new-privileges` | yes | yes |
| PID limit | 256 | 384 |
| Memory limit | 768 MiB | 1.5 GiB |
| CPU limit | 1 | 2 |
| Health | healthy | healthy |
| Restart count | 0 | 0 |

`scripts/check-runtime-contract.py` passed for both live containers. Fresh API
and worker images also built from the certified source, and the API image
passed an isolated alternate-port smoke.

## Health and readiness

Local and public health/readiness/version returned HTTP 200. Current readiness
is `ready_with_degraded_capabilities`, with:

- API, database, storage, disk, and configuration ready;
- fresh worker heartbeat;
- worker queue-claim capability true;
- API/worker release match true;
- optional TTS unavailable with reason `gpu_unavailable`;
- Reader/core readiness unaffected by optional TTS.

The local and public readiness payloads differed only in the live heartbeat
age measured at request time.

## Provenance

| Field | Value |
|---|---|
| Release ID | `ws6-production-20260723-r1` |
| Git SHA | `13e2b05d2142c6b5ae94d6dcbc718930cb8b8565` |
| API image | `sha256:6c86259e8cd65f4f4120b0c533f86ee2587706f45c2214937c141f65f2364c8f` |
| Worker image | `sha256:793e726c5a31ec1a10ca85f8ed94b8e36c3af096459ab92bd270b4cad6b82cef` |
| Schema | `2026-07-14-import-job-persistence-phase5` |

API and worker report the same release ID. The deployed Git SHA equals the
certified source HEAD.

## Metrics and alerts

The operational metrics endpoint is authenticated; an unauthenticated request
returned HTTP 401. Focused tests validate authenticated response shape and
redaction. A read-only production snapshot reported:

- release match true;
- worker ready with fresh heartbeat;
- queue depth 0;
- storage free approximately 585.6 GB;
- database size approximately 51.4 MB;
- artifact scan status `ok`, 1,774 paths, 0 errors;
- auth-session totals consistent with the bounded retention report;
- TTS unavailable;
- deterministic alerts for historical failed jobs, backup freshness, and
  restore-drill freshness.

## OBS-002 — external recovery freshness integration

Severity: P2. Status: open/accepted.

Production encrypted backups live in an operator-owned directory outside the
API container, while metrics scan the in-container backup location. The last
scheduled restore drill predates the WS4 status-publishing path. Consequently,
metrics report backup/drill freshness as missing or stale even though the
external backup and fresh certification restore drill passed.

Smallest follow-up:

1. publish a redacted, atomic backup-freshness status file into the bounded
   runtime status directory after successful encrypted backup/upload;
2. publish the same for every future scheduled restore drill;
3. consume only these aggregate status files in the metrics service;
4. test stale/fresh/missing states and permissions;
5. configure and exercise one external alert-delivery channel.

Do not mount the complete backup directory into the API merely to close this
gap.

## Backup operations

- Backup timer active and scheduled.
- Latest encrypted backup is current and non-zero.
- Scheduled restore drill last passed on 2026-07-22.
- Fresh certification restore drill passed on 2026-07-23.

## Limitations

- External alert delivery and public uptime monitoring were not demonstrated.
- Container restart telemetry is available by runtime inspection but is not
  exported by an in-process service without an external monitor.
- No production restart, deployment, or ingress change occurred.
