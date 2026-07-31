# Accessibility Audit

This is a practical audit, not a formal WCAG conformance claim.

## Working Well

- No visible unnamed buttons were found on the final audited pages.
- No visible unlabeled inputs were found on the final audited pages.
- Major navigation has names and pressed state.
- Reader controls have accessible names, and destructive actions use text labels.
- Focus-visible styling is defined globally.
- Status is generally represented by text and icon, not color alone.

## Findings

### Keyboard and Touch

- The two fixed-control overlaps were pointer blockers and likely keyboard-order usability problems. Both received narrow CSS fixes.
- The 360 px Reader sample had 22 controls below 44 px in at least one dimension. Mode buttons were 32 px high; several icon controls were 38 px.
- The mobile PWA dismiss control was 35 px high.
- Mobile bottom-nav items measured about 43x44 px, narrowly below the directional target in width.

### Semantics

- Some management pages show `H1` followed by `H3/H4/H5` with no visible `H2`, particularly inside the import workflow. This should be reviewed rather than mechanically renumbered.
- File/radio controls include visually tiny native inputs wrapped by larger labels. Automated geometry alone cannot determine the effective hit target for every wrapped control.

### Dialogs and Motion

- Dialog labels exist in the inspected Reader flows.
- Focus trapping, focus return, screen-reader announcement quality, contrast ratios, and reduced-motion behavior were not fully instrumented and remain unknown.

## Priorities

- P1 usability: increase Reader and PWA action targets to at least 44 px where layout permits.
- P1 screen-reader: add an automated accessibility smoke for login, import, Reader, and destructive dialogs.
- P2 keyboard: explicitly test focus trap/return for TOC, notes, settings, QA, and audiobook confirmation.
- P2 visibility: run a contrast tool against both Reader themes and operational status chips.
