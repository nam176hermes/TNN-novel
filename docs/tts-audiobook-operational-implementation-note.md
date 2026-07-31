## Phase 10 TTS / M4B Operational Implementation Note

Phase 11 follow-up lives in:

- `docs/tts-real-provider-validation-implementation-note.md`

### Current architecture

Novel-TNN keeps TTS and audiobook generation server-side.

- `app/services/tts/tts_pipeline.py` orchestrates chapter TTS jobs, retry, cancel, report writing, and chapter audio path updates.
- `app/services/tts/f5_vietnamese_engine.py` provides the current F5/ViVoice chunk engine and cache key generation.
- `app/services/tts/chunker.py` splits normalized Vietnamese chapter text into stable chunks with metadata.
- `app/services/tts/audio_qa.py` performs deterministic per-file audio QA.
- `app/services/tts/audio_merger.py` merges chunk audio into chapter MP3 and book M4B artifacts through `ffmpeg`.
- `app/mobile_api/routers/tts.py` exposes authenticated TTS job APIs.
- `app/mobile_api/routers/audio.py` exposes authenticated protected chapter audio stream/download APIs.
- `app/mobile_api/services/export_service.py` exposes authenticated book-level M4B export.

The current design is already job-based and restart-aware enough for this phase. Phase 10 should harden output validation and operator recovery rather than replace the runner.

### Current chunking behavior

- Chapter TTS reads Vietnamese translated text from `translated_text_path`.
- Text is normalized with `normalize_text(..., backend=settings.tts_normalizer)`.
- `chunk_text(...)` creates ordered chunks with:
  - `chunk_index`
  - `start_char`
  - `end_char`
  - `normalized_text`
- Resume mode already reuses completed chunk artifacts when the chunk row remains `completed` and the stored path still exists.

Current operational risk:

- chunking has basic tests, but it still needs more edge-case validation for very long paragraphs, dialogue-heavy text, and provider-limit boundaries.

### Current retry behavior

- Failed chunk retry already exists in `retry_failed_chunks(job_id)`.
- It only resets rows in `failed` or `qa_failed` states.
- It then re-runs `generate_chapter(..., resume=True)` for the same job id.
- Successful chunks are intended to be reused rather than regenerated.

Current operational risks:

- retry semantics need stronger tests around partial failures and completed-chunk reuse
- final output validation after retry is still light

### Current cache behavior

- The F5/ViVoice engine uses `stable_audio_cache_key(...)`.
- The cache key already includes:
  - normalized text
  - voice config
  - model config
- Cached WAV files are reused when they exist and are non-zero size.

Current operational risks:

- cache correctness is good enough structurally, but coverage should prove different settings do not collide and failed partial outputs are cleaned up

### Current MP3 / M4B behavior

- Chapter MP3 is created by `merge_chapter_audio(...)`.
- Book M4B is created by `merge_book_m4b(...)` in the TTS service path and by `app/export/m4b_exporter.py` in the export path.
- Protected download APIs already exist for:
  - chapter audio stream/download
  - TTS job artifact download
  - audiobook export download

Current operational risks:

- chapter-level QA does not yet validate expected chunk count versus produced files at the pipeline level
- merge success is mostly inferred from file creation, not from a richer post-merge validation pass
- M4B support exists, but long-form operational confidence is still limited without an explicit smoke path

### What Phase 10 will change

- add deterministic TTS operational validation where small patches are enough
- strengthen chunk retry/cancel/merge correctness checks
- add coverage for chunking edge cases and output QA edge cases
- add a dedicated TTS/audio smoke script for fixture-mode operational verification
- update workflow docs so M4B support is described truthfully

### What Phase 10 will intentionally leave unchanged

- no TTS engine rewrite
- no job runner rewrite
- no Celery/Redis/distributed queue
- no new frontend architecture
- no public or client-side exposure of provider/model secrets
- no weakening of protected audio/export routes
