# TTS / Audiobook Workflow

## Implementation Note

Phase 10 operational note:

- `docs/tts-audiobook-operational-implementation-note.md`
- `docs/tts-real-provider-validation-implementation-note.md`

Current TTS/audio support is server-first. The reader and UI call authenticated APIs; provider keys, model paths, cache paths, and engine internals stay on the backend.

Relevant backend areas:

- `app/services/tts/tts_pipeline.py`
- `app/services/tts/chunker.py`
- `app/services/tts/audio_qa.py`
- `app/services/tts/audio_merger.py`
- `app/mobile_api/routers/tts.py`
- `app/mobile_api/routers/audio.py`
- `app/mobile_api/services/export_service.py`
- `scripts/smoke_tts_audio.py`

Relevant frontend areas:

- `web/src/components/ReaderView.tsx`
- `web/src/components/reader/ReaderAudioBar.tsx`
- `web/src/api/client.ts`

## Generate Chapter Audio

Open a translated chapter in the reader. The `Audio và TTS chương` panel shows whether audio exists.

- If no audio exists, use `Tạo audio chương`.
- If audio exists, use `Nghe audio` or `Tải MP3`.
- `Advanced` is reserved for regenerate actions.

Readiness rules before TTS starts:

- chapter must have Vietnamese translated text
- chapter QA `FAIL` shows a warning, but does not hard-block generation
- detected Chinese leakage shows a warning, but does not hard-block generation

## Text Readiness and Normalization

The TTS pipeline should use Vietnamese translated text only.

- empty translated text is rejected
- whitespace is normalized
- Vietnamese punctuation is normalized through the existing text normalizer path
- raw Chinese leakage should be reviewed before TTS, not silently ignored
- chapter title metadata is preserved for final artifacts

If Vinorm or VietNormalizer support is configured, the pipeline uses the configured backend. If not, the existing fallback normalization remains in effect.

## Chunking and Retry

Chunking uses stable ordered chunk metadata:

- `chunk_index`
- `start_char`
- `end_char`
- normalized chunk text

Operational rules:

- chunks must stay ordered
- empty chunks are dropped
- retry resets only `failed` / `qa_failed` chunks
- resume reuses completed chunk files when they still exist
- successful chunks should not be regenerated during a normal failed-chunk retry
- cancellation is checked between chunks and again before merge
- cancellation before merge should leave the job `cancelled` and avoid a misleading completed MP3

## Audio QA

Per-chunk QA checks where practical:

- missing file
- empty file
- silent WAV
- suspiciously short duration
- clipping warning
- text-length duration warning

Final output checks:

- merged chapter MP3 must exist
- merged chapter MP3 must be non-zero size
- M4B must exist and be non-zero size when requested
- job summary reports:
  - completed chunk count
  - failed chunk count
  - missing completed chunk files
  - audio QA warning count

If `ffprobe` is unavailable, duration-based QA for MP3/M4B is reduced and the system reports that duration QA was skipped.

## Bulk Audio

Use `Thêm tùy chọn` -> `Tạo audiobook còn thiếu`.

The confirmation dialog shows:

- translated chapter count
- chapters already having audio
- chapters missing translation
- translated chapters still missing audio

`M4B chưa sẵn` means the current book still has translated chapters without audio. The operator should finish chapter audio generation first.

## Job Progress

TTS jobs use the existing durable job model. The reader shows:

- job id
- job status
- provider/model when reported
- progress percent
- completed/failed chunk counts
- safe QA/operational warnings when available
- safe error text
- refresh, cancel, and retry failed chunk actions when available

The API should expose protected download URLs and safe summary data, not raw backend filesystem paths.

## Playback and Protected Downloads

Reader playback uses protected chapter audio routes:

- stream: `/api/books/{book_id}/chapters/{chapter_id}/audio`
- download: `/api/books/{book_id}/chapters/{chapter_id}/audio/download`

TTS job artifact downloads use:

- `/api/tts/jobs/{job_id}/download?format=mp3`
- `/api/tts/jobs/{job_id}/download?format=m4b`

All of these must remain authenticated/protected. The UI must not expose raw filesystem paths.

## MP3 / M4B Support

Chapter MP3 playback/download is available when a chapter audio artifact exists.

Book-level M4B is available only when chapter audio exists and ffmpeg-based merge succeeds. Treat M4B as operationally validated only after smoke succeeds for the intended environment.

Current confidence:

- chapter MP3 path is stronger than long-book M4B
- fixture smoke validates artifact creation and merge behavior
- real long-book listening quality still needs a real-book smoke before claiming production confidence

## Smoke Procedures

### Reader/UI smoke

```bash
.venv/bin/python scripts/smoke_reader_page.py
```

### Fixture-mode TTS/audio smoke

```bash
.venv/bin/python scripts/smoke_tts_audio.py
```

Default behavior:

- creates a temporary test DB and data dir
- generates fixture chunk audio without a paid provider
- validates chapter MP3 creation
- validates M4B creation if ffmpeg is available

### Optional real-provider smoke

```bash
.venv/bin/python scripts/smoke_tts_audio.py \
  --real-provider \
  --dry-run \
  --db-path /path/to/pipeline.db \
  --data-dir /path/to/data \
  --book-id 12 \
  --chapter-limit 5 \
  --max-chars 90000 \
  --output-dir output/tts-validation/medium-book \
  --yes
```

Use `--dry-run` first. It does preflight only and writes:

- `tts-operational-report.md`
- `tts-operational-report.json`
- `listening-checklist.md`

No provider calls happen in dry-run mode.

### Bounded real-provider execution

```bash
.venv/bin/python scripts/smoke_tts_audio.py \
  --real-provider \
  --db-path /path/to/pipeline.db \
  --data-dir /path/to/data \
  --book-id 12 \
  --chapter-id 340 \
  --provider f5_vietnamese \
  --voice default \
  --output-dir output/tts-validation/ch340 \
  --resume \
  --yes
```

Representative subset with M4B validation:

```bash
.venv/bin/python scripts/smoke_tts_audio.py \
  --real-provider \
  --db-path /path/to/pipeline.db \
  --data-dir /path/to/data \
  --book-id 12 \
  --chapter-limit 8 \
  --generate-m4b
```

### Optional protected-route smoke against a running server

```bash
.venv/bin/python scripts/smoke_tts_audio.py \
  --base-url https://your-domain.example \
  --username novel-admin \
  --password-file /secure/path/novel-tnn-smoke-password \
  --book-id 12 \
  --chapter-id 340 \
  --check-m4b-route
```

This route check validates:

- unauthenticated chapter audio stream denied
- authenticated chapter audio stream allowed
- authenticated chapter audio download allowed
- audio range request works when supported
- optional authenticated M4B export download route when `--check-m4b-route` is set

The password file must be a regular `0600` file. Do not use a password command-line flag, which can leak through shell history or process listings.

## Troubleshooting

- Provider not configured: verify TTS env vars and model files on the server.
- Missing translation: translate or import Vietnamese content before TTS.
- QA FAIL: review chapter QA before generating audio.
- Chinese leakage warning: fix the chapter or accept the risk before TTS.
- Failed job: inspect sanitized job logs, fix provider/ffmpeg/tooling issue, then retry failed chunks.
- Missing chunk file before merge: rerun failed chunks.
- Empty chapter MP3 or M4B: inspect ffmpeg output and rerun smoke.
- Missing ffmpeg/ffprobe: install ffmpeg and ffprobe for merge plus fuller duration QA.
- Canceled job: partial chunk artifacts may remain; retry from existing controls when safe.
- Protected download denied: re-authenticate and verify the current session.
- Real-provider run refused due to existing audio: rerun only when regeneration is truly intended and pass `--overwrite`.

## Current Limitations

- Per-book voice profiles are not implemented in this phase.
- The reader does not replace the TTS engine or chunking pipeline.
- Full long-book M4B quality still needs a real-book operational smoke.
- Fixture smoke validates artifact creation and protected route behavior, not human listening quality.
- Bulk audio confirmation still estimates from chapter/audio metadata; backend state remains the source of truth.
- Real-provider smoke writes validation reports and representative artifacts under an operator-chosen output directory, but canonical chapter audio still stays in the backend data directory.
