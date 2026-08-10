# PR6 Mobile Raw Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing Raw backlog reachable from the mobile More sheet and verify the 360/390/412 responsive contract.

**Architecture:** Reuse `WorkflowShell.openMobileView('raw')`; do not add a route or alter the five-item mobile navigation. Cover wiring with a component test and cover actual geometry/overflow with the existing mocked Playwright application.

**Tech Stack:** React 19, TypeScript, Vitest/Testing Library, Playwright, CSS.

## Global Constraints

- Keep the mobile bottom navigation at exactly five items.
- The visible Raw entry must be a semantic button with a minimum 44px hit area.
- The authenticated shell and Raw page must not overflow horizontally at widths 360, 390, and 412.
- Do not change Raw backlog behavior.

---

### Task 1: Wire Raw into mobile More

**Files:**
- Modify: `web/src/components/WorkflowShell.tsx`
- Test: `web/src/components/WorkflowShell.test.tsx`

**Interfaces:**
- Consumes: `openMobileView(view: WorkflowView): void`
- Produces: a More-sheet button named `Raw chưa dịch` that calls `onViewChange('raw')`

- [ ] **Step 1: Write the failing component test**

Extend the mobile navigation test before its Import click:

```tsx
await userEvent.click(within(mobileNav).getByRole('button', { name: 'Thêm' }));
let moreSheet = screen.getByRole('dialog', { name: 'Thêm' });
await userEvent.click(within(moreSheet).getByRole('button', { name: 'Raw chưa dịch' }));
expect(onViewChange).toHaveBeenCalledWith('raw');
expect(screen.queryByRole('dialog', { name: 'Thêm' })).not.toBeInTheDocument();
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `npm --prefix web test -- WorkflowShell.test.tsx`

Expected: FAIL because the More sheet has no `Raw chưa dịch` button.

- [ ] **Step 3: Add the semantic More entry**

Import `FileText` from Lucide and add this first button under `Quản lý`:

```tsx
<button onClick={() => openMobileView('raw')} type="button">
  <FileText aria-hidden="true" />Raw chưa dịch
</button>
```

- [ ] **Step 4: Run the focused test and verify success**

Run: `npm --prefix web test -- WorkflowShell.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit the component slice**

```bash
git add web/src/components/WorkflowShell.tsx web/src/components/WorkflowShell.test.tsx
git add -f docs/superpowers/specs/2026-08-09-pr6-mobile-raw-design.md docs/superpowers/plans/2026-08-09-pr6-mobile-raw.md
git commit -m "fix: restore mobile access to raw backlog"
```

### Task 2: Prove mobile geometry and navigation

**Files:**
- Modify: `web/e2e/novel-tnn.spec.ts`

**Interfaces:**
- Consumes: `authenticatedPage`, `expectVisibleMobileTouchTargets`, `expectNoHorizontalOverflow`
- Produces: a viewport-matrix regression test for Raw navigation

- [ ] **Step 1: Write the failing Playwright regression**

```ts
test('mobile More opens Raw without overflow at 360, 390, and 412 pixels', async ({ page }) => {
  const state: MockState = { imported: false, translated: true, translateRequests: [] };
  await page.setViewportSize({ width: 390, height: 844 });
  await authenticatedPage(page, state);

  const mobileNav = page.getByRole('navigation', { name: 'Điều hướng chính trên di động' });
  const more = mobileNav.getByRole('button', { name: 'Thêm' });
  await more.click();
  const raw = page.getByRole('dialog', { name: 'Thêm' }).getByRole('button', { name: 'Raw chưa dịch' });
  await expect(raw).toBeVisible();
  await expect(raw).toHaveCSS('min-height', '44px');
  await raw.click();
  await expect(page.getByRole('heading', { name: 'Raw chưa dịch' })).toBeVisible();

  for (const viewport of [
    { width: 360, height: 740 },
    { width: 390, height: 844 },
    { width: 412, height: 915 },
  ]) {
    await page.setViewportSize(viewport);
    await expectVisibleMobileTouchTargets(page, `Raw at ${viewport.width}px`);
    await expectNoHorizontalOverflow(page);
  }
});
```

- [ ] **Step 2: Run the regression and verify success after Task 1**

Run: `npm --prefix web run test:e2e -- --grep "mobile More opens Raw"`

Expected: PASS on all three viewport widths.

- [ ] **Step 3: Run PR6 validation**

Run:

```bash
npm --prefix web test -- WorkflowShell.test.tsx RawBacklogView.test.tsx
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web run test:e2e -- --grep "mobile More opens Raw"
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 4: Commit E2E coverage**

```bash
git add web/e2e/novel-tnn.spec.ts
git commit -m "test: cover mobile raw navigation viewports"
```
