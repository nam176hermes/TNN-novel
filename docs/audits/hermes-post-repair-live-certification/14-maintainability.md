# Maintainability


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Static inventory

The scan covered 344 source files. Twenty-four modules exceed 1,000 lines and eight exceed 2,000 lines. [Source: evidence/maintainability-scan.json]

| Module | Lines |
|---|---:|
| `app/database/db.py` | 5,633 |
| `app/mobile_api/services/pipeline_service.py` | 5,289 |
| `web/src/components/ReaderView.tsx` | 4,247 |
| `app/ingestion/source_adapters.py` | 2,842 |
| `web/src/components/ImportPanel.tsx` | 2,455 |
| `web/src/App.tsx` | 2,134 |

Largest ownership concentrations include `PipelineService` at about 3,130 lines, `build_default_source_adapters` at about 1,386 lines, and `_migrate_legacy_schema` at about 883 lines. [Source: evidence/maintainability-scan.json]

## Extraction outcome

Bounded Reader and TTS extractions preserved the test baseline. Reader state correctness, PWA, registry, and TTS privacy contracts pass. File size alone is not evidence for another broad refactor.

## Risks that justify narrow future extraction

- Reader request ownership still permits one duplicate translation fetch.
- Recovery scripts split permission expectations across host runner and container publisher.
- The adapter factory remains a 1,386-line function despite a canonical registry contract.
- A static import-graph scan reports two strongly connected groups. This is `SUSPECTED` because package re-exports can create false positives.

## Recommendation

Do not begin a repository-wide cleanup. Extract only a contract that has repeated defects, conflicting ownership, security risk, or independent-test blockage. Require caller-impact analysis and full relevant tests.

## Verdict

**6.5/10**, up from 6.3 due verified bounded extraction, with substantial P2 ownership debt remaining.
