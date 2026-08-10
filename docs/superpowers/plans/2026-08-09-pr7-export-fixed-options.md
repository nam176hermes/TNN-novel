# PR7 Export Fixed Options Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace four fake Export controls with truthful, non-interactive fixed-default descriptions.

**Architecture:** Keep the existing export API and all real controls unchanged. Render fixed behavior as a semantic description list and remove visual control cues from the component and feature CSS.

**Tech Stack:** React 19, TypeScript, Vitest/Testing Library, CSS, Playwright.

## Global Constraints

- Book export requests remain `{ format }` only.
- Chapter range, annotations, cover, and TOC must not look focusable or clickable.
- Standalone annotation export APIs remain unchanged.
- Every remaining visible control must perform a real action.

---

### Task 1: Specify truthful fixed defaults

**Files:**
- Modify: `web/src/components/ExportView.test.tsx`
- Modify: `web/src/components/ExportView.tsx`
- Modify: `web/src/styles/features.css`

**Interfaces:**
- Consumes: `activeBook.total` and existing export callbacks
- Produces: non-interactive `dl.export-fixed-options` content

- [ ] **Step 1: Write the failing component test**

Add a test that renders book 1 and asserts:

```tsx
expect(screen.getByRole('heading', { name: 'Thiết lập cố định' })).toBeInTheDocument();
expect(screen.getByText('Tất cả chương đã dịch')).toBeInTheDocument();
expect(screen.getByText('Không kèm chú thích trong file sách')).toBeInTheDocument();
expect(screen.getByText('Không kèm bìa sách')).toBeInTheDocument();
expect(screen.getByText('Theo mặc định của định dạng đã chọn')).toBeInTheDocument();
expect(screen.queryByRole('button', { name: /Phạm vi chương|Bao gồm chú thích|Bìa sách|Mục lục/ })).not.toBeInTheDocument();
expect(document.querySelector('.toggle-switch')).not.toBeInTheDocument();
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `npm --prefix web test -- ExportView.test.tsx`

Expected: FAIL because the fixed-default heading/copy does not exist.

- [ ] **Step 3: Replace fake option cards with a description list**

Remove unused `ChevronRight`, `Image`, `List`, and `StickyNote` imports. Replace the option grid with:

```tsx
<section aria-labelledby="export-options-title" className="panel export-options-panel">
  <div className="panel-header">
    <div>
      <p className="section-label">Không thể thay đổi</p>
      <h3 id="export-options-title">Thiết lập cố định</h3>
    </div>
  </div>
  <dl className="export-fixed-options">
    <div><dt>Phạm vi chương</dt><dd>Tất cả chương đã dịch</dd></div>
    <div><dt>Chú thích</dt><dd>Không kèm chú thích trong file sách</dd></div>
    <div><dt>Bìa sách</dt><dd>Không kèm bìa sách</dd></div>
    <div><dt>Mục lục</dt><dd>Theo mặc định của định dạng đã chọn</dd></div>
  </dl>
</section>
```

- [ ] **Step 4: Replace interactive-looking CSS**

Rename the option-grid/card rules to `.export-fixed-options` and `.export-fixed-options > div`; remove cursor/hover/control styling and use neutral borders/background. Preserve the existing one-column mobile layout.

- [ ] **Step 5: Run the focused test and verify success**

Run: `npm --prefix web test -- ExportView.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit the UI slice**

```bash
git add web/src/components/ExportView.tsx web/src/components/ExportView.test.tsx web/src/styles/features.css
git add -f docs/superpowers/specs/2026-08-09-pr7-export-fixed-options-design.md docs/superpowers/plans/2026-08-09-pr7-export-fixed-options.md
git commit -m "fix: make export defaults non-interactive"
```

### Task 2: Guard the real export contract

**Files:**
- Modify: `web/e2e/novel-tnn.spec.ts`
- Review only: `web/src/api/client.test.ts`

**Interfaces:**
- Consumes: existing `ApiClient.exportBook(bookId, format)`
- Produces: regression evidence that visible format controls affect `{ format }`

- [ ] **Step 1: Verify the existing API request assertion**

Confirm the existing export client test asserts the request body remains exactly:

```ts
expect(fetcher).toHaveBeenCalledWith(
  'http://test/api/books/1/exports',
  expect.objectContaining({ body: JSON.stringify({ format: 'txt' }) }),
);
```

- [ ] **Step 2: Extend Export E2E semantics**

Before clicking `Bắt đầu xuất`, assert `Thiết lập cố định` is visible and the four fixed rows are not buttons, checkboxes, or switches. Keep the existing real download assertion.

- [ ] **Step 3: Run PR7 validation**

Run:

```bash
npm --prefix web test -- ExportView.test.tsx api/client.test.ts
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web run test:e2e -- --grep "exports a translated book"
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 4: Commit contract coverage**

```bash
git add web/e2e/novel-tnn.spec.ts
git commit -m "test: guard fixed export request contract"
```
