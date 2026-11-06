# Live User Experience

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Confirmed live workflows

- Login and authenticated shell.
- Dashboard, Library, Jobs, and More navigation.
- Book to Reader navigation.
- Reader text display and chapter navigation.
- Operator pages for Import, Sources, Glossary, Providers, Export, Status, and Settings.

[Source] fresh Playwright screenshots under `/tmp/novel-tnn-live-audit/controller/mobile-nav/`, `/tmp/novel-tnn-live-audit/controller/mobile-reader/`, and `/tmp/novel-tnn-live-audit/controller/desktop-pages/`

## User-facing strengths

- Mobile navigation is consistent and does not overflow horizontally.
- Reader typography is readable and chapter controls stay reachable.
- Empty Jobs state explains how jobs are created.
- Import uses a clear staged flow.
- Status separates API, providers, jobs, queue, backup, and security information.

## User-facing gaps

- First-session offline can blank after the UI reports a successful cache action. See UX-PWA-001.
- Fixed bottom navigation or chapter controls can cover the lowest visible copy at short viewports. See UX-MOB-007.
- Reader modes and offline actions are nested under More, reducing discoverability. See UX-DISC-008.
- Dense provider and glossary tables use small secondary text.

## Confidence

High for navigation and Reader display. Medium for destructive or paid workflows because production mutation was prohibited and those paths were verified only through isolated tests and source contracts.
