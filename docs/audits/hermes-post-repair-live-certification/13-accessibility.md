# Accessibility


Audit date: 2026-07-25

Release under audit: `upgrade-b-production-20260725-r1`

Source commit reported by production: `3a781fa3cd48398dd298466118d8c1acc4d291f6`

## Automated and browser evidence

Visible sampled controls met the touch-target policy and had accessible names. The only sub-policy item in broader scans was a hidden file input, which is excluded from visible target scoring. No horizontal overflow appeared at required widths. [Source: evidence/browser-summary.json] [Source: evidence/test-summary.json]

## Reader More dialog

The More dialog passed in all five viewports:

- focus entered the dialog;
- 24 sampled Tab positions stayed inside;
- Escape closed the dialog;
- focus returned to the trigger.

This verifies the previous `A11Y-001` repair. [Source: evidence/browser-summary.json]

## Reader settings dialog

The settings dialog failed in all five viewports:

- initial focus remained outside the dialog;
- early Tab positions escaped containment;
- focus did not return to the trigger after close.

Escape dismissal worked. Touch users can still operate the sheet, so this is P2 rather than a material private-use blocker. [Source: evidence/browser-summary.json]

## Mobile safe area

At 360x740, the lower Jobs card enters the fixed bottom-navigation region. The page remains scrollable, but lowest visible content can be obscured. [Source: evidence/screenshots/mobile-360x740-jobs-redacted.png]

## Not certified

- Full WCAG conformance.
- Measured contrast inventory.
- Complete screen-reader order.
- All routes at 200 percent zoom.
- Reduced-motion behavior for every lazy-loaded component.
- Virtual-row recycling with a real screen reader.

## Verdict

**6.8/10** and **GO_WITH_LIMITATIONS**. Repair the settings focus lifecycle and bottom safe-area padding before the next certification.
