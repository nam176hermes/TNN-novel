# Workstream 1: Release Trust and Browser Network Isolation

Date: 2026-07-22

Branch: `repair/ws1-release-trust-browser-security-actual`

Baseline snapshot: `bf1442d5584cec728c9162a445f320655038fa01`

## Decision

**GO recommendation for Workstream 2 after operator review.**

All three WS1 issues have separate commits and the complete mandatory verification exits successfully. This workstream does not deploy, restart production, modify production configuration, or mutate production data. Workstream 2 must not start until the operator accepts this report.

## Scope

WS1 addressed only:

- `OPS-001`: mandatory verification failures could be hidden by a later successful command.
- `TEST-001`: the adapter registry contract duplicated a stale domain list.
- `SEC-001`: a second Playwright route handler replaced the private-network guard.

Protected challenge behavior, proxy behavior, fingerprints, CAPTCHA handling, production containers, ingress, and runtime data were left unchanged.

## Baseline and reproduction evidence

The implementation worktree was created from an immutable snapshot of the operator's tracked working state. This was necessary because the clean repository HEAD did not reproduce the three audit failures, while the operator baseline did. The deployed checkout was not reset, stashed away, or edited for WS1.

Before fixes, the three original regression tests failed together:

- `test_browser_session_navigation_guard_blocks_private_top_level_target`
- `test_browser_session_blocks_private_subresource_at_network_layer`
- `test_every_dedicated_registry_adapter_uses_the_dom_contract`

The browser failure was reproduced more broadly with eight failing network-policy cases. Private top-level requests, private subresources, IPv4 private/link-local targets, IPv6 loopback, private DNS resolution, and private iframe navigation were continued rather than aborted. The test fake also recorded two handlers for the same `**/*` route.

The original verification wrapper had sequential mandatory commands without an explicit gate abstraction. A later successful command determined the script's final status when shell failure handling was bypassed or altered. The isolated self-test now injects exit `97` and confirms the wrapper returns `97` while naming the failed gate.

## OPS-001

### Root cause

`scripts/verify.sh` relied on implicit shell sequencing instead of recording each mandatory gate as a named operation with explicit failure propagation. This made the aggregate result fragile and allowed a later success to hide an earlier failure in affected execution paths.

### Changes

- Added `run_mandatory_gate` with readable start, pass, and fail output.
- Preserved the exact failing command status.
- Added `--self-test-failure` for isolated regression testing without breaking product tests.
- Wrapped compile, shell syntax, environment, lint/typecheck, backend tests, dependency consistency, frontend tests, and frontend build as mandatory gates.

### Verification

- `tests/test_environment_scripts.py`: 9 passed.
- `scripts/verify.sh --self-test-failure`: printed `FAIL: injected mandatory gate (exit 97)` and returned `97`.
- Normal complete verification returned `0` only after every mandatory gate passed.

Commit: `5621f7a fix(verification): propagate failed gate exit status`

## TEST-001

### Root cause

The registry contract test maintained a separate hard-coded list of adapter domains. Production registration and test expectations could drift independently, which caused active dedicated adapters to be treated as missing from the contract.

### Changes

- Added immutable `SourceAdapterRegistration` metadata derived from the active registry.
- Added validation for missing adapter metadata, duplicate adapter IDs, and duplicate domains.
- Made source capability reporting use the active default registry instead of rebuilding a separate list.
- Made tests derive the full dedicated-adapter contract from the canonical registry.
- Kept a small required-active-domain assertion for the five audited domains without duplicating the complete registry.

Verified audited domains:

- `xbiquge.info`
- `xbiquge.so`
- `meionovels.com`
- `scribblehub.com`
- `lnmtl.com`

The canonical registry contains 43 adapters and 57 unique domains.

### Verification

- Adapter registry, source adapter, and observability suites: 108 passed.
- Original adapter regression included in the three-test check: passed.
- Missing metadata, duplicate ID, duplicate domain, and factory-to-registry parity contracts: passed.

Commit: `f4b2827 fix(adapters): derive registry contract from canonical source`

## SEC-001

### Root cause

`BrowserSessionManager` installed two Playwright handlers for the same `**/*` route. The later resource-blocking handler could replace the navigation/network policy handler. It continued requests that were not optional blocked resource types, including private top-level and subresource targets.

### Changes

- Consolidated private-network validation and optional resource blocking into one canonical route handler.
- Validate every intercepted request before deciding whether to block fonts, media, WebSockets, beacons, text tracks, or CSP reports.
- Abort policy violations with `blockedbyclient`.
- Preserve typed `UrlPolicyViolation` for blocked top-level navigation.
- Do not store a top-level navigation failure for blocked child-frame requests.
- Preserve image loading and approved browser/challenge behavior.

### Security coverage

Controlled tests cover:

- private top-level navigation;
- private subresources;
- child-frame navigation;
- public-to-private redirect destination behavior at the intercepted request boundary;
- IPv4 private, loopback, and link-local targets;
- IPv6 loopback targets;
- a hostname resolving to a private address;
- resource blocking through the same canonical handler;
- session close and browser lifecycle tests;
- existing CAPTCHA/challenge upgrade contracts;
- import worker processing and failure behavior.

Blocked requests are aborted and no URL, cookie, page content, credential, or private payload is logged by the new path.

### Verification

- Original three regressions: 3 passed.
- Browser, URL policy, fetch-security, and challenge suites: 74 passed, 1 existing deprecation warning.
- Focused mobile/API/browser security suites: 105 passed, 1 existing deprecation warning.
- Import worker suites: 14 passed.

Commit: `6332f05 fix(browser): abort private network requests`

## Complete mandatory verification

Command:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 \
PYTHONDONTWRITEBYTECODE=1 \
PYTHON_BIN=/home/thenam176/Novel-TNN/.venv/bin/python \
mise x node@22 -- scripts/verify.sh
```

Result: exit `0`.

Mandatory gate results:

- Python compile: PASS
- Shell syntax: PASS
- Isolated worktree environment: PASS
- Backend lint and frontend typecheck: PASS
- Backend tests: 1,161 passed, 2 existing deprecation warnings
- Python dependency consistency: PASS
- Frontend tests: 82 files and 740 tests passed
- Frontend production build: PASS
- `git diff --check`: PASS

Evidence log: `/tmp/ws1-final-verify.log`

The first full backend attempt had one environment-only failure because a backup fixture invoked the repository-relative `.venv/bin/python`, while the worktree initially used only an external `PYTHON_BIN`. Adding a local symlink to the existing Python 3.11 environment made that test pass. The final mandatory run then passed all 1,161 backend tests.

## Files changed

OPS-001:

- `scripts/verify.sh`
- `tests/test_environment_scripts.py`

TEST-001:

- `app/ingestion/source_adapters.py`
- `tests/test_dom_parser_registry_contract.py`

SEC-001:

- `app/utils/stealth_browser.py`
- `tests/test_browser_session_manager.py`

This report:

- `docs/repairs/ws1-release-trust-browser-security.md`

## Limitations and remaining risk

- No live third-party CAPTCHA, challenge, or bot-wall bypass was tested. This is an intentional safety boundary.
- No production deployment, restart, database mutation, Cloudflare change, DNS change, or ingress change was performed.
- Production runtime behavior still requires the normal deployment approval and post-deployment smoke process.
- External Codex or Claude review was unavailable because the local clients did not have usable review credentials. Final evidence therefore consists of source review, focused regressions, full automated verification, and commit-scope inspection.
- The branch starts from the tracked operator-state snapshot rather than the clean historical HEAD. Integration must preserve the operator's uncommitted baseline and should use the three issue commits in order.

## Commit order

1. `5621f7a fix(verification): propagate failed gate exit status`
2. `f4b2827 fix(adapters): derive registry contract from canonical source`
3. `6332f05 fix(browser): abort private network requests`

## Operator checkpoint

WS1 meets its automated acceptance criteria. Stop here. Do not start Workstream 2 or deploy these changes until operator approval.
