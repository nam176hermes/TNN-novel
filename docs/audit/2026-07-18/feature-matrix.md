# Novel-TNN quality audit — feature matrix

Status is evidence-based and updated as each workstream completes.

| Area | Current result | Evidence captured | Next audit gate |
|---|---|---|---|
| Repository and static checks | Passing | Python compile, shell syntax, lint, and typecheck pass. | Re-run combined verifier after any further work. |
| Production topology | Passing with provenance debt | API/worker healthy; loopback bind; hardened runtime mounts. | Canonical Compose-chain comparison. |
| Public ingress | Passing | Cloudflare Tunnel service is active; public health/ready pass; CORS and data-path probes pass. | Public authenticated/private-route probes. |
| SQLite and artifacts | Passing baseline | 42 tables; 1 book; 697 chapters; 329 mobile jobs; 695 QA reports; integrity and FK checks pass. | Full approved artifact-path scan and transactional workflow tests. |
| Authentication and authorization | P1 findings remediated; no P0 found | Seven-round deep-security discovery reached saturation. External default credentials, standalone dashboard exposure, and request-controlled translation egress were fixed with focused tests. | Release the verified commits only through an approved deployment window; retain P2 DNS-rebinding workstream. |
| Import and durable worker | Passing baseline | Worker healthcheck and container health pass; full backend suite covers jobs/recovery scenarios. | Live provider/source E2E remains intentionally out of scope. |
| Translation, QA, export | Passing test coverage | Backend suite passes; mocked-browser E2E exercises translation and TXT export. | Authenticated live workflow smoke only with explicit operator approval. |
| Reader and mobile UI | Passing test coverage and long-QA rendering contract | Vitest 82 files/732 tests and Playwright 8/8 cover desktop and 390/360px flows; AUD-008 adds a 180-paragraph QA-overlay regression. | Authenticated production Reader smoke only with explicit operator approval. |
| TTS | Passing non-GPU contract | 24 focused TTS tests pass; production F5/CUDA probe returns `tts_unavailable` before synthesis. | GPU-host quality/synthesis workstream remains deferred. |
| Backup and restore | Passing recovery drill, off-site verification, and retention contract | Two 5.64 GB encrypted R2 archive sets have matching local checksums and `READY` sidecars; isolated restore drill passed. AUD-001 and AUD-007 are closed. | Regular scheduled drill monitoring. |
| Full release gates | Passing for current checkout | Fresh production-mode `scripts/verify.sh` passed: backend 1,112; Vitest 82 files/733 tests; build and independent typecheck pass. Playwright 8/8 and local/public health/ready also pass. | Re-run after any future change or before an approved deployment. |
