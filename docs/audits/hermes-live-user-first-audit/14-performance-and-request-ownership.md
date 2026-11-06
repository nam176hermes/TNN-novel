# Performance and Request Ownership

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Runtime signals

At inspection, API memory was about 191 MiB of a 768 MiB limit and worker memory was about 105 MiB of a 1.5 GiB limit. Both containers were healthy with no restart or OOM event. [Source] fresh Docker stats and inspect

## Frontend build

The production build passed. Main JavaScript gzip was about 110.27 kB, Reader chunk about 54.31 kB, and main CSS about 38.41 kB. [Source] `/tmp/novel-tnn-live-audit/controller/verify-production-env.log`

## Browser behavior

No horizontal overflow was observed at required mobile and desktop viewports. Glossary uses bounded rendering. Reader content rendered at production chapter size. [Source] live viewport metrics and screenshots

## Risks

- Reader, Import, API client, and CSS files remain large, increasing render and ownership complexity.
- No physical low-end Android memory profile or WAN throttling run was completed.
- No live long-book export or TTS throughput run was allowed.

## Verdict

Performance: **7.7/10**. No current production saturation evidence was found. Device-level and long-running workload evidence remains incomplete.
