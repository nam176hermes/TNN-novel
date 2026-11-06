# Workstream 1: P1 First-Session Offline Readiness

Goal: Fix UX-PWA-001 without weakening protected API caching boundaries.

Scope:
- Reproduce in a fresh context with no preparatory online reload.
- Make newly installed app-shell assets available immediately to offline fetch handling.
- Report cache success only after chapter data and app shell are both verified.
- Add first-session and warmed-path E2E tests.
- Preserve authentication, service-worker scope, offline manifest versioning, and protected API non-caching.

Required verification:
- targeted service-worker tests;
- Playwright first-session and warmed offline cases;
- frontend unit, typecheck, build, and full E2E;
- full repository verification;
- live post-deploy two-path certification at `390x844`.

Stop before deployment or merge and return a HANDOFF with diff and test evidence.
