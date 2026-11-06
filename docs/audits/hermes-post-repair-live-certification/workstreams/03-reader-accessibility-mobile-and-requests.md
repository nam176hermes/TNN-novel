# Future workstream 3: Reader accessibility, mobile safe area, and request ownership

## Objective

Repair the Reader settings focus lifecycle, fixed-navigation padding, login install-prompt overlap, and remaining duplicate Reader requests without changing content contracts.

## Included issues

- `A11Y-SETTINGS-003`
- `UX-MOB-007`
- `PERF-READER-002`
- `UX-LOGIN-007`

## Excluded scope

No Reader redesign, typography rebrand, new feature, database migration, source-adapter change, or PWA cache rewrite.

## Dependencies

Existing More-dialog focus implementation, Reader request ownership tests, required viewport fixtures, and delayed-response harness.

## Implementation phases

1. Add failing tests for settings focus, safe-area geometry, login prompt geometry, and exact request counts.
2. Reuse the More-dialog focus pattern for settings.
3. Centralize bottom safe-area padding.
4. Deduplicate translation ownership and coalesce progress sync safely.
5. Run delayed stale-response and history navigation tests.
6. Return HANDOFF before deployment.

## Test gates

Frontend unit tests, E2E at all five viewports, keyboard focus lifecycle, touch targets, screenshot geometry, delayed responses, typecheck, build, full verification.

## Approval gates

No approval for local code and tests. Deployment, external screenshot publication, merge, or release needs explicit approval.

## Rollback

Revert each bounded commit independently. Preserve Reader API and persisted progress schema.

## Commit strategy

Separate commits for focus, mobile geometry, and request ownership.

## Definition of Done

All Reader dialogs pass focus entry, containment, Escape, and restoration; no visible content falls under fixed navigation; two chapter changes issue exactly two reads per resource; no stale content appears; all gates pass.
