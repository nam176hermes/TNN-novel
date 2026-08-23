import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { readStyleSources } from './test/readStyleSources';

const styles = readStyleSources(resolve(__dirname, 'styles.css'));

describe('mobile PWA prompt styles', () => {
  it('keeps the install prompt above the fixed mobile navigation with 44px mobile actions', () => {
    expect(styles).toContain('inset: auto 14px calc(var(--mobile-nav-height) + 16px + env(safe-area-inset-bottom)) 14px;');
    expect(styles).toContain('flex-wrap: wrap;');
    expect(styles).toContain('min-height: 44px;');
    expect(styles).toContain('margin: 18px auto calc(16px + env(safe-area-inset-bottom));');
  });

  it('keeps reader chapter navigation from covering the mode switcher', () => {
    expect(styles).toContain('.workflow-shell[data-active-view="reader"] .reader-text-mode-switcher {');
    expect(styles).toContain('top: 124px;');
    expect(styles).toContain('padding-top: 172px;');
    expect(styles).toContain('padding-bottom: calc(176px + env(safe-area-inset-bottom));');
    expect(styles).toContain('top: 116px;');
    expect(styles).toContain('padding-top: 164px;');
  });

  it('centers reader empty states on mobile without bottom bar overlap', () => {
    expect(styles).toContain('.reader-empty-state {');
    expect(styles).toContain('min-height: min(360px, calc(100dvh - 220px));');
    expect(styles).toContain('padding-bottom: calc(110px + env(safe-area-inset-bottom));');
  });

  it('turns dense mobile management tables into readable cards', () => {
    expect(styles).toContain('@media (max-width: 559px) {');
    expect(styles).toContain('.providers-management-table thead,');
    expect(styles).toContain('.glossary-management-table thead,');
    expect(styles).toContain('.providers-management-table th:nth-child(1)::before { content: "Provider"; }');
    expect(styles).toContain('.glossary-management-table td:nth-child(6)::before { content: "Bằng chứng"; }');
    expect(styles).toContain('.glossary-management-table td:nth-child(7)::before { content: "Thao tác"; }');
    expect(styles).toContain('.provider-key-form input,\n  .provider-key-form button,\n  .provider-row-test {\n    min-height: 44px;');
  });

  it('turns mobile job history tables into labeled cards', () => {
    expect(styles).toContain('.job-history-table thead,');
    expect(styles).toContain('.job-attempts-table tbody,');
    expect(styles).toContain('.job-history-table td:nth-child(10)::before { content: "Thông báo"; }');
    expect(styles).toContain('.job-attempts-table td:nth-child(7)::before { content: "Lỗi"; }');
  });

  it('keeps dense mobile sheets and card grids clear of the bottom navigation', () => {
    expect(styles).toContain('scroll-padding-bottom: calc(var(--mobile-nav-height) + env(safe-area-inset-bottom) + 32px);');
    expect(styles).toContain('padding-bottom: calc(var(--mobile-nav-height) + env(safe-area-inset-bottom));');
    expect(styles).toContain('max-height: calc(100dvh - var(--mobile-nav-height) - env(safe-area-inset-bottom) - 24px);');
    expect(styles).toContain('padding-bottom: calc(var(--mobile-nav-height) + env(safe-area-inset-bottom) + 24px);');
    expect(styles).toContain('.export-format-grid {\n    margin-bottom: calc(var(--mobile-nav-height) + env(safe-area-inset-bottom) + 24px);');
  });
});
