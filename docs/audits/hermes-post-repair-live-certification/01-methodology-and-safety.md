# Methodology and safety


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Evidence order

The audit used this order: live public black-box observation, isolated black-box staging from the production image, fresh runtime probes, deterministic tests, source inspection, then historical comparison. Historical reports were used only to define regression targets. [Source: evidence/browser-summary.json] [Source: evidence/live-runtime-second-snapshot.json]

## Production boundaries

Production was read-only. No production import, job creation, retry, cancellation, translation, TTS synthesis, backup creation, restore, deployment, container restart, DNS change, Cloudflare change, or secret edit was performed. The production database, WAL, and SHM hashes and row counts were identical before and after the audit. [Source: evidence/production-data-integrity.json] [Source: evidence/production-data-final-fingerprint.json]

All mutation-capable checks used an isolated SQLite copy and shadow API on port 17861. The restore drill used a new temporary root and the digest-addressed production API image. No paid provider was called. No GPU synthesis or CPU TTS attempt occurred. [Source: evidence/tts-gpu-only.json] [Source: evidence/restore-validation.json]

## Protected browser challenge behavior

Status: **preserved and regression-tested locally; not live-tested**.

The audit checked URL policy, private-network isolation, redirects, iframe and subresource behavior, failure typing, cookie-file privacy, retry, crash recovery, and teardown. It did not probe challenge bypass against a third-party site or expose solver details. [Source: evidence/test-summary.json]

## Redaction policy

Evidence excludes credentials, tokens, cookies values, chapter text, prompts, provider payloads, secret environment values, unrestricted container logs, and backup object names. Screenshots were masked before preservation. Identifiers are retained only when needed for release and image provenance.

## Confidence vocabulary

- `REPRODUCED`: directly observed in a fresh command, browser run, or runtime probe.
- `CODE_EVIDENCE`: current source establishes the behavior but no equivalent live mutation was run.
- `SUSPECTED`: evidence indicates a risk but counterevidence remains.
- `NOT_TESTED`: intentionally excluded or not completed.
- `BLOCKED`: authorization or safe-environment requirements prevented the test.
- `RECOMMENDATION_ONLY`: no defect was established.

## Limits

The custom browser script failed to locate the Reader mode buttons and TOC by its exact accessible-name selectors. Mode correctness therefore relies on release E2E and source contracts, not a complete custom black-box mode matrix. The settings and More dialog probes did execute and recorded their focus states. [Source: evidence/browser-summary.json]
