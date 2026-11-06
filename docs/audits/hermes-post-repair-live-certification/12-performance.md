# Performance


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Browser observations

All five audited viewports reported zero long tasks and zero horizontal overflow. Initial Reader DOM ranged from 327 to 479 nodes. Sampled operator routes ranged from roughly 332 to 717 nodes. This is materially below the pre-repair Glossary and TOC trees that exceeded 5,000 and 16,000 nodes. [Source: evidence/browser-summary.json]

## Request ownership

For two rapid chapter changes, the custom staging run observed:

- source reads: 2;
- QA reads: 2;
- translation reads: 3;
- final Reader surfaces: 1;
- visible loading residue: 0.

No stale visible overwrite was observed, but one duplicate translation read remains. Reader progress sync ranged from 5 to 14 POSTs depending on keyboard and focus traversal, which is bounded but noisy. [Source: evidence/browser-summary.json]

## Frontend build

| Asset | Raw size | Gzip size |
|---|---:|---:|
| ReaderView | 193.77 kB | 54.38 kB |
| Main index | 357.13 kB | 110.83 kB |
| ImportPanel | 73.80 kB | 19.79 kB |
| CSS | 229.22 kB | 38.41 kB |

The production build completed in 584 ms on the audit host. [Source: evidence/test-summary.json]

## Runtime sample

API CPU was about 0.13 percent and memory about 215 MiB. Worker CPU was about 0.29 percent and memory about 69 MiB. This is a point-in-time sample, not a soak or capacity limit. [Source: evidence/live-runtime-second-snapshot.json]

## Untested

No low-end Android memory soak, long-chapter multi-hour scroll, query-count profiler, disk-I/O trace, or production import timing was run.

## Verdict

**7.7/10**, suitable for intended single-operator scale with bounded Reader request debt.
