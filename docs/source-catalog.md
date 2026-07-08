# Source Catalog

Novel-TNN can import a local Novela/yckceo-style source catalog JSON as read-only metadata.

This is not a scraper and does not make every catalog entry importable. Existing URL import behavior still depends on the supported source policies in `app/ingestion/source_policies.py`.

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

The response includes both `entries` and `items` arrays. They contain the same catalog rows; `items` is kept for backward compatibility with earlier internal callers.

## Safety Boundary

The source catalog is not trusted input for scraping. Do not expose `data/` directly, do not import catalog domains automatically, and do not run large source checks without explicit rate limits and SSRF protection.

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
