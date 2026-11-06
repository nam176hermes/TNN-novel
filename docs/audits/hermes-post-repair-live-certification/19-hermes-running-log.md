# Hermes running log


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Timeline

1. Opened the public application before source inspection and captured login/PWA behavior.
2. Recorded repository, toolchain, container, image, release, health, and readiness baseline.
3. Created an isolated SQLite online backup and shadow API using the production image.
4. Ran authenticated browser checks at 360x740, 390x844, 412x915, 1366x768, and 1440x1000.
5. Preserved 20 redacted screenshots and normalized browser telemetry.
6. Ran verification failure-propagation self-tests.
7. Ran the production-aware complete gate: 1,247 backend, 778 frontend, build, and 12 Chromium E2E passed.
8. Ran a separate 382-test focused security and workflow suite.
9. Probed staging CSRF, refresh rotation, reuse detection, logout, and logout-all.
10. Audited production SQLite, artifacts, logs, sessions, runtime permissions, resources, and endpoint headers read-only.
11. Verified API and worker source files against release Git SHA with zero mismatches.
12. Verified GPU-unavailable behavior at API and low-level TTS entry points without creating a job.
13. Inventoried encrypted backups and verified the latest checksum and sidecar.
14. Ran an isolated encrypted restore. DB, artifacts, API, and Reader passed; receipt publication failed.
15. Proved receipt publication in an ephemeral UID 10001-owned directory.
16. Reconciled configured backup data root, live Docker mount, and operator runtime root as the same database.
17. Captured identical production database fingerprints before and after read-only validation.
18. Inspected the current release and rollback overlays and found the canonical runbook stale.
19. Generated this redacted certification package and future-workstream prompts.
20. A continuation inspection found that a later UID 1000 shadow relaunch remained healthy with auto-remove disabled. It did not mount or mutate production data.
21. Repaired the audit-only logout locator and reran the five-scenario PWA adversarial matrix. The process exited 0 with zero harness errors and all seven assertions true.
22. Stopped and removed the shadow container. Production API and worker remained healthy and were not restarted.
23. Refreshed local and public health, readiness, version, container state, SQLite integrity, foreign-key checks, and database fingerprints read-only.
24. Rebuilt the evidence manifest and checksums as revision 2.

## Safety record

- No product source repair.
- No production database or artifact mutation.
- No production job action.
- No provider payment or GPU synthesis.
- No production container restart or deployment.
- No Cloudflare, DNS, proxy, or challenge-behavior change.
- No secret value preserved in the package.

## Execution anomalies

- Initial full verification lacked the required production environment contract and stopped at environment validation. The corrected invocation passed.
- Browser log tee initially opened before its output directory existed; browser JSON and screenshots were still created.
- The custom Reader mode and TOC selectors did not match their controls, so those fields are not presented as custom-browser passes.
- A staging authenticated metrics probe later received HTTP 401 after repeated audit sessions and was not used as metrics evidence.
- The isolated restore process exited 1 only at receipt publication after authenticated Reader smoke passed.
- The first PWA continuation run used a hidden mobile-navigation locator and exited 1. After the harness navigated visibly back to Library before opening the mobile More sheet, the rerun exited 0.
- The chapter-only scenario deliberately removed both shell caches. Offline reload returned `net::ERR_FAILED`, which is expected because IndexedDB chapter data cannot bootstrap a missing application shell.
- Initial unauthenticated refresh probes returned HTTP 401 during fresh browser contexts. They were expected bootstrap denials and produced no page errors.
