# Open issue register

No reproduced P0 or P1 issue is open.

## DEP-001 — Python dependency advisories

| Field | Value |
|---|---|
| Severity | P2 |
| Confidence | CODE_EVIDENCE / tool-reported |
| Domain | dependency security |
| Affected scope | Python environment |
| Evidence | `pip-audit` reported `ecdsa 0.19.2`, `pytest 8.3.3`, and `setuptools 79.0.1` advisories |
| Current counterevidence | runtime JWT uses HS256; pytest/setuptools are test/build tooling |
| Risk | future reachability or tooling exposure; upgrade compatibility unknown |
| Smallest fix | upgrade/remove affected paths using the package manager, then rerun focused auth and full verification |
| Regression plan | auth/token suite, dependency consistency, all backend tests, Docker build/smoke |
| Release decision | accepted for current private deployment; schedule promptly |

No lockfile or dependency was changed during certification.

## OBS-002 — recovery freshness is not visible to container metrics

| Field | Value |
|---|---|
| Severity | P2 |
| Confidence | REPRODUCED |
| Domain | observability / recovery |
| Evidence | current encrypted backup and restore drill pass, while metrics report missing/stale freshness |
| Root cause | backup directory is operator-owned outside the container; old scheduled drill predates runtime status publication |
| Risk | false-positive alerts and failure to distinguish stale recovery evidence from an integration gap |
| Smallest fix | publish redacted atomic status receipts into the bounded runtime status directory |
| Regression plan | fresh/stale/missing receipt tests, permissions, authenticated metrics, alert evaluation |
| Release decision | accepted with documented manual verification |

## OBS-003 — external alert delivery not demonstrated

| Field | Value |
|---|---|
| Severity | P2 |
| Confidence | CODE_EVIDENCE / NOT_TESTED externally |
| Domain | observability |
| Evidence | deterministic alert list exists; no external notifier/uptime delivery was demonstrated |
| Risk | operator may not learn of an outage without polling |
| Smallest fix | configure one bounded external delivery channel and an external public-health monitor |
| Regression plan | controlled test alert, delivery receipt, redaction test, failure/backoff test |
| Release decision | accepted for attended single-operator use |

## Deferred/non-defect validation gaps

| ID | Status | Reason |
|---|---|---|
| TEST-GPU-001 | NOT_TESTED | No supported GPU was used; no-CPU-fallback behavior passed. |
| TEST-CHALLENGE-001 | BLOCKED by authorization | Protected third-party challenge behavior was not live-tested. |
| A11Y-CERT-001 | NOT_TESTED | No full screen-reader/WCAG conformance audit. |
| PERF-SOAK-001 | NOT_TESTED | No long-duration low-end Android memory soak. |
| ROLLBACK-DRILL-001 | NOT_TESTED live | Rollback overlay/commands validated; production rollback not executed. |

These entries are not presented as reproduced defects.
