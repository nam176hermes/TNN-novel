# Accessibility Audit

## Structural scan

The sampled mobile and desktop screens reported headings and landmarks and no unlabeled interactive elements under the harness heuristic. This is not a WCAG conformance result. [Source: browser evidence JSON `scans`]

## A11Y-001: More dialog keyboard behavior

A focused mobile keyboard probe found:

- focus did not move into the More dialog after keyboard activation;
- Escape did not close the dialog;
- tab traversal could reach the body rather than remain within the dialog.

[Source: focused Playwright keyboard probe]

Classification: P1, REPRODUCED.

## A11Y-002: touch targets

Many mobile controls measured below 44 CSS pixels. Sources had up to 58 undersized interactive controls; Reader More options had 25; Reader font settings had nine. Some range and hidden file inputs are false positives, so remediation must target visible controls. [Source: browser evidence JSON]

Classification: P2, REPRODUCED.

## Reduced motion and zoom

A focused probe found no horizontal overflow after a CSS-based 200 percent zoom simulation. Two elements still reported motion duration under reduced-motion emulation. Browser-native zoom, contrast ratios, screen-reader announcements, and complete focus restoration were not fully tested. [Source: focused Playwright accessibility probe]

Verdict: accessibility NO-GO for certification.
