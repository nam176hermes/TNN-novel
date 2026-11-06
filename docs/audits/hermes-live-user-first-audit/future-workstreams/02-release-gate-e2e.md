# Workstream 2: Mandatory Browser E2E Gate

Goal: Prevent releases from passing full verification while critical browser workflows are unexecuted.

Scope:
- Add Playwright browser installation and `npm --prefix web run test:e2e` to CI.
- Add an explicit opt-in full local gate or include E2E in `scripts/verify.sh` where environment support is guaranteed.
- Fail closed on missing browser binaries.
- Cache Playwright binaries safely.
- Keep unit, typecheck, and build gates unchanged.

Required verification: clean CI-equivalent run, fail-closed missing-browser simulation, 11 existing tests plus new first-session PWA case.

Protected CI and package configuration requires operator greenlight before editing.
