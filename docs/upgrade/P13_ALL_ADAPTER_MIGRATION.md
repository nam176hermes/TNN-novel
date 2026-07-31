# P13 — All dedicated source adapters on the DOM contract

## Scope

P13 moves every remaining dedicated source adapter in the runtime registry to
the P12 `DomSourceAdapter` contract. It adds synthetic, local fixtures and
parameterized contract coverage; no test contacts a live website or launches a
browser.

The registry's `generic_html` entry remains an intentional catch-all for
policy-approved sources without a reviewed, source-specific layout. It is not
counted as a dedicated DOM adapter and does not claim a source-specific parser
version.

## Verified registry inventory

The planning list named 17 domains. The runtime registry contains 20 dedicated
domains. The additional domains found in code are `biquge.tw`, `uukanshu.cc`,
and `xbanxia.cc`; they are migrated and covered here rather than being dropped.

| Adapter | Domains | DOM version |
|---|---|---|
| `69shuba` | `69shuba.com`, `69shuba.cx`, `69shux.com` | `69shuba-dom-v1` |
| `69shumi` | `69shumi.com`, `69shumi.net` | `69shumi-dom-v1` |
| `biquge` | `biquge.tw`, `22biqu.com` | `biquge-dom-v1` |
| `uukanshu` | `uukanshu.cc` | `uukanshu-dom-v1` |
| `17k` | `17k.com` | `17k-dom-v1` |
| `52shuku` | `52shuku.net` | `52shuku-dom-v1` |
| `fanqienovel` | `fanqienovel.com` | `fanqienovel-dom-v1` |
| `jjwxc` | `jjwxc.net` | `jjwxc-dom-v1` |
| `qidian` | `qidian.com` | `qidian-dom-v1` |
| `novel543` | `novel543.com` | `novel543-dom-v1` |
| `hetushu` | `hetushu.com` | `hetushu-dom-v1` |
| `ixdzs8` | `ixdzs.com`, `ixdzs8.com` | `ixdzs8-dom-v1` |
| `xbanxia` | `xbanxia.cc`, `xbanxia.com` | `xbanxia-dom-v1` |
| `bookqq` | `book.qq.com` | `bookqq-dom-v1` |

## Runtime contract

Every dedicated entry is a `DomSourceAdapter`. It owns domain policy, P02 URL
canonicalization, ordered metadata/link/content selectors, removal selectors,
P12 page/content validation, P03 normalization/hash semantics, and an explicit
version. Normal parsing returns `parser_method="dom"`.

All P13 adapters have no regex fallback. The only runtime fallbacks remain
`69shuba` and `69shumi`, where P12 fixtures prove a legacy layout can be
recovered safely. If an adapter has no configured fallback, selector mismatch
returns typed `parse_failed`; it must not silently route through regex.

## Fixture and contract test conventions

`tests/fixtures/source_adapters/` contains one sanitized combined HTML fixture
per P13 adapter. Each fixture has synthetic book metadata, two chapter links,
a chapter heading, two content paragraphs, and removable navigation/advertising
nodes. Tests exercise `preview_from_html` and `chapter_from_html` only, so
network access is structurally absent.

`tests/test_dom_parser_registry_contract.py` validates:

- all 20 dedicated domains resolve to versioned DOM adapters;
- each P13 fixture emits DOM preview/chapter results with canonical hashes;
- chapter links remain on the adapter's allowed domain;
- cleanup removes navigation and advertising text;
- every adapter maps a status-200 challenge page to
  `user_verification_required`;
- only the P12-proven 69shuba-family adapters have a regex fallback.

## Adding or changing an adapter

1. Add or verify the source policy in `app/ingestion/source_policies.py` before
   registering the domain. The source policy remains the authority for whether
   a public URL may enter the import flow.
2. Add the adapter identity and exact domain tuple to the registry source entry
   and add the matching `DomSelectorConfig` to the P13 DOM configuration map
   in `build_default_source_adapters()` in
   `app/ingestion/source_adapters.py`. The returned entry must be a
   `DomSourceAdapter`; the pre-P13 selector fields are identity/domain
   provenance only and must not be configured as a runtime fallback. Include
   ordered selectors for title, chapter title, author, description, cover,
   chapter links, chapter content, and source-specific removal targets where
   needed.
3. Assign a version such as `example-dom-v1`. Bump the version whenever
   extraction or validation semantics materially change, so parser telemetry
   remains interpretable across layouts.
4. Add a sanitized fixture under `tests/fixtures/source_adapters/` and a case
   to `CASES` in `tests/test_dom_parser_registry_contract.py`. The fixture must
   contain no live content, cookies, credentials, tokens, or private URLs.
5. Cover a normal preview and chapter parse, canonical link handling, cleanup,
   and the typed challenge path through the parameterized contract suite.
6. Do not add a regex fallback merely because a selector is inconvenient. Add
   one only after a fixture demonstrates a real selector mismatch, the legacy
   parser succeeds on that same sanitized fixture, and a regression test proves
   that fallback telemetry contains only adapter id/version/target.
7. Run the contract suite, impacted adapter tests, backend lint/typecheck, and
   full backend pytest. Default CI must not make an Internet request.

## Boundaries and remaining risk

P13 adds no route, schema, queue, retry, browser lifecycle, frontend, or
provider behavior. Synthetic fixtures prove the extraction contract, not a
live website's current markup; live-layout review remains an explicit
operational validation activity and must not be implied by these tests.

## Verification

- Registry contract suite: `46 passed in 3.81s`.
- Broader adapter/fetch/source regression suite: `113 passed, 1 warning in
  19.13s`.
- Backend compile, lint/typecheck, and `git diff --check`: passed.
- Full backend suite: `1006 passed, 2 warnings in 1677.20s (0:27:57)`.

The two full-suite warnings are existing dependency deprecations from
`passlib/crypt` and `jieba/pkg_resources`; they are unrelated to P13.
