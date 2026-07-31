# P12 — DOM parser framework and 69shuba migration

## Scope

P12 adds an offline, versioned DOM extraction framework and migrates the
69shuba family without changing routes, job scheduling, SSE, frontend behavior,
or browser lifecycle. Tests use sanitized local fixtures and never contact a
live source.

## Dependency decision

The project has no declared general-purpose HTML parser dependency. P12 uses
Python's standard-library `html.parser` and a deliberately small selector
subset. The transitively installed `lxml` package is not treated as an
application dependency, and no production package was added.

## Parser contract

A DOM adapter owns:

- allowed-domain policy;
- P02 URL canonicalization;
- `parse_preview`;
- `parse_chapter`;
- canonical normalization and cleanup;
- typed content validation;
- an explicit `adapter_version`.

Selector configuration provides ordered fallbacks for title, author,
description, cover, chapter links, chapter content, and removal targets. The
selector engine intentionally supports only the tag, id, class, attribute, and
descendant forms required by reviewed source configurations.

## Extraction pipeline

1. Detect challenge and not-found/error documents before extraction.
2. Parse the document tree.
3. Remove script, style, navigation, advertising, breadcrumb, popup, and
   source-specific boilerplate nodes.
4. Resolve the first matching metadata/content selectors.
5. Convert block elements and `<br>` boundaries into paragraphs.
6. Apply canonical Unicode and whitespace normalization.
7. Validate the extracted chapter.
8. Calculate SHA-256 from the same normalized text representation used by
   import persistence.

Canonical normalization and hashing now live in
`app/ingestion/text_normalization.py`. The existing
`app.mobile_api.services.import_metadata` import path re-exports those names so
P03 callers remain compatible.

## Validation and error mapping

Validation rejects:

- status-200 challenge/verification documents as
  `user_verification_required`;
- recognizable not-found documents as `content_not_found`;
- empty or short chapter text as `content_invalid`;
- chapter indexes misidentified as chapter content;
- content dominated by navigation boilerplate.

Selector mismatch is `parse_failed` and may use the compatibility parser.
Challenge, missing, and invalid content never fall through to regex parsing.

## 69shuba-family migration

The default registry keeps the existing identities and domain boundaries:

- `69shuba`: `69shuba.com`, `69shuba.cx`, `69shux.com`;
- `69shumi`: `69shumi.com`, `69shumi.net`.

Both entries now use versioned DOM selector configurations. Existing result
contracts remain compatible; parser-version, parser-method, and content-hash
metadata are additive and have defaults for older callers.

## Regex compatibility fallback

The existing regex adapter remains available only when DOM layout selectors do
not match or yield no semantically valid chapter links. Fallback output still
passes the new page-state and content validators. Telemetry records only
adapter id, adapter version, and the preview/chapter target. It never records a
URL, raw HTML, extracted chapter text, cookie, token, or credential.

## Fixtures and coverage

Sanitized local fixtures cover:

- normal preview and chapter pages;
- primary and secondary selector layouts;
- relative and absolute chapter links;
- Chinese text, HTML entities, and Unicode normalization;
- removal of navigation, ads, breadcrumb, popup, and script content;
- regex compatibility fallback;
- 403/404/500/502/522 and status-200 challenge pages;
- empty and short content;
- chapter-list and boilerplate misclassification;
- a valid chapter numbered 404, preventing false not-found classification.

The fixture suite performs no Internet or real-browser calls.

## Compatibility and boundaries

- Existing adapter ids and registry lookup behavior remain stable.
- P02 URL policy and typed source errors are reused rather than duplicated.
- P03 normalization/hash semantics remain authoritative.
- Existing generic and regex selector adapters remain available to other
  sources and direct callers.
- No router, API schema, worker, retry, scheduler, SSE, or frontend behavior
  changed.
- No live-provider validation is claimed by this milestone.

## Verification

- DOM fixtures plus source/import regressions: `56 passed in 12.68s`.
- Backend compile, lint wrapper, frontend typecheck, and `git diff --check`:
  passed.
- Full backend suite: `960 passed, 2 warnings in 1538.47s (0:25:38)`.
