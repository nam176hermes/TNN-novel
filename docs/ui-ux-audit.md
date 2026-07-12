# UI/UX Audit

## Evidence

- Production frontend against an isolated synthetic API.
- Desktop: `1440x1000`.
- Mobile: `390x844` and `360x740`.
- Screenshots: ignored `output/deep-audit-2026-07-11/`.
- Automated DOM checks: no horizontal overflow and no unlabeled button/input on the measured major routes.
- Browser console: no errors or warnings in the completed route pass.

This is a practical usability review, not a formal WCAG certification.

## Desktop

### KEEP_UNCHANGED

- Domain-oriented navigation is appropriate for a private translation operator.
- Library hierarchy, filtering, and card actions are understandable.
- Status cards surface readiness, provider, queue, and protection state clearly.
- Reader modes, QA tooling, glossary, source review, jobs, export, and provider controls should remain explicit rather than being hidden for visual minimalism.
- Dark visual language is consistent and the content width remains readable on a 1440px viewport.

### MUST_FIX

- Status/settings can block while listing old backups because archive manifests are read from compressed files. The UI needs an independent backup loading/error state after the backend list path is fixed.
- Status details expose absolute database and data-directory paths to authenticated clients. Replace them with safe storage labels or availability summaries.
- The active operator DB contains stale root paths, so Reader actions can fail despite library cards showing valid chapter counts. This is a workflow trust issue, not merely an internal migration concern.

### SHOULD_IMPROVE

- Status uses mixed Vietnamese/English labels (`Database`, `Data directory`, `Ready`, `Healthy`, `Online`). Normalize operator-facing language without hiding technical meaning.
- Reader loading should preserve a stable content skeleton; one sequential screenshot showed a mostly empty canvas while the lazy route loaded.
- Library cards are tall and action-heavy. Keep actions, but use progressive disclosure for secondary cover/edit/destructive controls.
- Import onboarding steps are informative but visually dense and run together; improve spacing and semantic list layout before redesigning the workflow.
- The PWA install prompt should be deferrable and should not repeatedly compete with the primary task.

### OPTIONAL_POLISH

- Reduce repeated green status decoration on dense admin pages.
- Clarify empty cover placeholders without making them visually dominant.
- Add a compact status summary at the top of long operational pages.

## Mobile

### KEEP_UNCHANGED

- The persistent bottom navigation makes all primary domains reachable.
- A dedicated prominent Import action is appropriate for the operator workflow.
- The 390px and 360px passes had no measured horizontal document overflow.
- Fixed-control overlap fixes from P1 remain effective in the current screenshots.

### MUST_FIX

- The PWA install prompt can occupy a large part of the lower viewport and compete with the bottom navigation until dismissed. Add durable dismissal/backoff and ensure it never hides task controls.
- Library remains two-column at 390px. Titles, status, and controls become cramped; switch to one-column compact cards below a tested breakpoint.
- Import instruction steps wrap into dense blocks and are hard to scan. Use a vertical step layout with separated title and description.

### SHOULD_IMPROVE

- Several controls remain below the practical 44px touch target noted in P1.
- The bottom navigation uses many unlabeled icons simultaneously. Accessible names exist, but persistent visible labels or a clearer selected-state caption would reduce recognition cost.
- Status cards require extensive scrolling before backup and operational details. Add section shortcuts or collapse secondary metrics.
- Long titles and errors need consistent wrapping with action buttons kept reachable.
- Reader mode, QA, audio, and chapter controls should be tested as separate sheets on a low-height Android viewport.

## Loading, Empty, Error, And Destructive States

- Loading states exist for route lazy loading and major API requests.
- Backup listing currently couples a slow backend operation to settings readiness; this is the clearest misleading loading state.
- Empty states generally identify the domain, but some provide no immediate primary action.
- Safe error rendering is present in tested paths; no hostile HTML execution was reproduced.
- Destructive book/chapter and backup-secret actions retain confirmation requirements in code/tests.

## Accessibility Basics

### Verified

- Measured routes had named buttons and inputs.
- Main views use headings and explicit form labels in core workflows.
- Status is not represented only by color; text labels accompany icons/colors.
- Dialog/drawer components include accessible roles/labels in the inspected code.
- Hostile import/EPUB content is sanitized server-side before rich rendering.

### Gaps

- No formal contrast matrix was produced.
- Keyboard-only traversal and dialog focus return were not exhaustively completed on every panel.
- Reduced-motion behavior is not comprehensively documented or tested.
- Mobile touch-target sizes remain below recommended practical dimensions in multiple controls.
- Reader annotation, selection popover, and nested sheets need a dedicated screen-reader pass.

## Scores

- Desktop UI/UX: `7.5/10`
- Mobile UI/UX: `6.0/10`
- Workflow clarity: `7.5/10`
- Accessibility basics: `6.5/10`

The interface is fit for a technical single operator. A whole-app redesign is not justified. The next UX work should target backup observability, mobile library density, PWA prompt behavior, and Reader control/load stability.
