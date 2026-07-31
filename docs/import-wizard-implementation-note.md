# Unified Import Wizard Implementation Note

## Current Import Flows

- `POST /api/import/paste` imports one pasted chapter as raw/source text through `PipelineService.import_from_text`.
- `POST /api/import/file` imports one uploaded TXT/HTML-like file as raw/source text through `PipelineService.import_from_file`.
- `POST /api/import/ebook/preview`, `/api/import/ebook`, and `/api/import/ebook/job` preview/import translated ebooks through `EbookImportService`.
- `POST /api/import/url/preview` previews supported source URLs through existing source adapters and source policies.
- `POST /api/import/url` starts a background URL import job through the existing job service.
- Source catalog APIs are metadata-only and do not make catalog entries trusted import sources.
- Imported raw chapters are added to the library by creating books/chapters and raw text files. Translated ebook imports write translated chapter files.

## Existing Frontend Surfaces

- `ImportPanel.tsx` contains separate tabs for paste, file, and translated ebook import.
- URL/source import is exposed separately through source-related screens and API client methods.
- Post-import actions are scattered between `App.tsx` handlers, library selection, translation job buttons, and TTS actions.

## Duplicated/Risky Areas

- Paste and file routes duplicate single-chapter import shape and always write raw/source text.
- The older file/paste flows cannot correctly store Vietnamese translated text in `translated_text_path`.
- Duplicate handling is inconsistent: ebook import has duplicate strategies, while paste/file currently error on duplicate chapter numbers.
- Existing overwrite behavior must remain explicit. The wizard must not silently replace raw or translated content.

## Phase 3 Unification Scope

- Add a guided wizard UI as the primary import entry point.
- Add shared text import commit logic for reviewed paste/TXT plans so raw Chinese and Vietnamese translation are stored in the correct fields.
- Reuse existing translated ebook preview/import APIs for EPUB/ebook import.
- Reuse existing guarded source URL preview and URL job APIs.
- Reuse existing job service for optional translation/TTS actions.

## Left Unchanged

- No new crawler behavior.
- No source-policy bypass.
- No job runner redesign.
- No Celery/Redis or multi-worker queue.
- No tenant/multi-user migration.
- No automatic promotion of source catalog entries into supported import sources.

## Follow-up Hardening Notes

- Paste/TXT wizard commits now have a 5 MB backend payload cap and return HTTP 413 when exceeded.
- Browser TXT/Markdown/HTML-like files above 5 MB are rejected before parsing.
- HTML-like preview text is rendered as escaped text, not raw HTML.
- Duplicate overwrite requires an explicit confirmation checkbox when duplicate chapters are detected.
- Result screens expose import-more, open-reader/book, and view-job actions when callbacks are available.
- Current browser-side parsing is intentionally lightweight. A future server-side preview-session flow is the right next step if full-book TXT files routinely exceed the 5 MB safe client path.
