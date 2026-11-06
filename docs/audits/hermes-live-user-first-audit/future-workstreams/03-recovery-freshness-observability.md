# Workstream 3: Recovery Freshness Observability

Goal: Expose external backup and restore-drill freshness without exposing archives or passphrases.

Scope:
- Define a minimal receipt schema: status, completed timestamp, archive hash identifier, validation counts, and producer version.
- Publish receipts atomically with restrictive permissions.
- Let runtime read only the receipt, not backup contents or credentials.
- Add stale and missing states to authenticated metrics and Status UI.
- Add external alert thresholds.

Required verification: missing, stale, corrupt, future timestamp, wrong release, and fresh receipt tests; isolated restore drill; no secret or path leakage.
