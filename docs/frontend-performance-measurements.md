# Frontend Performance Measurements

## Production Bundle

| Asset | Raw size | Gzip |
| --- | ---: | ---: |
| Main entry | 341.96 KB | 106.78 KB |
| Global CSS | 188.78 KB | 32.26 KB |
| ReaderView route | 181.73 KB | 49.54 KB |
| ImportPanel route | 49.70 KB | 13.41 KB |
| Providers route | 25.94 KB | 15.23 KB |
| Sources route | 25.65 KB | 6.66 KB |

Three clean production build runs on Linux took 9.59, 9.80, and 10.43 seconds including TypeScript. Vite route chunks are already lazy. Reader audio, dictionary, X-Ray, offline, QA, marks, search, settings, and selection tools are all imported by the Reader route and therefore arrive together.

## Browser Timing

Login heading appeared in 91-161 ms. Login to useful authenticated shell took 830-844 ms. Cold lazy-page runs were generally 0.94-0.96 seconds. Repeat runs, including a 100 ms settle allowance, were generally 143-160 ms.

Three-run examples:

| Flow | Desktop | Mobile |
| --- | --- | --- |
| Library | 923, 159, 158 | 918, 153, 156 |
| Import | 329, 142, 147 | 936, 148, 151 |
| Jobs | 224, 149, 149 | 232, 149, 143 |
| Sources | 942, 156, 155 | 243, 156, 151 |
| Reader open | 520, 227, 372 | 394, 835, 154 |

No browser console errors occurred in the successful desktop/mobile/small-mobile run. No horizontal document overflow was detected after the two mobile fixed-control patches.

## Rendering Findings

- Reader QA mode on the long fixture reached about 5,182 DOM nodes and took up to 599 ms in the measured interaction.
- Browser long tasks reached about 249 ms during desktop import/reader activity and 198-216 ms on mobile.
- Reader startup requested chapters twice and repeated reader state and QA requests in observed runs.
- The long Reader route remains the only route chunk close to the main entry size.
- Import previews stayed below 516 DOM nodes because the UI samples chapter content rather than rendering full files.

## Recommendations

- P1: remove duplicate Reader load requests before adding memoization.
- P1: profile and isolate QA overlay computation/rendering from the core text surface.
- P2: lazy-load Reader X-Ray, dictionary, AI, annotation import/export, and audiobook controls when opened.
- P2: split global CSS by feature only after the baseline and visual regression coverage are retained.
- P3: add a development-only bundle report; do not add production runtime dependencies for it.
