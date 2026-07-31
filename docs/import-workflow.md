# Unified Import Workflow

Novel-TNN now uses one guided import wizard for common import work. The wizard is intended for a single operator and keeps the existing source-policy, job, and auth protections intact.

## Supported Sources

- Paste text: best for one chapter or a short multi-chapter text block.
- Upload TXT/Markdown/HTML-like text files: parsed in the browser, then reviewed before saving.
- Ebook import: keeps the existing translated ebook preview/import flow for EPUB/AZW3/MOBI/PRC/TXT where supported by the current backend.
- Source URL: uses the existing guarded source preview/import job. Unsupported URLs remain blocked by source policy and URL safety checks.
- Source catalog: metadata only. A catalog entry can help fill a URL, but automated source import now requires a `VERIFIED` managed source from Source Hub.

## Size Limits

- Paste/TXT wizard imports are capped at 5 MB per reviewed commit.
- The browser rejects TXT/Markdown/HTML-like files above 5 MB before parsing them.
- The backend also rejects oversized `POST /api/import/wizard/text` payloads with HTTP 413.
- Larger books should be split into smaller imports or routed through the existing ebook/server-side import path.

Known limitation: paste/TXT detection currently runs in the browser. Normal 1-5 MB files are supported, but very large books need a future server-side preview-session design to avoid heavy client-side parsing.

## Raw vs Translated Content

The wizard detects whether text looks like raw Chinese, Vietnamese translation, mixed bilingual content, or unknown content.

- Raw Chinese is saved to the chapter source/raw text field.
- Vietnamese translation is saved to the translated text field.
- Reviewed bilingual plans can preserve both raw and translated text.
- Unknown or ambiguous text must be corrected by the operator before saving.

The wizard deliberately avoids mixing Chinese raw text into Vietnamese translation fields or labeling translated Vietnamese as raw Chinese.

## Duplicate and Overwrite Rules

Before saving, the wizard compares detected chapter numbers against the target book.

- Skip duplicate: keeps existing chapters unchanged.
- Error on duplicate: stops the import and reports the conflict.
- Replace duplicate: only runs when explicitly selected and confirmed.

Existing chapters are never silently overwritten. Manually edited translations should use skip or explicit replace after review.

## Chapter Detection

The text detector recognizes common headings:

- Chinese headings such as `第10章`, `第 10 章`, and Chinese numeral variants.
- Vietnamese headings such as `Chương 10`.
- English headings such as `Chapter 10`.
- Simple numeric headings such as `10. Tên chương`.

If no reliable headings are found, the wizard imports the text as one chapter and shows a warning so the operator can edit the title and chapter number.

## Cleaning and Preview

The preview step can normalize spacing, normalize line breaks, and remove obvious source watermark lines. It shows the first detected chapters, detected language/content mode, duplicate count, estimated size, and warnings before commit.

Previewed content is rendered as escaped text. HTML-like input such as `<script>`, `<img onerror>`, `<iframe>`, or raw HTML inside Markdown is not executed by the wizard preview.

Common warnings include:

- Content too short.
- Extremely long single chapter.
- Too many duplicate lines.
- No chapter headings detected.
- Language/content mode mismatch.
- Target chapter already exists.
- URL blocked or unsupported.

## URL Import Limits

URL import does not introduce a new crawler. It reuses the existing supported-source preview and import job paths. Private, local, invalid, or unsupported URLs remain blocked by the existing URL and source policy protections.

After Phase 8, source-based automation is stricter:

- preview is still allowed for supported-policy URLs
- starting a background source import job requires a matching managed source in Source Hub
- that managed source must be in status `VERIFIED`
- `NEEDS_REVIEW`, `IMPORTED`, `BROKEN`, and `BLOCKED` sources stay disabled for automation
- the wizard surfaces the review/test reason instead of failing later inside the job start request

## Translation and TTS Jobs

After saving text, the wizard can optionally create follow-up work through the existing job system:

- Save and create translation job for raw Chinese chapters.
- Save and create TTS job for translated Vietnamese chapters when TTS support is configured.

Long-running translation, source URL import, and TTS work stays in the background job lifecycle. The import request does not run those jobs inline.

## Troubleshooting

- `Unknown content mode`: choose raw Chinese or Vietnamese translation manually before saving.
- `Duplicate chapter number`: choose skip duplicate or explicit replace after reviewing the target book.
- `Unsupported file type`: use TXT/Markdown/HTML-like files in the text import tab, or use the ebook flow for EPUB/AZW3/MOBI/PRC.
- `URL blocked or unsupported`: use a source already supported by the app source policies.
- `No chapters detected`: import as one chapter or edit the headings before saving.
- `TXT file is too large`: split the text file or use the ebook/server-side import path.
- `Encoding không được hỗ trợ`: save the file as UTF-8 and import again.

## QA Notes

The import wizard was checked at desktop, tablet, and mobile viewport sizes. The wizard did not create horizontal page overflow in those checks, the import button remained visible, and mobile touch targets were usable at a 390px-wide viewport. During local browser QA, the already-running API process used production CORS settings, so the Vite frontend showed CORS/API availability errors even though `/api/ready` was reachable locally. Restart local development with `scripts/stop-local.sh && scripts/start-local.sh` when full API-backed browser QA is needed.

After Phase 4, committed imports may run best-effort glossary extraction and deterministic chapter QA. Raw Chinese chapters can create `NEEDS_REVIEW` glossary candidates; translated chapters can receive QA warnings when enough source or glossary context exists. These warnings are shown to the operator after import/translation, but they do not block the import commit.
