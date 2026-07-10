# Technical Debt Register

## P0

### Local Environment Drift
- Evidence: `scripts/verify.sh` fails in the current environment; backend pytest runs fail on missing `jose` and `pyperclip`; `app.mobile_api` fails to boot because `fastapi/starlette` import resolution is broken in the venv
- Impact: prevents reliable local validation and blocks browser smoke
- Priority: highest
- Proposed action: repair the project environment, then re-run verification from the intended interpreter

### Failing Frontend Integration Test
- Evidence: `web/src/App.integration.test.tsx` fails on translated-library-to-reader navigation
- Impact: indicates a UI copy/flow mismatch or test drift in a key operator path
- Priority: high
- Proposed action: inspect the translated library reader transition and align the rendered heading or the test

## P1

### Large Reader Bundle
- Evidence: `ReaderView` is the largest frontend chunk at about 181.73 kB gzip-compressed 49.54 kB
- Impact: slower parse/execute on desktop and especially mobile
- Priority: high
- Proposed action: split reader shell from mode-specific subviews

### Large Global CSS File
- Evidence: `web/src/styles.css` is about 241 kB
- Impact: increases CSS parse and maintenance cost
- Priority: medium-high
- Proposed action: break CSS into feature-scoped files

### Monolithic Database Module
- Evidence: `app/database/db.py` is the largest backend file at about 237 kB
- Impact: harder to reason about queries, migrations, and data integrity
- Priority: medium-high
- Proposed action: split by domain

### Monolithic Pipeline Service
- Evidence: `app/mobile_api/services/pipeline_service.py` is about 220 kB
- Impact: service-layer coupling and poor change isolation
- Priority: medium-high
- Proposed action: split by domain service

## P2

### Import Wizard Client-Side Ceiling
- Evidence: 5 MB browser-side import cap is enforced
- Impact: acceptable today, but it is the point where future imports become more sensitive to browser memory and main-thread cost
- Priority: medium
- Proposed action: consider server-side preview/session handling for larger payloads

### Reader Complexity
- Evidence: reader state is already split, but `ReaderView.tsx` still carries too many responsibilities
- Impact: slows development and increases regression risk
- Priority: medium
- Proposed action: peel off subcomponents incrementally

### Router Size
- Evidence: `app/mobile_api/routers/import_routes.py`, `books.py`, and `jobs.py` are all large
- Impact: mixed responsibilities and harder endpoint discovery
- Priority: medium
- Proposed action: split routers after services are separated

## P3

### Dependency Hygiene
- Evidence: deprecation warnings were noted previously for `vinorm`, `passlib/bcrypt`, and `jieba/pkg_resources`
- Impact: not immediately breaking, but worth planned upgrades
- Priority: low-medium
- Proposed action: create a dependency migration plan with test coverage

### Observability Gaps
- Evidence: many workflows have logs and status endpoints, but live browser smoke could not complete in the current environment
- Impact: the operator may struggle to distinguish environment drift from product regressions
- Priority: medium
- Proposed action: add a small startup/self-check script that validates the exact runtime dependencies
