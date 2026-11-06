# Feature Matrix

Evidence references point to the numbered audit documents, the preserved browser JSON, focused test output, and read-only production probes. [Source: `01-methodology-safety-and-evidence.md`]

| Area | Status | Confidence | Evidence | Blocking gap |
|---|---|---|---|---|
| Login | PASS_WITH_LIMITATIONS | REPRODUCED | Focused security tests and isolated login | localStorage refresh token |
| Mobile navigation | PASS_WITH_LIMITATIONS | REPRODUCED | Three required mobile viewports | touch targets and dialog behavior |
| Library | PASS_WITH_LIMITATIONS | REPRODUCED | Browser open and Reader launch | mutation coverage limited |
| Reader translation | PASS_WITH_LIMITATIONS | REPRODUCED | Long translated article rendered | duplicate requests |
| Reader raw/split | FAIL | REPRODUCED | Source response exists, modes disabled | READ-001 |
| Reader QA | PASS_WITH_LIMITATIONS | REPRODUCED | QA mode selectable | full overlay state matrix limited |
| Reader audio | NOT_TESTED | NOT_TESTED | Sample had no usable audio | GPU synthesis forbidden |
| Reader offline | FAIL | REPRODUCED | No article after offline reload | READ-002 |
| Import | PASS_WITH_LIMITATIONS | REPRODUCED | 271 focused workflow tests | live source/challenge excluded |
| Durable jobs | PASS_WITH_LIMITATIONS | REPRODUCED | Worker and job tests | readiness does not aggregate heartbeat |
| Translation | PASS_WITH_LIMITATIONS | REPRODUCED | Mocked provider tests | paid live calls excluded |
| QA | PASS_WITH_LIMITATIONS | REPRODUCED | Deterministic QA tests | live operator approval flow limited |
| TTS policy | PASS_WITH_LIMITATIONS | REPRODUCED | 42 tests and production unavailable probe | low-level CPU fallback remains |
| Export | PASS_WITH_LIMITATIONS | REPRODUCED | Focused export tests | live private download not repeated |
| Backup | PASS | REPRODUCED | timer, encrypted artifacts, checksums | alerting weak |
| Restore | PASS_WITH_LIMITATIONS | REPRODUCED | fresh isolated restore and Reader smoke | no production restore by design |
| SQLite integrity | PASS | REPRODUCED | integrity and FK checks | direct connection pragma nuance |
| Artifact availability | PASS_WITH_LIMITATIONS | REPRODUCED | active path scan and restore scan | no continuous monitor |
| Public ingress | PASS_WITH_LIMITATIONS | REPRODUCED | HTTP 200 local/public | missing security headers |
| API runtime hardening | FAIL | REPRODUCED | Docker inspect | OPS-002 |
| Worker health | PASS_WITH_LIMITATIONS | REPRODUCED | Docker health check | absent from public readiness |
| Observability | FAIL | CODE_EVIDENCE | in-memory only metrics | no exporter or alerts |
| Desktop parity | PASS_WITH_LIMITATIONS | REPRODUCED | two desktop viewports | full mutation and AT review limited |
| Accessibility | FAIL | REPRODUCED | keyboard and target probes | A11Y-001 and A11Y-002 |
| Release verification | FAIL | REPRODUCED | masked backend failures | OPS-001 |
| Release provenance | FAIL | REPRODUCED | version endpoint and image drift | OPS-003 |
