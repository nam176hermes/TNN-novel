# Performance and Request Ownership

## Browser measurements

| Surface | DOM nodes | Interactive elements |
|---|---:|---:|
| Dashboard | 332 | 14 mobile |
| Sources | up to 2,430 mobile | 110 |
| Glossary and style | 16,813 | 3,510 |
| Reader | about 455 | 6 mobile |
| Reader TOC | 5,342 | 707 |

[Source: browser evidence JSON `scans`]

## PERF-001: unvirtualized large lists

Glossary and Reader TOC materialize thousands of DOM nodes. This increases layout, memory, keyboard traversal, and assistive-technology cost. [Source: browser DOM scan]

Classification: P2, REPRODUCED.

## PERF-002: duplicate request ownership

Normal mobile navigation duplicated system status, backup, and Reader-state requests. Four rapid previous-chapter transitions produced 23 API calls, including seven translation, four source, four QA, four dictionary, and four Reader-sync calls. [Source: browser network summary and focused rapid-navigation probe]

Classification: P2, REPRODUCED.

Risk: stale responses can overwrite newer state, and repeated artifact reads waste I/O.

## Bundle observations

The isolated build reported approximately 191.30 kB for ReaderView, 349.16 kB for the main index, and 73.80 kB for ImportPanel before gzip. [Source: isolated Vite build log]

## Priority

Correct request ownership and stale-response handling before broad component refactors. Virtualize Glossary and TOC with keyboard and current-item behavior protected by tests.
