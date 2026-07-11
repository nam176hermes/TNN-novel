# Live Performance Audit Implementation Note

## Audit Baseline

- Date: 2026-07-10
- Canonical repository: `/mnt/c/Users/thenam/Documents/Novel-TNN`
- Branch and baseline: `master`, `c4a7873aa1d9b316ed2c96fbac4e3b3230ced7e2`
- Benchmark checkout: `/home/thenam176/Novel-TNN-P1-audit` on the WSL Linux filesystem
- Python: 3.11.15 from the benchmark checkout `.venv`
- Node/npm: 22.23.0 / 10.9.8
- Playwright: 1.61.1, Chromium
- ffmpeg/ffprobe: 6.1.1
- Viewports: 1440x1000, 390x844, and 360x740

The initial Git baseline was clean before P1 started. The benchmark checkout was cloned from the baseline commit and installed from `pyproject.toml`, `requirements.txt`, and `web/package-lock.json`. No `.env`, operator database, novel content, provider credentials, or runtime artifact was copied into it.

## Isolation

All writes used the synthetic database at `output/audit/data/pipeline.db` in the Linux checkout. Fixtures comprised 3 initial synthetic books, 157 chapters, 500 glossary rows, one QA report, one audio artifact, and text files from 24 KB to 4.9 MB. Later scale tests added isolated import results and 50 one-chapter books. The live operator database was not opened or modified.

No paid translation or TTS provider was invoked. TTS used generated WAV data, fixture synthesis, ffmpeg, and ffprobe. No restore was performed.

## Method

- API routes: five HTTP calls per read route, with the first call labeled cold-route and the remaining four summarized by median.
- Page navigation: production build, real API, real Chromium, 100-150 ms settling allowance, cold lazy-route pass plus three repeat runs for library, import, jobs, sources, and reader.
- Import: real browser file selection plus real isolated API commits.
- Reader: real API data, normal and long synthetic chapters, DOM size, request capture, long-task observation, and mode interaction.
- Database: `EXPLAIN QUERY PLAN`, table counts, raw SQLite connection timing, and project connection timing.
- UI/UX: screenshots plus desktop/mobile interaction and DOM inspection.
- Accessibility: practical DOM and keyboard-control inspection; this is not a formal WCAG audit.

Machine-readable results and screenshots are untracked under `output/live-audit-2026-07-10/`.

## Limitations

- Timings are local WSL Linux results, not WAN or low-end Android benchmarks.
- Playwright timing is approximate and is not reported as official Core Web Vitals.
- React DevTools Profiler was not available; rendering conclusions use DOM counts, network traces, long tasks, and interaction timing.
- Real-provider synthesis speed, provider rate limits under load, production restore, and large private-library behavior remain untested.
