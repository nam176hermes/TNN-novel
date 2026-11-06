# Mobile Reader and PWA

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Reader live result

At `390x844`, Reader displayed readable text, one article region, previous and next navigation, and no horizontal overflow. The fixed chapter controls remained available. [Source] `/tmp/novel-tnn-live-audit/controller/mobile-reader/390x844-reader.png`

## Offline result

Manual cache succeeded and persisted an offline manifest. A first-session immediate offline reload returned a blank page. Repeating the flow after an online controlled reload restored 10,064 characters, one article, and the offline indicator. [Source] first-session and warmed PWA JSON files under `/tmp/novel-tnn-live-audit/controller/browser-fresh/`

## Cause boundary

The service worker pre-caches hashed assets into the shell cache. Asset fetch handling reads the runtime cache. A controlled online request warms the runtime cache; the first install session can therefore report chapter-cache success before runtime app-shell readiness. [Source] `web/public/reader-offline-sw.js`

## Existing test limitation

The current Playwright test performs an online reload before the offline assertion. It proves the warmed path and protected API non-caching, not the first-session path. [Source] `web/e2e/novel-tnn.spec.ts`

## Verdict

Mobile Reader: **GO_WITH_LIMITATIONS**. Online reading works. Warmed offline reading works. First-session offline readiness requires repair.
