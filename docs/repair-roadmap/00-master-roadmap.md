# Novel-TNN — Hermes Repair and Upgrade Master Roadmap

## Purpose

This package converts the Hermes mobile-first audit into a controlled implementation program.

The current audit baseline identified:

- no reproduced P0;
- eight open P1 findings;
- several P2 security, performance, accessibility, observability, release, and maintainability gaps;
- strong data integrity, backup/restore, and core workflow foundations;
- mobile Reader correctness and production release trust as the highest-priority weaknesses.

This roadmap is for a private, single-operator Novel-TNN deployment. Do not convert the application into SaaS, replace SQLite without evidence, or perform a broad rewrite.

## Current production environment

Repository: `/home/thenam176/Novel-TNN`

Runtime data: `/home/thenam176/Novel-TNN/data`

Production environment file: `/home/thenam176/.config/novel-tnn/production.env`

Production containers:

- `novel-tnn-wsl-api-1`
- `novel-tnn-wsl-import-worker-1`

## Protected behavior

### Browser challenge integration

The existing browser/session/challenge integration is protected.

Do not:

- remove, disable, expand, rewrite, rename, or relocate it;
- change proxy, fingerprint, solver, or challenge behavior;
- run live bypass tests against third-party systems;
- expose sensitive implementation details.

Only repair its network-isolation boundary using local fixtures, mocks, contract tests, and explicitly authorized environments.

### TTS

F5/ViVoice is GPU-only.

Without a supported GPU:

- TTS must report unavailable;
- invalid TTS jobs must be rejected safely;
- the engine must never fall back to CPU;
- the rest of Novel-TNN must remain ready.

## Global implementation rules

1. Read `AGENTS.md` and the relevant audit documents before changing code.
2. Record branch, HEAD, worktree status, running containers, and baseline tests.
3. Work in a dedicated branch or worktree. Do not edit the deployed checkout directly unless that is already the approved repository workflow.
4. Reproduce every issue before fixing it.
5. Add a failing regression test where practical.
6. Apply the smallest responsible fix.
7. Run targeted tests before broader verification.
8. One logically complete issue per commit.
9. Do not use `git add .`.
10. Never stage `.env`, private data, databases, backups, audio, exports, logs, model files, `.venv`, or `node_modules`.
11. Do not restart or deploy production without an explicit approval gate.
12. If verification fails, stop new work and repair the regression first.
13. Update the issue register and running log after every verified commit.
14. Stop after each workstream and wait for operator review.

## Required commit format

```text
fix(verification): propagate failed gate exit status
fix(browser): abort private network requests
fix(reader): centralize chapter data ownership
fix(pwa): restore cached reader content offline
fix(auth): move refresh token to httponly cookie
fix(runtime): align api container hardening
fix(readiness): include worker and capability status
fix(a11y): implement reader dialog focus lifecycle
perf(glossary): virtualize large term lists
refactor(reader): extract stable data controller boundary
```

## Workstream order

### Workstream 1 — Release trust and browser network isolation

File: `01-release-trust-and-browser-security.md`

Issues:

- `OPS-001`
- `SEC-001`
- `TEST-001`

Why first: no later work can be trusted while the verification wrapper can return success after failed tests.

### Workstream 2 — Mobile Reader correctness and offline behavior

File: `02-mobile-reader-correctness-and-offline.md`

Issues:

- `READ-001`
- `READ-002`
- `PERF-002`

Why second: these are the highest-priority product correctness problems and directly affect the mobile-first goal.

### Workstream 3 — Session security, headers, and retention

File: `03-session-security-headers-and-retention.md`

Issues:

- `SEC-002`
- `SEC-003`
- `SEC-004`

Why grouped: refresh-token architecture, browser security headers, CSRF contract, logout behavior, and session lifecycle must be designed and tested together.

### Workstream 4 — Production runtime, readiness, provenance, observability, and TTS invariant

File: `04-production-runtime-readiness-and-observability.md`

Issues:

- `OPS-002`
- `OPS-003`
- `OPS-004`
- `OBS-001`
- `TTS-001`

Why grouped: these changes share Docker, release, health/readiness, deployment, and operational verification boundaries.

### Workstream 5 — Mobile accessibility and large-list performance

File: `05-mobile-accessibility-and-list-performance.md`

Issues:

- `A11Y-001`
- `A11Y-002`
- `PERF-001`

Why after Reader correctness: avoid building accessibility and virtualization behavior on top of unstable Reader state ownership.

### Workstream 6 — Controlled maintainability extraction

File: `06-controlled-maintainability-extraction.md`

Issues:

- `MAINT-001`
- follow-up ownership debt discovered while fixing earlier workstreams

Why last among implementation workstreams: large modules should be split only after behavior is protected by passing contract tests.

### Workstream 7 — Final regression and release certification

File: `07-final-regression-and-release-certification.md`

Purpose: re-run the full feature, security, mobile, operations, recovery, and provenance matrix. This workstream does not add features.

## Release gates after every workstream

At minimum:

```text
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
scripts/verify.sh
git diff --check
git status --short
```

Also run:

- affected Playwright mobile tests;
- local health and readiness;
- Docker build/smoke when runtime files change;
- public probes only after approved deployment;
- restore drill when backup or data behavior changes.

## Stop conditions

Hermes must stop and request operator approval before:

- production restart;
- production deployment;
- modifying `production.env`;
- changing Cloudflare, DNS, tunnel, or reverse proxy;
- migrating session/token behavior in production;
- destructive cleanup;
- active database migration;
- paid provider calls;
- GPU synthesis;
- changes to protected challenge behavior.

## Program Definition of Done

The upgrade program is complete when:

- all reproduced P1 issues are fixed and verified;
- all baseline tests are green;
- `scripts/verify.sh` returns non-zero for any failed gate;
- mobile raw/split and offline Reader contracts pass;
- refresh-token handling no longer depends on browser-readable persistent storage;
- API and worker runtime controls are aligned;
- readiness reports worker and optional capability state honestly;
- F5/ViVoice cannot fall back to CPU;
- release identity maps production images to a Git commit;
- key operational metrics and alerts are available;
- mobile dialog and touch-target regressions are fixed;
- Glossary and TOC no longer materialize excessive DOM trees;
- final local and public probes pass;
- the final worktree is clean;
- remaining P2/P3 items are documented honestly.
