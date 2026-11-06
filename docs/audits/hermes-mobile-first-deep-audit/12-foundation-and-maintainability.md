# Foundation and Maintainability

## Static architecture scan

A Python AST import scan covered 139 modules and found no multi-module import cycle. [Source: fresh AST scan]

## MAINT-001: oversized ownership centers

Largest implementation files include:

| File | Lines |
|---|---:|
| `app/database/db.py` | 5,632 |
| `app/mobile_api/services/pipeline_service.py` | 5,468 |
| `web/src/components/ReaderView.tsx` | 4,249 |
| `app/ingestion/source_adapters.py` | 2,802 |
| `web/src/components/ImportPanel.tsx` | 2,454 |
| `web/src/App.tsx` | 2,091 |
| `web/src/state/readerCache.ts` | 1,895 |
| `web/src/api/client.ts` | 1,616 |

[Source: fresh line-count scan]

Classification: P2, CODE_EVIDENCE.

The observed Reader state mismatch, duplicate requests, adapter registry drift, and large test surfaces align with concentrated ownership. Do not begin a broad refactor first. Protect behavior with focused tests, repair defects, then extract stable boundaries.

## TEST-001: adapter registry drift

The baseline registry contract omitted `xbiquge.info`, `xbiquge.so`, `meionovels.com`, `scribblehub.com`, and `lnmtl.com`, causing one backend failure. [Source: baseline pytest output]

Classification: P2, REPRODUCED.

## Foundation priorities

1. Fail-fast verification.
2. Deployed source identity.
3. Worker-aware readiness.
4. Security-header policy.
5. Session retention.
6. Exported metrics and alerts.
7. Narrow module boundaries after defect tests pass.
