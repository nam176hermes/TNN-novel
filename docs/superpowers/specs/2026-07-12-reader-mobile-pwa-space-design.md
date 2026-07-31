# Reader Mobile PWA Space Design

## Status

Approved option: **A**.

## Problem

On narrow mobile viewports, the global PWA installation prompt appears above the Reader's fixed bottom controls. The two independent fixed surfaces consume a large portion of the viewport even though the Reader controls are the primary interaction surface.

This is an existing mobile UX issue. It is separate from the P0A artifact-path/runtime recovery.

## Scope

P0A_FIX_APPLIED:

- Do not render the PWA installation prompt while the authenticated workflow is in the Reader view.
- Keep the installation prompt unchanged on Library, Status, and the other non-Reader views.
- Keep the Reader's fixed controls inside the mobile safe area and preserve enough content padding that controls do not cover chapter text.
- Preserve the existing dismiss/install behavior and local-storage key.
- Add focused tests for prompt visibility by active view and for the Reader mobile spacing contract.

RECOMMENDATION_ONLY:

- A future compact install chip or dedicated application settings entry could provide installation access from inside Reader without restoring the large overlay.

## Interaction Design

The authenticated application owns the active workflow view. It conditionally mounts `PwaInstallPrompt` only when `activeView !== 'reader'`. No new global state or persisted preference is introduced.

When the user leaves Reader, the prompt may appear again if the browser offers installation and the user has not dismissed it. When the user enters Reader, the prompt is removed immediately so the text and Reader controls retain the viewport.

The existing Reader bottom bar remains fixed. Its safe-area padding remains in force, and the Reader content bottom padding must be at least the height of the bottom controls plus the safe-area inset.

## Error And Edge Cases

- Login and session-restoration screens retain the current prompt behavior.
- Public review mode retains the current prompt behavior because it does not expose the authenticated Reader workflow state.
- Standalone PWA mode and dismissed prompts remain hidden through existing component logic.
- Network/offline status remains independent and is not changed by this design.

## Verification

- Component/integration test: prompt is present on a non-Reader workflow and absent in Reader.
- Source/CSS regression test: Reader content and fixed controls retain safe-area-aware spacing.
- Mobile browser smoke: chapter text is visible, Reader controls remain usable, and the PWA prompt does not cover the Reader.
- Non-Reader browser smoke: installation prompt behavior remains available.

## Exclusions

- No Reader redesign.
- No PWA installation-flow redesign.
- No changes to artifact metadata, content, authentication, or API contracts.
