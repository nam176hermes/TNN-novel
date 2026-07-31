# Performance and accessibility certification

## Verdict

Performance: **GO** for the audited private production scale.

Accessibility: **GO_WITH_LIMITATIONS**.

## Before/after large-list measurements

| Surface | Hermes audit baseline | Post-repair measurement |
|---|---:|---:|
| Glossary DOM nodes | 16,813 | 541 |
| Glossary visible interactive elements | 3,510 | 59 |
| Reader TOC DOM nodes | 5,342 | 165 |
| Reader TOC visible buttons | 707 | 23 |

The post-repair trees are bounded by the virtual window rather than total
record count. Search/filter, current selection, keyboard focus, and TOC current
chapter behavior are covered by component and Playwright tests.

## Reader performance

- Isolated warm Reader navigation to first visible text: 32 ms for the sampled
  short chapter. This is a staging browser timing, not a WAN/provider claim.
- Four rapid transitions: four requests each for source, translation, QA, and
  dictionary pack; no duplicate core read owner observed.
- Single post-interaction JS heap snapshot: approximately 16.1 MB.
- Mobile surface maximum: 662 DOM nodes.
- Desktop surface maximum: 1,500 DOM nodes.
- No horizontal overflow at any required viewport.

Reader progress/sync POST frequency varied with navigation and debouncing. It
did not duplicate content reads or produce stale visible content. A long-run
memory soak remains outside this certification.

## Dialog keyboard lifecycle

The Reader More dialog passed:

- focus entry into the dialog;
- Tab/Shift+Tab containment in tests;
- Escape close;
- restoration to the trigger;
- accessible dialog name and semantics;
- touch activation.

## Mobile touch targets

Across 360×740, 390×844, and 412×915, the automated visible-control audit
found zero controls below the approved approximately 44×44 CSS-pixel policy.
Hidden file inputs, range tracks, checkboxes, and radio controls were excluded
from false-positive sizing checks.

## Zoom and reduced motion

- A 200% CSS zoom smoke produced no horizontal overflow in the Reader.
- Repository CSS includes explicit `prefers-reduced-motion: reduce` rules.
- Reduced-motion emulation left one element with a non-zero computed duration;
  no blocking or required information depended on that motion.

These checks do not equal formal browser-zoom, screen-reader, or WCAG
conformance testing.

## Remaining limits

- No full screen-reader pass.
- No long-duration physical low-end Android memory/scroll soak.
- No complete contrast inventory or formal WCAG claim.
- Reduced-motion residual should be identified during the next accessibility
  review, but it did not reproduce a P0/P1 workflow failure.
