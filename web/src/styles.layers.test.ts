// @ts-expect-error -- Vitest-only Node built-in; the browser bundle intentionally omits @types/node.
import { readFileSync } from 'node:fs';
// @ts-expect-error -- Vitest-only Node built-in; the browser bundle intentionally omits @types/node.
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { readStyleSources } from './test/readStyleSources';

declare const __dirname: string;

const entryPath = resolve(__dirname, 'styles.css');
const entry = readFileSync(entryPath, 'utf-8');
const componentStyles = readFileSync(resolve(__dirname, 'styles/components.css'), 'utf-8');
const featureStyles = readFileSync(resolve(__dirname, 'styles/features.css'), 'utf-8');
const shellStyles = readFileSync(resolve(__dirname, 'styles/shell.css'), 'utf-8');
const expectedImports = [
  './styles/tokens.css',
  './styles/base.css',
  './styles/shell.css',
  './styles/components.css',
  './styles/features.css',
  './styles/utilities.css',
];

describe('ordered stylesheet layers', () => {
  it('declares the fixed cascade order before importing each source exactly once', () => {
    expect(entry.startsWith('@layer tokens, base, shell, components, features, utilities, overrides;\n')).toBe(true);

    for (const importedSource of expectedImports) {
      expect(entry.split(`@import "${importedSource}";`).length - 1).toBe(1);
    }
  });

  it('keeps the entry as an import manifest without feature declarations', () => {
    const manifestLines = entry
      .split('\n')
      .map((line: string) => line.trim())
      .filter(Boolean);

    expect(manifestLines).toEqual([
      '@layer tokens, base, shell, components, features, utilities, overrides;',
      ...expectedImports.map((source) => `@import "${source}";`),
    ]);
  });

  it('wraps every imported source in its approved layer', () => {
    for (const importedSource of expectedImports) {
      const layer = importedSource.match(/\/([^/]+)\.css$/)?.[1];
      expect(layer).toBeTruthy();
      const source = readFileSync(resolve(__dirname, importedSource), 'utf-8').trim();
      expect(source.startsWith(`@layer ${layer} {\n`)).toBe(true);
      expect(source.endsWith('}')).toBe(true);
      expect(source).not.toContain('@import');
    }
  });

  it('reads concrete declarations from explicitly imported local sources', () => {
    const sources = readStyleSources(entryPath);
    expect(sources).toContain('--accent: #078b5b;');
    expect(sources).toContain('.workflow-shell[data-active-view="reader"] .reader-text-mode-switcher {');
    expect(sources).toContain('max-height: min(58dvh, calc(100dvh - 240px), 620px);');
  });

  it('keeps the login CTA override after the generic action owner', () => {
    const genericMinimum = componentStyles.indexOf('min-height: 38px;');
    const loginOverride = componentStyles.indexOf('.login-panel .primary-action {');

    expect(genericMinimum).toBeGreaterThan(-1);
    expect(loginOverride).toBeGreaterThan(genericMinimum);
    expect(componentStyles.slice(loginOverride, loginOverride + 120)).toContain('min-height: 48px;');
    expect(shellStyles).not.toContain('.login-panel .primary-action {');
  });

  it('keeps desktop provider table sizing with the feature owner after its base sizing', () => {
    const baseTable = featureStyles.indexOf('.providers-management-table {\n  font-size: 12px;\n  min-width: 800px;');
    const desktopTable = featureStyles.indexOf(
      '.workflow-management-view .providers-management-table {\n    font-size: 11.5px;\n    min-width: 660px;',
    );

    expect(baseTable).toBeGreaterThan(-1);
    expect(desktopTable).toBeGreaterThan(baseTable);
    expect(featureStyles.lastIndexOf('@media (min-width: 821px) {', desktopTable)).toBeGreaterThan(baseTable);
    expect(shellStyles).not.toContain('.workflow-management-view .providers-management-table {');
  });
});
