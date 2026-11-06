# Future workstream 1: recovery continuity and receipts

## Objective

Make current backup and restore receipt workflows executable under the hardened UID 10001 data ownership model, then prove a complete isolated drill without weakening confidentiality.

## Included issues

- `OPS-RECOVERY-001`

## Excluded scope

No production restore, archive deletion, retention cleanup, provider change, deployment, or broad backup redesign.

## Dependencies

Current production image digest, current release ID, protected backup environment, a copied database, one existing encrypted archive, and an isolated receipt directory.

## Implementation phases

1. Reproduce host preflight and publisher ownership conflict with a minimal fixture.
2. Define one explicit directory and ACL contract for host validation and UID 10001 publication.
3. Update script tests before implementation.
4. Apply the smallest script and protected environment changes.
5. Run config validation and complete isolated restore.
6. Verify receipt ingestion, freshness metrics, and failure preservation.
7. Return a HANDOFF with diff and evidence. Do not restart production.

## Test gates

Focused recovery tests, shell syntax, config matrix, non-root publisher, checksum failure, corrupt receipt, stale and wrong-release receipt, isolated encrypted restore exit 0, authenticated Reader smoke, full verification with E2E.

## Approval gates

Protected environment edits, ACL or permission changes, `chmod`, `chown`, systemd execution, production backup creation, off-site API calls, and production receipt publication require explicit approval.

## Rollback

Restore the previous scripts and protected environment backup, remove only newly created isolated receipt fixtures, and leave all published archives untouched.

## Commit strategy

One test commit, one minimal implementation commit, one documentation and evidence commit. No deploy commit.

## Definition of Done

Current config validates, next scheduled backup contract is executable, isolated restore exits 0, both receipt kinds parse as fresh, status and metrics agree, all tests pass, and controller verification confirms the diff.
