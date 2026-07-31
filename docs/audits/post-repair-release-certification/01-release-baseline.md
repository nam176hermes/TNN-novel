# Release baseline

## Source baseline

| Item | Value |
|---|---|
| Certification branch | `certification/ws7-release-certification` |
| HEAD | `13e2b05d2142c6b5ae94d6dcbc718930cb8b8565` |
| Main worktree branch | `upgrade-b/00-baseline-and-agent-guidance` |
| Main worktree HEAD | `13e2b05d2142c6b5ae94d6dcbc718930cb8b8565` |
| Initial certification status | clean |
| Production config identity | mode 0600, operator-owned, SHA-256 `7399742c8f15c2f31cb78d0779e587fc6c6c23368d01551b61369272c9c7f3d8` |
| Schema revision | `2026-07-14-import-job-persistence-phase5` |

The config hash identifies the file without recording its contents. No secret
value was printed or copied into the repository.

## Toolchain

| Tool | Version |
|---|---|
| Python | 3.11.15 |
| Node.js | 22.23.0 |
| npm | 10.9.8 |
| Docker | 29.1.3 |
| Docker Compose | 2.40.3 |
| Playwright | 1.61.1 |

Tests used `NOVEL_PIPELINE_IGNORE_DOTENV=1` and isolated SQLite/data roots for
mutable workflows. Production checks were limited to read-only DB/filesystem,
container inspection, and non-mutating HTTP probes.

## Production identity

| Component | Image ID | Runtime state |
|---|---|---|
| API | `sha256:6c86259e8cd65f4f4120b0c533f86ee2587706f45c2214937c141f65f2364c8f` | healthy, restart 0 |
| Import worker | `sha256:793e726c5a31ec1a10ca85f8ed94b8e36c3af096459ab92bd270b4cad6b82cef` | healthy, restart 0 |

Both components report release `ws6-production-20260723-r1` and Git SHA
`13e2b05d2142c6b5ae94d6dcbc718930cb8b8565`. The API build timestamp is
`2026-07-23T22:45:47Z`.

## Fresh certification images

The source was rebuilt without deploying it:

| Image | Image ID |
|---|---|
| `novel-pipeline-api:ws7-certification` | `sha256:332cebe15c1c4e5eba418f387d332d2c0c29418fb847fa0d81e3486bb7f9139d` |
| `novel-pipeline-import-worker:ws7-certification` | `sha256:3faf043b2bc3055e15e73cdb66863bfdafcece3a442cf47eaf6ab0592b507dbd` |

An isolated API smoke used the certification image on an alternate loopback
port and isolated volume. Health, readiness, version, runtime limits, and
GPU-unavailable behavior passed. A first harness attempt intentionally failed
closed because an external bind was paired with `PUBLIC_DEPLOY=0`; the corrected
safe staging configuration passed. This was a harness setup correction, not an
application defect.

## Backup and restore baseline

- Newest encrypted backup at certification: 5,638,439,552 bytes, completed
  2026-07-23 19:01 EDT.
- Backup timer: active; last trigger 2026-07-23 03:20 EDT; next scheduled
  2026-07-24 03:31 EDT.
- Last scheduled restore drill: success on 2026-07-22 13:52 EDT.
- Fresh certification restore drill: success on 2026-07-23; isolated temporary
  target, no live-data write, cleaned after evidence capture.

## Worktrees

Existing historical repair worktrees remained untouched. Certification ran in
its own worktree. No branch was merged, rebased, deleted, pushed, or deployed.
