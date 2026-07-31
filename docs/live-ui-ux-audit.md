# Live UI/UX Audit

## Desktop

### KEEP_UNCHANGED

- The dark operator-focused visual system is coherent and appropriate for long sessions.
- Desktop navigation is explicit, stable, and exposes operational status without hiding primary workflows.
- Reader typography and content width are readable.
- Loading, empty, and operational panels generally use clear Vietnamese labels.

### SHOULD_IMPROVE

- Library cards are information-dense and repeat progress in several forms.
- Reader places chapter navigation, five modes, audio status, and PWA promotion above text, delaying content visually.
- Status exposes extensive technical detail. This is useful for the single operator, but secondary diagnostics should be collapsible.
- The global PWA prompt overlays content until dismissed.

## Mobile

### MUST_FIX

- Fixed PWA prompt blocked the Import CTA. `LIVE_AUDIT_FIX_APPLIED` moved it above the mobile bar.
- Reader chapter controls blocked the QA mode row. `LIVE_AUDIT_FIX_APPLIED` separated the rows and increased content padding.
- Raw/split/Raw gon are disabled in the actual App workflow despite source text availability. This remains `RECOMMENDATION_ONLY` because it requires a data-contract change and integration tests.

### SHOULD_IMPROVE

- The two-column library grid is too compressed at 390 px: titles, statistics, and actions compete for width. Use one column below a measured breakpoint or redesign cards for compact mobile semantics.
- Import wizard step text runs together and creates a very tall page. Use a compact progress summary and reveal detail for the active step.
- Reader controls still occupy a large portion of a 740-844 px viewport; PWA promotion obscures reading content even though it no longer blocks controls.
- Several Reader controls are 32-38 px high, below a practical 44 px touch target.
- Mobile status is very long and includes local filesystem diagnostics. Keep those available, but collapse them under an operator diagnostics disclosure.

### OPTIONAL_POLISH

- Reduce repeated technical English/Vietnamese mixing in import and status copy.
- Reduce duplicated card progress labels and decorative empty space.

Screenshots for login, workbench, library, Reader, import, jobs, sources, glossary, providers, status, and export are under `output/live-audit-2026-07-10/screenshots/`.
