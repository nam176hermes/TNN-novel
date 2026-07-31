# Export Workflow

## Export vs Backup

Novel-TNN separates two different operator tasks:

- `Book Export`: reader-facing files for reading or listening.
- `System Backup`: operational recovery archive for the whole app.

Do not treat a book export as a backup. Do not treat a system backup as a reading export.

## Book Export

Current authenticated book export routes:

- `POST /api/books/{book_id}/exports`
- `GET /api/books/{book_id}/exports/{format}/download`
- `GET /api/books/{book_id}/exports/audiobook/m4b/download`
- `GET /api/books/{book_id}/exports/annotations/{format}/download`
- `GET /api/glossary/export`

Current supported formats:

- Book text:
  - `TXT`
  - `DOCX`
  - `EPUB`
- Audiobook artifact:
  - `M4B` only when chapter audio already exists and export succeeds
- Reader annotations:
  - `JSON`
  - `Markdown`
  - `CSV`
- Glossary:
  - `JSON`
  - `CSV`

## Export behavior

- Book exports use translated Vietnamese chapters by default.
- Export filenames are sanitized.
- Downloads require authentication.
- Export metadata no longer exposes internal absolute filesystem paths.
- Export output never includes provider keys or internal job logs.

## Audio / Audiobook export

- Chapter MP3 playback/download stays on protected audio routes.
- Book-level `M4B` export is available only when chapter audio exists.
- If some chapters do not have audio yet, the operator should generate chapter audio first.
- Long-book `M4B` should still be treated as operationally sensitive; run `scripts/smoke_tts_audio.py` in fixture mode first, then run `--real-provider --dry-run`, and only then run a bounded real-provider validation on the intended book or representative subset.
- `M4B` export should fail clearly when `ffmpeg` is missing or when the generated artifact is empty.
- Representative validation M4B artifacts written by the smoke tool are not the same thing as the canonical authenticated book export route.

## Glossary export

Glossary export preserves review metadata, including fields such as:

- `review_status`
- `locked`
- `first_seen_chapter_id`
- `first_seen_chapter_number`
- `source_context`

Use glossary export for review or migration, not as a full system recovery tool.

## Known limitations

- Markdown book export is not implemented yet.
- Full long-book `M4B` generation still depends on real-book operational verification.
- Book export does not replace system backup or restore drill procedures.
- Chapter markers and rich M4B metadata must be inspected with `ffprobe` or player testing before claiming production-ready audiobook compatibility.
