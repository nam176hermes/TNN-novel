# Current baseline and release identity


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Repository and toolchain

| Field | Value |
|---|---|
| Repository | `/home/thenam176/Novel-TNN` |
| Branch | `upgrade-b/00-baseline-and-agent-guidance` |
| HEAD | `f90fd33cae63d7e3bbb621c8d1830f974c91d8b7` |
| Release source | `3a781fa3cd48398dd298466118d8c1acc4d291f6` |
| Worktree | Dirty, four untracked audit or roadmap groups before this package |
| Python | 3.11.15 |
| Node | 22.23.1 |
| npm | 10.9.8 |
| Docker | 29.1.3 |
| Compose | 2.40.3 |
| Playwright CLI | 1.61.1 |

[Source: evidence/live-runtime-second-snapshot.json]

## Runtime identity

| Component | Image reference | Immutable local image ID |
|---|---|---|
| API | `novel-pipeline-api:upgrade-b-production-20260725-r1` | `sha256:c42e717988df91910a0a4712082684128eea994f3325620bf3cf2c23f4857cf3` |
| Import worker | `novel-pipeline-import-worker:upgrade-b-production-20260725-r1` | `sha256:03b84a071b9e884a63f963084310a15d252a2bffd130c61203b33de7f4604050` |

Production reports app version `0.1.0`, frontend version `0.1.0`, build timestamp `2026-07-25T03:40:16Z`, release ID `upgrade-b-production-20260725-r1`, and schema revision `2026-07-14-import-job-persistence-phase5`. API and worker release IDs match. [Source: evidence/live-runtime-second-snapshot.json]

## Source-to-image proof

The production release SHA is an ancestor of repository HEAD. A file-level comparison checked 173 tracked application files between the release Git tree and the API image: zero missing, zero extra, and zero hash mismatches. Docker inspection resolves the live immutable image IDs. `/api/version` still reports `image_digest=unknown`, so digest provenance is externally reconciled rather than self-contained in the application payload. [Source: evidence/runtime-release-summary.json] [Source: evidence/live-runtime-second-snapshot.json]

## Endpoint topology

- Public: `https://novel-tnn.tradingcompanydirect.com/`
- Local API: `http://127.0.0.1:7860/`
- Isolated shadow: `http://audit.localhost:17861/`

Local and public health and readiness returned HTTP 200 in the fresh second snapshot. [Source: evidence/live-runtime-second-snapshot.json]

## Validation baseline

The production-aware full verification gate passed after setting `NOVEL_PIPELINE_PRODUCTION_ENV_FILE`. A first invocation without the required runtime contract correctly failed the environment gate and was not counted as a test failure. The verified gate included compile, shell syntax, environment, lint and typecheck, backend, dependency consistency, frontend tests, build, browser prerequisite, and E2E. [Source: evidence/test-summary.json]
