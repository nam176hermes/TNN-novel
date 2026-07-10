# UI/UX Audit

## Desktop Findings

### Working Well
- Clear separation between the workflow shell and the translated-library reader
- Navigation is domain-based rather than hidden behind a generic dashboard
- The reader has explicit modes for translation, raw, split, collapsed raw, and QA overlay
- Import has clear multi-mode flows: paste, file, ebook, URL, and catalog
- The UI already includes operational surfaces for jobs, providers, glossary, sources, export, backup, and PWA install

### Must Fix
- The reader route integration test expects a heading `Đọc truyện`, but the current rendered page did not contain that heading
- That suggests a copy / route-heading mismatch, or a regression in the translated-library-to-reader navigation flow

### Should Improve
- `web/src/styles.css` is very large and centralizes too much layout and state styling
- `ReaderView.tsx` is too dense for comfortable editing and future UX iteration
- The sidebar/workspace density is high; the app is functional but visually heavy
- Large modal/drawer surfaces in the reader can be difficult to scan on smaller laptops

### Keep Unchanged
- The operator-facing technical vocabulary is appropriate for this domain app
- The operational pages are grouped in a way that matches the workflow of a single operator
- The reader's multiple modes are justified by the translation/QA workflow and should not be collapsed into a simpler generic reader

## Mobile Findings

### Verified
- The app has explicit mobile panel switching in `AppShell`
- PWA install and network status affordances exist
- The reader includes touch-specific controls and mobile-aware sheets

### Risks
- The reader bundle is large, so mobile parse and first interaction cost are likely higher than ideal
- Fixed/sticky controls in a dense reader are the highest-risk area for overlap and accidental taps
- Import and sources pages likely need more attention on narrow screens because they are data-dense workflows

### Recommendation
- Treat the reader and import surfaces as the highest-value mobile UX audit targets
- Do not redesign the whole app for mobile; instead, tighten navigation and spacing where touch targets and vertical space matter most

## Accessibility Findings
- Semantic headings and aria labels are present in many core surfaces
- Dialogs and panels generally use explicit roles and labels
- The project still needs a focused keyboard/focus pass on the reader, import dialogs, and destructive flows
- No formal WCAG claim should be made from the current evidence

## Overall Assessment
- The UI is operational and domain-appropriate
- It is not minimalist, but that is acceptable for a private operator console
- The main UX risk is complexity concentration in the reader, import, and source hub
