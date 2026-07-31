# Source Catalog

Novel-TNN now has two separate source layers:

1. `source_catalog_entries`: imported read-only metadata from local Novela/yckceo-style JSON.
2. `managed_sources`: operator-selected sources inside Source Hub with explicit review state.

This separation is intentional. Catalog rows are not trusted import sources by themselves, and the app does not mass-import them into active automation.

## Import a Catalog

Download or provide a local `yckceo_sources.json` file, then run:

```bash
python -m app.ingestion.source_catalog_cli /path/to/yckceo_sources.json
```

Use a custom database path for tests or maintenance:

```bash
python -m app.ingestion.source_catalog_cli /path/to/yckceo_sources.json --db-path data/pipeline.db
```

The importer is idempotent. Running it again updates matching entries by stable catalog id and does not create duplicates.

## Managed Sources

Use Source Hub to import selected catalog rows into `managed_sources` for review. This is manual and explicit:

- no mass auto-import
- duplicate rows skipped safely
- malformed or unsafe rows rejected
- imported rows default to `NEEDS_REVIEW` for supported-policy domains, or `IMPORTED` otherwise
- imported rows never become `VERIFIED` automatically

Managed sources carry the operator review lifecycle, rate-limit settings, last fetch-test result, notes, and automation eligibility.

## Normalized Tags

The yckceo/Novela tags are normalized as:

- `搜` -> `search`
- `发` -> `explore`
- `图` -> `manga`
- `声` -> `audio`

Unknown tags are kept separately as `unknown_tags` so bad source metadata does not pollute the normalized filters.

## Supported Status

Each catalog entry gets a `supported_status`:

- `supported`: the entry URL domain matches an existing `SOURCE_POLICIES` domain.
- `unsupported`: the URL is public HTTP/HTTPS but no backend source policy supports it yet.
- `invalid_url`: the URL is missing, uses an unsupported scheme, contains credentials, or points at localhost/private network literal IPs.

Supported status is metadata only. It does not auto-promote a source, modify source policies, or bypass the existing import validation.

## Source Status Lifecycle

Managed source statuses:

- `IMPORTED`: metadata imported, not reviewed yet
- `NEEDS_REVIEW`: operator should test/review before automation
- `VERIFIED`: safe enough for automated source-based jobs
- `BROKEN`: source/parser currently failing, excluded from automation
- `BLOCKED`: source explicitly blocked, cannot be tested or used

Rules:

- newly imported rows are never `VERIFIED`
- `BLOCKED` rows cannot be fetch-tested or used in jobs
- `BROKEN` rows cannot be used in automation
- `NEEDS_REVIEW` rows may be tested manually only
- only `VERIFIED` rows can start automated URL/source jobs

Trust levels:

- `UNKNOWN`
- `LOW`
- `MEDIUM`
- `HIGH`
- `MANUAL_ONLY`

Today trust level is operator metadata plus UI filtering. The hard gate for automation is status `VERIFIED`.

## Read API

Authenticated operators can query the catalog:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/source-catalog?query=69shuba&tag=search&supported=true&page=1&page_size=50"
```

Supported filters:

- `query`: searches name, URL, domain, author, external id, and raw tags.
- `tag`: normalized tag such as `search`, `explore`, `manga`, or `audio`.
- `domain`: exact normalized hostname.
- `supported`: `true` for supported entries, `false` for unsupported/invalid entries.
- `page` and `page_size`: pagination, capped at 200 per page.
- `per_page`: backward-compatible alias for `page_size`.
- `status`: managed-source review status such as `VERIFIED`, `NEEDS_REVIEW`, or `UNMANAGED`
- `trust_level`: managed-source trust filter such as `MANUAL_ONLY` or `HIGH`

The response includes both `entries` and `items` arrays. They contain the same catalog rows; `items` is kept for backward compatibility with earlier internal callers.

## Managed Source API

All managed-source APIs require authentication.

List and review sources:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/sources?status=NEEDS_REVIEW&page=1&page_size=50"
```

Import selected catalog rows into Source Hub:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"entry_ids":["yckceo:1","yckceo:2"]}' \
  "http://127.0.0.1:8000/api/sources/import-catalog"
```

Safe fetch-test one managed source:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/sources/src_xxx/test"
```

Verify a previously tested source:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/sources/src_xxx/verify"
```

Mark a source `BROKEN`, `BLOCKED`, or back to `NEEDS_REVIEW`:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"status":"BLOCKED"}' \
  "http://127.0.0.1:8000/api/sources/src_xxx/status"
```

## Validation Rules

Before a managed source is stored or updated:

- base URL must pass the existing SSRF-safe public HTTP/HTTPS validator
- localhost, private IPs, link-local, metadata IPs, and unsupported schemes are rejected
- duplicate catalog/base URLs are skipped safely
- parser type must be one of the explicitly supported parser types
- parser config must match the allowed schema for that parser type
- unsafe config fields are rejected

The app does not create a second weaker URL validation path.

## Safe Fetch Test

Managed source fetch tests:

- use the SSRF-safe validation path
- fetch only the base/sample URL
- apply short timeouts
- do not follow redirects blindly
- do not crawl linked pages
- do not send cookies, auth headers, or provider keys
- store only sanitized result text

Test statuses include:

- `success`
- `blocked_by_policy`
- `timeout`
- `invalid_url`
- `fetch_failed`
- `parse_failed`
- `parser_config_missing`

These results update `last_tested_at`, `last_successful_fetch_at`, and `last_error` on the managed source. A successful test does not auto-verify the source; verification remains an explicit operator action.

## Parser Safety

Managed-source parser handling is intentionally narrow:

- no arbitrary code execution from imported configs
- no shell commands
- no filesystem access from parser config
- no dynamic eval
- no new network path outside the guarded fetch utility
- parser errors are contained and surfaced as sanitized results

If a source needs richer parser behavior than the supported safe config allows, keep it in `NEEDS_REVIEW` until a real server-side adapter/policy is added deliberately.

## Rate Limiting

Managed sources store conservative per-source settings:

- requests per minute
- delay between requests
- max concurrent requests
- cooldown after error

These values are operator-visible metadata and are used for safe review/management. They do not add any stealth, proxy rotation, or bypass behavior.

## Import Wizard Integration

Phase 8 changes the Source Catalog step in the import wizard:

- catalog rows remain metadata only
- the wizard now shows managed source status when available
- only `VERIFIED` managed sources can start automated URL import jobs
- `NEEDS_REVIEW`, `IMPORTED`, `BROKEN`, and `BLOCKED` sources stay disabled for automation
- unverified rows show a review/test reason instead of silently failing

## Job Integration

When a verified source starts a URL/source import job:

- the existing Phase 2 job lifecycle is reused
- long fetch/import work still runs in the background job system
- the job payload stores `managed_source_id`
- failures are logged with sanitized messages only
- raw HTML and secrets are not stored in job logs

## Safety Boundary

The app will not do the following:

- no captcha bypass
- no paywall bypass
- no rate-limit evasion
- no stealth proxy rotation
- no blind mass import of thousands of sources
- no arbitrary crawler behavior from imported metadata
- no weakening of SSRF protections

Also do not expose `data/` directly.

## Parser Candidates

Operators can create a parser candidate from a catalog entry:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/source-catalog/<catalog-entry-id>/parser-candidate"
```

This fetches one guarded preview page only, using the same private-network/SSRF protection as source health checks. The server stores review metadata in `source_adapter_candidates`, including detected title, possible chapter links, content-container signals, confidence, status, and sanitized failure reason.

Parser candidates are review aids only:

- They do not add domains to `SOURCE_POLICIES`.
- They do not become supported sources automatically.
- They do not make unsupported catalog entries importable.
- Import remains blocked until a developer/operator adds a real source policy and parser.

Read candidates through:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/source-adapter-candidates?page=1&page_size=50"
```
