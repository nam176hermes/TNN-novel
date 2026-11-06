# Foundation and Maintainability

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Positive foundation

- Backend and frontend have large automated suites.
- Service, router, schema, repository, and frontend API boundaries are documented.
- Database migrations are idempotent and SQLite-aware.
- Runtime and release scripts fail closed.
- No tracked source diff was present during audit.

[Source] `AGENTS.md`; `scripts/verify.sh`; `tests/conftest.py`; fresh verification

## Hotspots

The code scan found 338 Python, TypeScript, TSX, and CSS files; 27 exceeded 1,000 lines and 10 exceeded 2,000 lines. Key hotspots include:

- `app/database/db.py`: 5,632 lines;
- `app/mobile_api/services/pipeline_service.py`: 5,468 lines;
- `web/src/components/ReaderView.tsx`: 4,246 lines;
- `app/ingestion/source_adapters.py`: 2,841 lines;
- `web/src/components/ImportPanel.tsx`: 2,454 lines.

The largest class, `PipelineService`, spans about 3,315 lines. The scan found 68 Python symbols at or above 100 lines. [Source] fresh line and AST scan

## Test counterweight

Backend tests contain about 31,633 lines across 109 files. Frontend unit tests contain about 27,238 lines across 83 files. Large modules are therefore not untested, but change blast radius remains high. [Source] fresh test inventory

## Verdict

Maintainability: **6.3/10**. Refactor only after P1 repair, one bounded public contract at a time, with caller-impact and full verification.
