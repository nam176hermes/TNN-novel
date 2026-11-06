# Desktop Operator Workflows

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Observed live pages

Import, Sources, Glossary and Style, Providers, Export, Status and Backup, and Settings rendered at `1366x768` and `1440x1000` without horizontal overflow. [Source] screenshots under `/tmp/novel-tnn-live-audit/controller/desktop-pages/`

## Strengths

- Import stages are understandable.
- Provider keys remain masked while cost and usage context remain visible.
- Status separates capabilities, queue state, failed jobs, security, and recovery information.
- Glossary renders a bounded data window rather than an unbounded DOM.

## Limitations

- Provider and glossary tables are dense and use small text.
- Import primary actions can fall below the first viewport.
- Failed-job cards emphasize raw identifiers more than next recovery action.
- The install banner can cover lower Status content.

## Safety

No live retry, provider test, import, export, or restore action was clicked. Isolated E2E covered representative mocked import, translation start, TXT export, mobile pages, and offline behavior. [Source] `npm --prefix web run test:e2e`, 11 passed
