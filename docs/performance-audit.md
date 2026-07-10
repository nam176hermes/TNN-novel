# Performance Audit

## Measured Baseline

### Frontend Build
- Command: `npm --prefix web run build`
- Result: passed
- Duration: 23.52s
- Notes: Vite emitted a plugin-timing warning; major time was spent in `vite-resolve`, `vite:asset`, and `vite:css-post`

### Frontend Bundle Sizes
- `web/dist/assets/index-0nrX7BLv.js`: 341.96 kB
- `web/dist/assets/ReaderView-Cs_yt5uV.js`: 181.73 kB
- `web/dist/assets/index-Cpg1hn-s.css`: 188.58 kB
- `web/dist/assets/ImportPanel-BoyT7EyM.js`: 49.70 kB
- `web/dist/assets/ReaderView-Cs_yt5uV.js` is the single largest route chunk and is a likely first target for future split work

### Import Performance Constraints
- Browser-side text import limit in UI: 5 MB
- Browser-side ebook upload limit in UI: 95 MB
- Server-side wizard import limit: 5 MB
- The import panel does a client-side byte count and encoding check before submission, which is good for correctness but still means the full text sits in browser memory

### Database / Data Footprint
- `data/pipeline.db`: about 47 MB at audit time
- Rows observed:
  - `books`: 15
  - `chapters`: 4175
  - `translated chapters`: 4159
  - `glossary_terms`: 3111
  - `audio files`: 8

## Verification Results

### Passed
- `npm --prefix web run typecheck`
- `npm --prefix web run build`
- `git diff --check`

### Failed Or Blocked
- `scripts/verify.sh` failed early because `python -m pyflakes` is not executable in the active environment
- `pytest` via the available system interpreter fails on many backend tests because `jose` and `pyperclip` are missing from that environment
- `app.mobile_api` startup in the current venv fails on an import error involving `fastapi` / `starlette`
- `npm --prefix web test` has at least one failing integration test:
  - `web/src/App.integration.test.tsx`
  - failure: translated-library flow expects heading `Đọc truyện`, but the rendered workflow page did not contain that heading

## Page-Load Findings

### Current State
- Live page-load measurements could not be completed because the local API bootstrap failed in the current environment
- The frontend test suite and production build are still useful evidence that the static app shell is healthy, but they do not replace runtime timing

### Inferred Bottlenecks
- `ReaderView.tsx` is very large and likely contributes to slower initial parse and larger JS execution cost
- `styles.css` is also very large and may increase style recalculation cost
- The Reader route is the largest JS chunk in the build output

## Import Performance Findings
- 5 MB browser-side parsing is probably acceptable for single-chapter text import, but it is already at the edge of a smooth browser experience
- The UI correctly guards large text files and shows preview state, but it still parses the whole payload on the client
- For larger chapter sets or repeated imports, server-side preview/session handling would be the safer next phase

## Reader Performance Findings
- The reader surface is the heaviest frontend area by bundle size and responsibilities
- State modules for reader cache, rich content, progress, marks, dictionary, offline cache, and search are already separated, which is good
- The main issue is not obvious virtualization demand yet; it is the size and complexity of the reader bundle and the amount of behavior packed into one component

## TTS Performance Findings
- Non-provider TTS code is split across chunking, merge, QA, and pipeline modules
- No live provider synthesis was run during this audit
- The report therefore treats provider time as NOT TESTED and only comments on non-provider overhead structurally

## Backend Performance Findings
- `app/database/db.py` is large and probably contains multiple hot paths that deserve targeted profiling
- `app/mobile_api/services/pipeline_service.py` is the next largest backend hotspot
- Many endpoints are domain-separated already, but several routers remain large enough that import-time cost and local reasoning cost are both noticeable

## Priority Summary
- P0: fix local environment drift so the API boots and pytest can run under the intended interpreter
- P1: reduce reader bundle and CSS size
- P1: address the failing translated-library integration test
- P2: consider server-side import preview for larger payloads
- P2: split the largest backend service/router modules by domain
