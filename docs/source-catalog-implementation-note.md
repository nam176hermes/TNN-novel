# Source Catalog Phase 8 Implementation Note

## Current Source Management Found

- `source_catalog_entries` stores read-only metadata imported from local `yckceo_sources.json` / Novela-style catalog files.
- `source_catalog_health_checks` stores one-off guarded source checks for catalog rows.
- `source_adapter_candidates` stores parser-review candidates created from catalog rows.
- `POST /api/import/url/preview` and `POST /api/import/url` rely on built-in `SOURCE_POLICIES` plus hardcoded adapters in `app/ingestion/source_adapters.py`.
- `validate_public_http_url()` already blocks unsupported schemes, localhost, credentials, and private literal IPs before URL import.
- `check_source_health()` already performs a guarded single-page fetch with DNS/private-network checks, no cookies, no auth headers, no redirect following, and a small read limit.
- `SourcesView.tsx` exposes supported backend policies, a read-only source catalog, and parser candidates.
- `ImportPanel.tsx` can search the catalog, but a catalog row that is merely `supported` by domain policy can currently jump straight into URL preview.

## What Is Safe Today

- Catalog metadata does not automatically become a trusted source.
- Source health checks use a guarded SSRF-aware fetch path.
- URL import uses existing supported-source policies and built-in parsers only.
- Parser-candidate creation does not auto-promote a source into supported automation.

## What Is Risky Today

- Catalog rows do not have an operator-managed lifecycle such as `NEEDS_REVIEW`, `VERIFIED`, `BROKEN`, or `BLOCKED`.
- There is no durable distinction between read-only catalog metadata and operator-approved sources.
- Catalog-supported domains can still be turned into URL previews from the import wizard without an explicit verify/review step.
- There is no per-source managed status, trust level, notes, or overrideable conservative rate-limit metadata for operator-selected sources.

## Phase 8 Changes

- Keep `source_catalog_entries` as metadata only.
- Add a separate managed-source layer for operator-selected sources.
- Import from catalog into managed sources only by explicit operator selection.
- Default imported managed sources to `NEEDS_REVIEW` or `IMPORTED`, never `VERIFIED`.
- Reuse existing SSRF-safe URL validation and guarded fetch testing for managed sources.
- Gate automation so only `VERIFIED` managed sources can be used for source-based automated import jobs.
- Keep direct non-source imports unchanged: paste, TXT, ebook, translated ebook.
- Keep parser execution restricted to built-in parser types only; imported parser configs stay data-only and schema-validated.

## Intentionally Left Unchanged

- No captcha bypass.
- No paywall bypass.
- No rate-limit evasion.
- No proxy rotation or stealth automation expansion.
- No arbitrary crawler behavior.
- No multi-user or SaaS source ownership model.
- No distributed queue changes.
