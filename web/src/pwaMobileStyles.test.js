import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const styles = readFileSync(resolve(__dirname, 'styles.css'), 'utf-8');

describe('mobile PWA prompt styles', () => {
  it('keeps the install prompt above the fixed mobile navigation', () => {
    expect(styles).toContain('inset: auto 14px calc(76px + env(safe-area-inset-bottom)) 14px;');
  });

  it('keeps reader chapter navigation from covering the mode switcher', () => {
    expect(styles).toContain('.workflow-shell[data-active-view="reader"] .reader-text-mode-switcher {');
    expect(styles).toContain('top: 124px;');
    expect(styles).toContain('padding-top: 172px;');
    expect(styles).toContain('top: 116px;');
    expect(styles).toContain('padding-top: 164px;');
  });
});
