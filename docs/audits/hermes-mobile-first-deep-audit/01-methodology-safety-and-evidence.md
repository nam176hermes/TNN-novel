# Methodology, Safety, and Evidence

## Mission boundary

This was an audit and repair-planning mission. Product repairs, refactors, migrations, deployments, production restarts, ingress changes, paid-provider calls, and CPU F5/ViVoice synthesis were forbidden. [Source: operator mission statement]

## Safety controls

- Production database and artifacts were inspected read-only.
- `production.env` was not modified and secret values were not recorded.
- Browser challenge integration was inspected only through source and isolated tests.
- Mutable browser tests used `/tmp/novel-tnn-audit-staging-data-v4/pipeline.db` and port 7861.
- Production artifacts were mounted read-only in staging.
- Restore validation created a separate drill directory and temporary container.
- Chapter text, cookies, passwords, tokens, and private payloads are absent from reports.

[Source: `15-hermes-running-log.md`; staging Docker inspect and restore service output]

## Evidence classes

| Class | Meaning |
|---|---|
| REPRODUCED | Observed in a fresh test, browser run, or live read-only probe |
| CODE_EVIDENCE | Direct static path proves the condition, but impact was not executed live |
| SUSPECTED | Evidence indicates risk but another explanation remains |
| NOT_TESTED | Intentionally excluded or not safely reachable |

## Main evidence

- Baseline log: `/tmp/novel-tnn-audit-baseline.log`
- Browser JSON: `/home/thenam176/.local/share/novel-tnn-audits/hermes-mobile-first-deep-audit-20260722/browser-audit-results.json`
- Browser screenshots: same external evidence directory
- Restore validation: latest JSON under `/home/thenam176/Novel-TNN-restore-drills/`
- Python dependency JSON: `/tmp/novel-tnn-pip-audit.json`
- Repository baseline: branch `upgrade-b/00-baseline-and-agent-guidance`, commit `286cd49129494604eb1fe6413307375a15bc4a0b`

## Verification commands used

```text
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_mobile_api_security.py ...
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_*import*.py tests/test_*backup*.py ...
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_tts_availability.py tests/test_mobile_api_tts.py tests/test_job_service_logic.py
systemctl --user start novel-tnn-restore-drill.service
uvx pip-audit --path .venv/lib/python3.11/site-packages
npm audit --omit=dev --audit-level=high
```

## Coverage limits

- No live CAPTCHA or third-party challenge test.
- No paid translation request.
- No F5/ViVoice synthesis.
- No production mutation or destructive restore.
- No full screen-reader session or measured color-contrast audit.
- No claim of WCAG conformance.
- Browser evidence used copied operator data without reporting private content.
- Independent Claude and Codex CLI report reviewers were attempted but unavailable because their CLI sessions were not authenticated. Final package review therefore used deterministic consistency, citation, secret-pattern, wording, issue-ID, section-count, and diff checks rather than a cross-family verdict.
