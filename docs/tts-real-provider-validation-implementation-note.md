# Phase 11 Real-Provider Validation Implementation Note

## Current provider support

Novel-TNN still keeps TTS server-side.

- `app/services/tts/tts_pipeline.py` remains the orchestration seam for chapter synthesis, retry, resume, cancel, and report writes.
- `app/services/tts/f5_vietnamese_engine.py` remains the primary local/real-provider engine path for F5 Vietnamese / ViVoice.
- `edge_tts` remains a fallback/provider variant for environments that intentionally choose it.
- `app/services/tts/audio_merger.py` still owns chapter MP3 merge and representative M4B merge.
- `app/export/m4b_exporter.py` still owns authenticated export-path M4B generation for operator downloads.

Phase 11 does not replace these paths. It adds bounded validation and inspection around them.

## Voice settings path

Voice settings still come from:

- env-backed defaults in `app/config.py`
- request-level `voice_config` values passed to `TTSPipeline.generate_chapter(...)`

The Phase 11 smoke flow can override:

- `voice_id`
- `rate`
- `volume`

It does not print reference transcript text or provider secrets.

## Real-provider invocation path

The bounded real-provider smoke path is still direct server-side synthesis:

1. select a bounded chapter scope from an existing book
2. run preflight only, or
3. call `TTSPipeline.generate_chapter(...)` with deterministic job ids
4. reuse completed chunks unless overwrite is explicitly requested
5. inspect resulting MP3 artifacts
6. optionally create a representative validation M4B from the selected chapter outputs

This keeps the Phase 2 durable job model intact and avoids a second runner architecture.

## Retry and timeout settings

Current runtime knobs remain env-driven:

- `TTS_CHUNK_TIMEOUT_SECONDS`
- `TTS_CHUNK_RETRIES`
- `TTS_QA_RETRIES`
- `TTS_CHUNK_MAX_CHARS`
- `TTS_CHUNK_MAX_SENTENCES`

Phase 11 validation focuses on proving these behaviors operationally:

- failed chunk retry
- successful chunk reuse
- cancel-before-merge safety
- zero-byte / partial-output detection

## Runtime and storage expectations

Expected cost/runtime varies heavily with provider, voice, and chapter size. Phase 11 therefore adds:

- explicit `--real-provider`
- bounded `--chapter-limit`
- optional `--max-chars`
- explicit confirmation unless `--yes`
- dry-run/preflight mode

Storage still lands under the configured backend data directory for real audio artifacts. Validation reports and representative M4B artifacts land under an operator-selected output directory.

## MP3 and M4B tooling requirements

- `ffmpeg` is required for chapter MP3 merge and representative/book M4B merge.
- `ffprobe` is strongly recommended for metadata, duration, and chapter-marker inspection.
- If `ffprobe` is missing, validation stays structurally useful but metadata and duration confidence is reduced.

## Operational risks that still remain

- real-provider timeout/rate-limit behavior depends on the configured provider and cannot be claimed without an actual bounded run
- long-book listening quality still needs human spot checks
- chapter markers inside M4B depend on what the current FFmpeg path actually writes in the target environment
- protected live-domain downloads must be validated against the deployed domain, not just local ASGI tests

## Intentional non-goals for Phase 11

- no TTS engine rewrite
- no job-runner rewrite
- no Celery/Redis/distributed queue
- no client-side/provider-side secret exposure
- no automatic full-book paid run without explicit operator flags
