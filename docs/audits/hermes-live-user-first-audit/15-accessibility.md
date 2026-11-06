# Accessibility

Audit date: 2026-07-24

Release: `ws7-production-20260723-r1` at `5dd78353bbff3244af03eda054084b323b63d3c2`.

## Fresh live checks

At `390x844`:

- main and navigation landmarks were present;
- mobile primary navigation had an accessible label;
- all 14 visible controls met the 44 by 44 pixel policy;
- the More dialog received focus;
- focus remained inside the dialog for 20 Tab presses;
- Escape closed the dialog;
- focus returned to the More trigger.

[Source] fresh Playwright keyboard and DOM audit on 2026-07-24

Playwright E2E also passed mobile touch-target and feature-page checks at 390 px and 360 px. [Source] `web/e2e/novel-tnn.spec.ts`; fresh E2E output

## Visual limitations

Secondary gray text and dense provider or glossary table text may be difficult for low-vision users. Fixed bottom controls can visually cover the lowest copy at short viewports. No formal contrast measurement was completed.

## Not tested

- NVDA, JAWS, VoiceOver, or TalkBack.
- Browser zoom at 200 percent as a formal certification run.
- Reduced-motion and high-contrast operating-system modes.

## Verdict

Accessibility: **GO_WITH_LIMITATIONS**. Keyboard and touch foundations are strong; formal assistive-technology and contrast certification remain open.
