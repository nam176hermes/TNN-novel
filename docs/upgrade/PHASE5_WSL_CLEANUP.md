# Phase 5 — WSL Migration Preservation and Cleanup Record

**Completed:** 2026-07-17

This record closes the Windows-mounted to native-WSL migration. It preserves
the recovery material and development history that were required for a safe
cutover. After the agreed soak period and explicit operator approval, the
legacy Windows working directories were removed; this did not alter the
retained archives or the native-WSL production tree.

## Scope and safety boundary

- Production continues to run from the WSL repository and its dedicated API
  and import-worker containers.
- The preserved archive process did not change source code, import workflow,
  browser-session behavior, or CAPTCHA integration.
- The legacy Windows `data/`, backups, and environment material were copied
  into the protected recovery archive before the old workspace was removed.
- No retained backup or recovery archive was deleted.
- This operational record does not change the P16 application release decision
  in `PLAN_B.md`.

## Production and recovery verification

At the Phase 5 check point, the WSL API and worker were healthy with zero
container restarts. Local health/readiness and public health checks returned
HTTP 200. An authenticated API/Library/Reader smoke check also passed at a
390px mobile viewport after the backup completed.

### Post-cutover backup

The backup was created from the live WSL data tree using the production image
with network disabled. It did not include `.env` or any other configured
secrets.

| Property | Verified value |
|---|---:|
| Archive | `novel-pipeline-backup-20260717-123907.tar.gz` |
| Listing/sidecar status | `READY` |
| Archive size | 5,638,511,980 bytes |
| Source files represented | 44,470 |
| Source data size represented | 6,412,814,405 bytes |
| Secrets included | No |
| Encrypted | No |
| `data/pipeline.db` archive member | Present (51,388,416 bytes) |

The production image deliberately has no repository virtual environment. When
performing an operator backup *inside that image*, invoke
`python scripts/ops.py backup --out-dir …` rather than the local-development
`scripts/backup-local.sh` wrapper, which expects `.venv` in the checkout.

### Restore drill

The new backup was restored offline into a dedicated drill directory, not into
the production data mount. The drill passed the built-in restore check and an
additional immutable read-only SQLite verification:

| Check | Result |
|---|---|
| Restore drill | Pass |
| SQLite `integrity_check` | `ok` |
| SQLite foreign-key violations | 0 |
| Restored library rows | 1 |

`immutable=1` was used only for the final read-only inspection because the
drill directory was intentionally mounted read-only. The normal restore drill
had already opened the writable isolated copy successfully.

## Archive inventory

Archives are stored under
`$HOME/Novel-TNN-archives/phase5-20260717T123847Z/`. They are independent
copies; their sources were left untouched. Verify all artifacts with
`sha256sum --check SHA256SUMS` from that directory.

| Archive | Size (bytes) | SHA-256 | Contents |
|---|---:|---|---|
| `legacy-repository-working-tree.tar.gz` | 2,412,417,641 | `20b91cacc78219de94c4f06d6ff6b46efa8a3357abab25b804386b310c9b4127` | Legacy Git history and working tree, including its four uncommitted source changes. Excludes `data/`, `backups/`, `.env`, virtual environments, node modules, and caches. |
| `legacy-worktree-p2c-background-retention-modularity.tar.gz` | 6,843,272 | `a5315621783570024ef1c3574ba598ca8c753202bbce7c77724088c21bcaa977` | The archived linked worktree source snapshot and its Git pointer. |
| `migration-reports-p1-p5.tar.gz` | 59,792,362 | `a2735f638c8dc331219018ade61992b51a91d9731bcddbc38b2ec221c523bcdc` | Migration state/report material for Phases 1A through 5. |

The legacy main repository archive includes `.git/HEAD` and the changed
`Import` route, Compose file, and affected tests. The worktree archive includes
its `.git` pointer and source tree. The migration-report archive contains each
of the Phase 1A, 2, 3, 4, and 5 directories. The separate
`legacy-windows-backups-20260717T172510Z` archive preserves the legacy backup
set; its checksum manifest passed all six entries before the Windows workspace
was removed.

## Remaining manual tasks

1. Keep the WSL repository, worktree, and protected legacy archives. The
   Windows working directories are no longer runtime or development inputs.
2. Keep the new plain backup protected locally. Create an encrypted off-site
   backup before treating it as disaster-recovery coverage.
3. Continue the normal backup schedule and repeat restore drills at the cadence
   defined in [`../backup-restore.md`](../backup-restore.md).
4. If an archived linked worktree is restored at a different path, repair its
   pointer from the restored main repository with `git worktree repair` before
   using it as a live worktree.
5. Before changing application release status, address the independent P16
   release gates recorded in `PLAN_B.md`; Phase 5 does not waive them.
