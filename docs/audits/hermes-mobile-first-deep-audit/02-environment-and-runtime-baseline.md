# Environment and Runtime Baseline

## Repository

- Root: `/home/thenam176/Novel-TNN`
- Branch: `upgrade-b/00-baseline-and-agent-guidance`
- Commit: `286cd49129494604eb1fe6413307375a15bc4a0b`
- Worktree was dirty before audit. The audit did not alter listed product files. [Source: fresh `git status --short`, 2026-07-22]

## Production topology

| Service | State | Health | Restart count |
|---|---|---|---:|
| API | running | healthy | 0 |
| Import worker | running | healthy | 0 |

Both use user `novel` and a read-only root filesystem. [Source: fresh `docker inspect`]

## Baseline test results

| Gate | Result |
|---|---|
| Backend pytest | FAIL, 1,110 passed and 3 failed |
| Frontend Vitest | PASS, 82 files and 740 tests |
| Frontend typecheck | PASS |
| Frontend build | PASS |
| Dependency consistency | PASS |
| Environment checker | Four topology-sensitive failures |

The backend failures were two private-network browser guard tests and one adapter registry contract test. [Source: `/tmp/novel-tnn-audit-baseline.log`]

## Verification wrapper defect

The aggregate process returned exit code zero because commands continued after failure and the final `git diff --check` succeeded. The output itself records failed checks. [Source: baseline process output and `scripts/verify.sh`]

## Runtime endpoints

Inside the API container:

| Endpoint | HTTP | Measured latency |
|---|---:|---:|
| `/api/health` | 200 | 7.23 ms |
| `/api/ready` | 200 | 3.17 ms |
| `/api/version` | 200 | 1.23 ms |

Local and public root/readiness endpoints returned HTTP 200. [Source: fresh curl and container probes]

## Runtime identity gap

The API image is `mobile-bottom-safe-fix-20260720-r1`; the worker image is `security-audit-20260718-r1`. `/api/version` reports `0.1.0` but no Git commit or image digest. [Source: Docker inspect and `/api/version`]
