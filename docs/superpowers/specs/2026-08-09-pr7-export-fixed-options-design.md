# PR7 Export Fixed Options Design

## Goal

Remove misleading Export affordances while preserving the currently supported export request contract.

## Current capability

The book export API accepts only `{ format: "txt" | "docx" | "epub" }`. Chapter range, annotations, cover inclusion, and TOC configuration are not book-export request fields. The current cards look interactive but cannot change the request.

## User experience

- Replace the interactive-looking option cards with a clearly labelled `Thiết lập cố định` information section.
- State the actual fixed behavior in plain text:
  - scope: all translated chapters;
  - annotations: not included in book exports;
  - cover: not included;
  - TOC: generated according to the selected format's built-in behavior, with no user setting.
- Use non-control semantics and remove toggle switches, chevrons, hover/focus styling, and any wording that implies configurability.
- Keep the functional book picker and TXT/DOCX/EPUB export buttons unchanged.

## Contract boundary

- Do not add request fields or backend export features.
- Do not change standalone reader-annotation export endpoints.
- Every element that still looks like a control must remain keyboard focusable/clickable and affect an actual request or action.

## Verification

- Component tests assert fixed-default copy and absence of fake switches/interactive option controls.
- API-client tests continue to prove book export sends only the selected format.
- Existing export E2E flow still downloads the selected export.
