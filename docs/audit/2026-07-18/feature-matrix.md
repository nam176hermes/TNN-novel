# Novel-TNN quality audit — feature matrix

Status is evidence-based and updated as each workstream completes.

| Area | Current result | Evidence captured | Next audit gate |
|---|---|---|---|
| Repository and static checks | Passing | Python compile, shell syntax, lint, and typecheck pass. | Re-run combined verifier after any further work. |
| Production topology | Passing with provenance debt | API/worker healthy; loopback bind; hardened runtime mounts. | Canonical Compose-chain comparison. |
| Public ingress | Passing | Cloudflare Tunnel service is active; public health/ready pass; CORS and data-path probes pass. | Public authenticated/private-route probes. |
| SQLite and artifacts | Passing baseline | 42 tables; 1 book; 697 chapters; 329 mobile jobs; 695 QA reports; integrity and FK checks pass. | Full approved artifact-path scan and transactional workflow tests. |
| Authentication and authorization | Passing baseline; exhaustive code scan blocked | Local/public protected routes return 401; docs schema routes are disabled; backend suite passes. | Approve and run deep-security discovery. |
| Import and durable worker | Passing baseline | Worker healthcheck and container health pass; full backend suite covers jobs/recovery scenarios. | Live provider/source E2E remains intentionally out of scope. |
| Translation, QA, export | Passing test coverage | Backend suite passes; mocked-browser E2E exercises translation and TXT export. | Authenticated live workflow smoke only with explicit operator approval. |
| Reader and mobile UI | Passing test coverage | Vitest 82 files/731 tests and Playwright 8/8 cover desktop and 390/360px flows. | Authenticated production Reader smoke only with explicit operator approval. |
| TTS | Passing non-GPU contract | 24 focused TTS tests pass; production F5/CUDA probe returns `tts_unavailable` before synthesis. | GPU-host quality/synthesis workstream remains deferred. |
| Backup and restore | Passing recovery drill and documentation contract | 5.64 GB encrypted R2 archive and isolated restore drill passed; AUD-001 closed. | Regular scheduled drill monitoring. |
| Full release gates | Passing component gates | Backend 1,103 passed; Vitest 82 files/731 tests; Playwright 8/8; production build, local/public health/ready all pass. | Run combined `scripts/verify.sh` after any new work. |
