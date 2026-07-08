# Novel Translation Pipeline

A local CLI pipeline for translating Chinese web novels (xianxia/xuanhuan) into Vietnamese for personal reading/listening.

**Legal boundary**: import only from public or authorized sources you are allowed to access. No DRM bypass, paywall bypass, or unauthorized scraping.

**Anti-bot features (Phase 5+)**: proxy rotation, captcha solving, and stealth headless browser for Cloudflare-protected sources.

---

## Installation

```bash
cd novel_pipeline
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"   # installs the `novel` CLI command + test tools
cp .env.example .env      # fill provider keys, local password, and secrets
npm --prefix web ci       # operator dashboard dependencies
```

For the current operator workflow, configure one cheap/free cloud provider first:

```bash
# Recommended starting point in .env
GEMINI_API_KEY=...
DEEPSEEK_API_KEY=...
# Optional free/cheap fallback
OPENROUTER_API_KEY=...
MOBILE_API_SECRET=replace-with-a-long-random-value
MOBILE_API_ADMIN_PASSWORD=replace-default-password
```

To avoid placing provider keys in shell history, write them through stdin:

```bash
printf '%s' "$GEMINI_API_KEY" | python scripts/ops.py set-provider-key GEMINI_API_KEY --stdin
printf '%s' "$DEEPSEEK_API_KEY" | python scripts/ops.py set-provider-key DEEPSEEK_API_KEY --stdin
printf '%s' "$OPENROUTER_API_KEY" | python scripts/ops.py set-provider-key OPENROUTER_API_KEY --stdin
```

After changing provider keys, restart the API and run `python scripts/ops.py doctor`.

Raw source import docs: `docs/raw-source-importer.md`

Read-only external source catalog docs: `docs/source-catalog.md`

Batch translation/audio docs: `docs/batch-jobs.md`

PWA install mode docs: `docs/pwa-install.md`

Android wrapper evaluation: `docs/android-wrapper-evaluation.md`

Remote deployment and backup hardening docs: `docs/deployment-hardening.md`

Ollama remains available as an optional local fallback. If you want to use it,
ensure Ollama is running with `qwen3:14b`:

```bash
ollama pull qwen3:14b
```

The app uses OpenAI-compatible `/chat/completions` provider settings internally.
Gemini, DeepSeek, OpenRouter, OpenAI-compatible providers, and Ollama can all be
configured without changing code.

---

## Phase 1 — Single Chapter Workflow

```bash
# 1. Initialize
python -m app.main init

# 2. Import chapter from file
python -m app.main import-file \
  --book "test_novel" --chapter 1 \
  --title "Chapter 1" --path "./chapter_1_zh.txt"

# 3. Clean
python -m app.main clean --book "test_novel" --chapter 1

# 4. Translate
python -m app.main translate --book "test_novel" --chapter 1

# 5. Check output
ls data/translated/test_novel/
cat data/translated/test_novel/chapter_0001.txt
```

Or import from clipboard (copy Chinese text first):
```bash
python -m app.main import-clipboard \
  --book "test_novel" --chapter 1 --title "Chapter 1"
```

---

## Phase 2 — Daily Batch Workflow

**Step 1**: Import and clean up to 15 chapters manually:
```bash
# Repeat for each chapter
python -m app.main import-file \
  --book "test_novel" --chapter 2 \
  --title "Chapter 2" --path "./chapter_2_zh.txt"

python -m app.main clean --book "test_novel" --chapter 2
```

**Step 2**: Check the translation queue:
```bash
python -m app.main queue --book "test_novel"
```

**Step 3**: Run the daily batch (translate + QA all cleaned chapters):
```bash
python -m app.main daily --book "test_novel" --limit 15
```

This will:
- Translate all cleaned chapters in order
- Run a QA check on each translation (detects missing text, name inconsistencies, etc.)
- Flag chapters scoring below 7.0 for manual review
- Save a daily report to `data/logs/daily_reports/daily_YYYY-MM-DD.json`

**Step 4**: Retry failed translations:
```bash
python -m app.main retry --book "test_novel"
# Or retry a specific chapter:
python -m app.main retry --book "test_novel" --chapter 3
```

**Step 5**: Review pending glossary terms:
```bash
# List pending terms
python -m app.main glossary-review --book "test_novel"

# Approve a term (by ID)
python -m app.main glossary-review --approve 5

# Reject a term
python -m app.main glossary-review --reject 7
```

---

## CLI Commands

| Command | Description |
|---|---|
| `init` | Initialize project: folders, SQLite DB, starter glossary |
| `import-file` | Import chapter from a local `.txt` or `.html` file |
| `import-clipboard` | Import chapter from system clipboard |
| `clean` | Clean a raw chapter (removes boilerplate, ads) |
| `translate` | Translate one chapter via Ollama |
| `list` | List chapters (filter by `--book`) |
| `queue` | Show translation queue (pending or failed) |
| `daily` | Batch: translate all pending chapters + QA + report |
| `retry` | Retry failed translations |
| `glossary-review` | Review/approve/reject pending glossary terms |

---

## Data Layout

```
data/
  raw/           # original imported text
  cleaned/       # after boilerplate removal
  translated/    # final Vietnamese output
    test_novel/
      chapter_0001.txt
      chapter_0002.txt
  audio/         # (Phase 3: TTS output)
  exports/       # (Phase 5: EPUB, M4B)
  glossary/      # default glossary JSON
  logs/
    daily_reports/   # daily_YYYY-MM-DD.json
```

Database: `data/pipeline.db` (SQLite)

---

## Translation Quality

Uses a 2-pass approach:
1. **Translate**: Ollama + Qwen3:14b, chunked at 2000 chars, glossary injected, style-controlled prompt
2. **QA Review**: Second Ollama pass — checks for missing sentences, name inconsistencies, untranslated fragments, scores 0-10

Chapters scoring < 7.0 are flagged in the daily report.

---

## Roadmap

## Phase 3 — Audio Generation

Generate MP3 audio for a single chapter:
```bash
python -m app.main tts --book "test_novel" --chapter 1
```

Optional flags:
```bash
# Custom voice (default: vi-VN-HoaiMyNeural)
python -m app.main tts --book "test_novel" --chapter 1 --voice vi-VN-NamMinhNeural

# Speech rate (default: -5%)
python -m app.main tts --book "test_novel" --chapter 1 --rate "-10%"
```

Output: `data/audio/test_novel/chapter_0001.mp3`

Chapter status becomes `audio_done`.

After running TTS on all chapters:
```bash
ls data/audio/test_novel/
# chapter_0001.mp3
# chapter_0002.mp3
# chapter_0003.mp3
```

**Vietnamese voices available (edge-tts):**
- `vi-VN-HoaiMyNeural` — female (default, recommended)
- `vi-VN-NamMinhNeural` — male

**How it works:**
1. Text split into sentence-aware chunks (≤2000 chars each)
2. Each chunk synthesized via Microsoft Edge TTS (online)
3. Chunks merged with FFmpeg
4. Loudness normalized with FFmpeg loudnorm filter
5. MP3 metadata (title, album, track number, genre=Audiobook) embedded
## Phase 4 — Local Web Dashboard

Start a local dashboard at http://127.0.0.1:8000:
```bash
python -m app.main dashboard
```

Optional flags:
```bash
# Custom host/port
python -m app.main dashboard --host 0.0.0.0 --port 8080
```

Available endpoints (JSON API):
- `GET /books` — list all books
- `GET /chapters?book=<title>` — list chapters (filter by book)
- `GET /queue?status=cleaned` — pending chapters (status=cleaned or failed)
- `POST /translate/{chapter_id}` — translate a chapter by ID
- `POST /tts/{chapter_id}?voice=...&rate=...` — generate audio for a chapter
- `GET /glossary` — pending glossary terms
- `POST /glossary/approve/{term_id}` — approve a term
- `POST /glossary/reject/{term_id}` — reject a term
- `GET /daily-report` — latest daily report

Interactive API docs: http://127.0.0.1:8000/docs (Swagger UI)

The dashboard provides the same functionality as the CLI but via a browser-friendly interface.
Use it to monitor progress, trigger translations/QA/TTS, and review glossary terms.

## Mobile API

Start the mobile API backend at `http://0.0.0.0:7860` by default:

```bash
python -m app.mobile_api
```

Authentication is required for every `/api/*` endpoint except:
- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `GET /api/health`
- `GET /api/ready`
- `GET /api/version`

The browser/operator dashboard authenticates with `Authorization: Bearer <token>`.
Do not put shared API secrets in browser code. Configure browser/mobile origins
with `MOBILE_API_CORS_ORIGINS` as a comma-separated list.

The Vite operator dashboard lives in `web/`. For local development, run both
services with:

```bash
scripts/start-local.sh
scripts/status-local.sh
scripts/smoke-local.sh
```

Stop them with:

```bash
scripts/stop-local.sh
```

For single-service operation, build the frontend and let FastAPI serve `web/dist`:

```bash
npm --prefix web run build
MOBILE_API_SERVE_WEB=1 WEB_DIST_DIR=web/dist python -m app.mobile_api
```

Then open `http://127.0.0.1:7860/`.

## Operations / DevOps

P5 adds practical personal-use operations:

```bash
# Check runtime prerequisites, DB initialization, frontend tools, provider keys
python scripts/ops.py doctor

# Run the full backend/frontend verification suite
scripts/verify.sh

# Run quick static checks only
scripts/lint.sh

# Create a timestamped backup under backups/
python scripts/ops.py backup

# Restore safely into data_restored/ by default
python scripts/ops.py restore backups/<archive>.tar.gz

# Back up data, remove orphan chapter rows, and delete an empty stale
# data/novel_pipeline.db if it exists
python scripts/ops.py repair-db --remove-empty-stale-db

# Rotate runtime logs under data/logs/runtime
python scripts/ops.py rotate-logs --force

# Store a provider key in .env without printing it
printf '%s' "$GEMINI_API_KEY" | python scripts/ops.py set-provider-key GEMINI_API_KEY --stdin
```

Detailed Docker, systemd, backup/restore, smoke test, and recovery steps are in
`docs/operations/P5_RUNBOOK.md`.

## Phase 5 — EPUB and M4B Audiobook Export

Export translated chapters as EPUB ebook:
```bash
python -m app.main export-epub --book "test_novel"
```

Export chapter MP3s to single M4B audiobook:
```bash
python -m app.main export-m4b --book "test_novel"
```

This also exports an M3U playlist.

Output:
```
data/exports/
  test_novel/
    test_novel.epub     # EPUB ebook
    test_novel.m4b      # M4B audiobook
    test_novel.m3u      # Playlist for chapter MP3s
```

---

## Notes

- Translation may call configured cloud model APIs. Ollama is only a local fallback when selected/configured.
- TTS uses edge-tts, which calls Microsoft online TTS.
- Glossary is stored in SQLite and reused across chapters. New terms detected during translation are saved as pending (unapproved).
- Provider/model defaults are configurable through the operator dashboard and SQLite provider settings.
