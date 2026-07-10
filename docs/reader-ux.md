# Reader UX

## Implementation Note

Current reader code lives mainly in `web/src/components/ReaderView.tsx`, with supporting panels under `web/src/components/reader/`. The reader receives book/chapter state from the app shell, loads chapter translation/raw content through the existing API client, and stores local reader settings in `localStorage`.

Existing reader behavior before this phase already included:

- Library/book/chapter entry points from the translated-book reader route.
- Vietnamese translation rendering through `ReaderTextSurface`.
- Raw Chinese rendering through `ReaderRawTextSurface`.
- A split raw/translation mode.
- Typography/theme settings, scroll/paginated mode, full-screen and instant mode.
- Bookmarks, highlights, notes, local mark export/import, and server sync when an API client is available.
- Reading progress persistence and sync.
- Reader dictionary, AI/X-Ray, audio controls, and offline cache controls.

This phase keeps the data model and backend reader APIs intact. It adds reader UX/state around content modes and QA visibility only.

## Reader Modes

- `Bản dịch`: Vietnamese-only reading. This is the default mode for long reading.
- `Raw`: Chinese-only source reading. Disabled when the current chapter has no raw/source text.
- `Song song`: existing raw/translation comparison mode.
- `Raw gọn`: Vietnamese reading with raw Chinese hidden behind per-paragraph expand buttons.
- `QA`: Vietnamese reading with chapter QA summary and paragraph-level QA badges where a QA report exists.

The selected content mode is saved in `localStorage` with `novel-reader-text-mode-v1`. If a raw-dependent mode is selected but the next chapter has no raw text, the reader safely falls back to Vietnamese-only mode.

## Settings

Reader typography settings remain stored locally in `novel-reader-settings-v1`:

- font family
- font size
- line height
- paragraph spacing
- content width
- light, dark, sepia, and E-Ink themes
- scroll or paginated reading
- instant mode

Settings persist across chapters on the same browser/device.

## Paragraph Alignment

The reader uses best-effort paragraph splitting from blank lines for raw and translated text. Raw-collapsed mode matches raw paragraph `N` to Vietnamese paragraph `N`. If a source chapter has different paragraph counts, the unmatched raw paragraph simply does not appear under that Vietnamese paragraph.

Future work can add server-side stable paragraph IDs/alignment metadata. This phase does not alter chapter storage.

## QA Overlay

QA overlay loads the existing chapter QA report through `GET /api/books/{book_id}/chapters/{chapter_id}/qa`.

Displayed fields are intentionally small and sanitized:

- overall status
- Chinese leakage count
- glossary violation count
- repetition warning
- length ratio when available

Paragraph badges currently include:

- `Rò chữ Trung`
- `Vi phạm thuật ngữ`

The reader does not render raw QA JSON, stack traces, provider details, or internal debug payloads.

## Audio / TTS Panel

Phase 6 adds a compact `Audio và TTS chương` panel to the reader. It shows whether the current chapter has audio, exposes protected play/download actions when audio exists, and starts chapter TTS through the existing backend job API when audio is missing.

The panel warns before TTS when:

- the chapter has no Vietnamese translation
- the chapter QA report is `FAIL`
- the QA report still detects Chinese leakage

Missing translation blocks TTS. QA warnings do not block generation because the operator may intentionally override after review. Running/failed TTS job status, progress, retry, and cancel controls are shown in the same reader surface.

Bulk audiobook generation remains an explicit action under `Thêm tùy chọn` and requires confirmation before creating a job.

## Notes, Highlights, Bookmarks

Existing bookmark, highlight, and note behavior is preserved. Marks remain attached to paragraph index and character range where available. This is reliable for unchanged imported/translated chapter text, but paragraph-index marks can drift if the chapter content is later edited heavily.

User-entered notes are rendered as text through React, not as raw HTML.

## Translation Issue Reporting

Dedicated paragraph issue records are not added in this phase. Operators can currently use paragraph notes/highlights and QA/glossary review to track translation issues. A future phase can add DB-backed issue types such as wrong name, wrong term, missing text, awkward Vietnamese, Chinese leakage, repeated text, and glossary violation.

## Mobile Behavior

The content-mode switcher is horizontally scrollable on small screens to avoid overflow after adding Raw gọn and QA modes. Raw-collapsed mode is the preferred mobile review mode because it keeps Vietnamese reading flow intact and opens raw text only when needed.

Parallel mode still stacks to one column on narrow screens through existing responsive CSS.

## Known Limitations

- Paragraph alignment is best-effort and not backed by stable server paragraph IDs.
- QA badges are derived from available report fields. If a QA report lacks paragraph indexes/source terms, badges may attach to the first paragraph.
- Dedicated translation issue reporting is postponed to avoid introducing a new backend workflow in this reader-focused phase.
- Server-side reader preferences are not introduced; settings remain per browser/device.
