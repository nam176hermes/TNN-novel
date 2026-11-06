// @ts-expect-error -- Vitest-only Node built-in; the browser bundle intentionally omits @types/node.
import { readdirSync, readFileSync } from 'node:fs';
// @ts-expect-error -- Vitest-only Node built-in; the browser bundle intentionally omits @types/node.
import { basename, resolve } from 'node:path';
import postcss, { type Rule } from 'postcss';
import { describe, expect, it } from 'vitest';

import { readStyleSources } from './test/readStyleSources';

declare const __dirname: string;

const entryPath = resolve(__dirname, 'styles.css');
const entry = readFileSync(entryPath, 'utf-8');
const componentStyles = readFileSync(resolve(__dirname, 'styles/components.css'), 'utf-8');
const featureStyles = readFileSync(resolve(__dirname, 'styles/features.css'), 'utf-8');
const importStyles = readFileSync(resolve(__dirname, 'styles/import.css'), 'utf-8');
const operationsStyles = readFileSync(resolve(__dirname, 'styles/operations.css'), 'utf-8');
const readerStyles = readFileSync(resolve(__dirname, 'styles/reader.css'), 'utf-8');
const shellStyles = readFileSync(resolve(__dirname, 'styles/shell.css'), 'utf-8');
const expectedImports = [
  './styles/tokens.css',
  './styles/base.css',
  './styles/shell.css',
  './styles/components.css',
  './styles/features.css',
  './styles/reader.css',
  './styles/library.css',
  './styles/import.css',
  './styles/operations.css',
  './styles/utilities.css',
];

type FeatureOwner = 'reader.css' | 'library.css' | 'import.css' | 'operations.css';

const featureOwners: Record<FeatureOwner, RegExp> = {
  'reader.css': /\.reader-/,
  'library.css': /(?:\.library-|\.translated-librar(?:y|ies)-|\.translated-books?-|\.book-card)/,
  'import.css': /(?:\.import-|\.ebook-|\.paste-status-|\.file-status-panel|\.url-import-|\.source-file-|\.catalog-import-|\.wizard-|\.danger-confirmation)/,
  'operations.css': /(?:\.status-(?:settings|overview|runtime|performance|detail|header)-|\.backup-|\.jobs?-|\.failed-job-|\.tts-job-|\.tts-chunk-|\.stage-timing-|\.auto-refresh-|\.sparkline)/,
};

const sharedStatusSelectors = [
  '.status-error',
  '.status-success',
  '.status-pill',
  '.status-chip',
  '.status-chip-success',
  '.status-chip-warning',
  '.status-chip-danger',
  '.status-chip-muted',
  '.status-spinner',
];

function selectorsFor(css: string): Array<{ selector: string; inResponsiveContext: boolean }> {
  const selectors: Array<{ selector: string; inResponsiveContext: boolean }> = [];
  postcss.parse(css).walkRules((rule: Rule) => {
    type CssAncestor = { name?: string; parent?: CssAncestor; type: string };
    let parent = rule.parent as unknown as CssAncestor | undefined;
    let inResponsiveContext = false;
    while (parent) {
      if (parent.type === 'atrule' && ['media', 'supports', 'container'].includes(parent.name ?? '')) {
        inResponsiveContext = true;
        break;
      }
      parent = parent.parent;
    }
    for (const selector of rule.selectors) {
      selectors.push({ selector, inResponsiveContext });
    }
  });
  return selectors;
}

function ownersForSelector(selector: string): FeatureOwner[] {
  return (Object.entries(featureOwners) as Array<[FeatureOwner, RegExp]>)
    .filter(([, pattern]) => pattern.test(selector))
    .map(([owner]) => owner);
}

function ownershipViolations(sources: Record<string, string>): string[] {
  const violations: string[] = [];
  const selectorFiles = new Map<string, Set<string>>();

  for (const [filename, css] of Object.entries(sources)) {
    for (const { selector } of selectorsFor(css)) {
      const owners = ownersForSelector(selector);
      for (const owner of owners) {
        if (filename !== owner) {
          violations.push(`${selector} belongs to ${owner}, found in ${filename}`);
        }
        const files = selectorFiles.get(`${owner}\0${selector}`) ?? new Set<string>();
        files.add(filename);
        selectorFiles.set(`${owner}\0${selector}`, files);
      }
    }
  }

  for (const [key, files] of selectorFiles) {
    if (files.size > 1) {
      const [, selector] = key.split('\0');
      violations.push(`${selector} appears across ${[...files].sort().join(', ')}`);
    }
  }
  return violations;
}

function computeSimpleClassCascade(classNames: string[]): Record<string, string> {
  type Winner = { layer: number; order: number; specificity: number; value: string };
  const winners = new Map<string, Winner>();
  const layerOrder = new Map([
    ['tokens', 0],
    ['base', 1],
    ['shell', 2],
    ['components', 3],
    ['features', 4],
    ['utilities', 5],
    ['overrides', 6],
  ]);
  let order = 0;

  for (const importedSource of expectedImports) {
    const css = readFileSync(resolve(__dirname, importedSource), 'utf-8');
    const sourceName = importedSource.match(/\/([^/]+)\.css$/)?.[1] ?? '';
    const layerName = ['reader', 'library', 'import', 'operations'].includes(sourceName)
      ? 'features'
      : sourceName;
    const layer = layerOrder.get(layerName) ?? -1;
    postcss.parse(css).walkRules((rule: Rule) => {
      type CssAncestor = { name?: string; parent?: CssAncestor; type: string };
      let parent = rule.parent as unknown as CssAncestor | undefined;
      while (parent && parent.type !== 'root') {
        if (parent.type === 'atrule' && ['media', 'supports', 'container'].includes(parent.name ?? '')) return;
        parent = parent.parent;
      }
      for (const selector of rule.selectors) {
        if (!/^\.[a-z0-9_-]+(?:\.[a-z0-9_-]+)*$/i.test(selector)) continue;
        const requiredClasses = [...selector.matchAll(/\.([a-z0-9_-]+)/gi)].map((match) => match[1]);
        if (!requiredClasses.every((className) => classNames.includes(className))) continue;
        const specificity = requiredClasses.length;
        for (const node of rule.nodes ?? []) {
          if (node.type !== 'decl') continue;
          order += 1;
          const current = winners.get(node.prop);
          const candidate = { layer, order, specificity, value: node.value };
          if (
            !current
            || candidate.layer > current.layer
            || (candidate.layer === current.layer && candidate.specificity > current.specificity)
            || (
              candidate.layer === current.layer
              && candidate.specificity === current.specificity
              && candidate.order > current.order
            )
          ) {
            winners.set(node.prop, candidate);
          }
        }
      }
    });
  }

  return Object.fromEntries([...winners].map(([property, winner]) => [property, winner.value]));
}

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
      const sourceName = importedSource.match(/\/([^/]+)\.css$/)?.[1];
      expect(sourceName).toBeTruthy();
      const layer = ['reader', 'library', 'import', 'operations'].includes(sourceName ?? '')
        ? 'features'
        : sourceName;
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

  it('does not place the reference image with baked-in Admin controls behind real UI', () => {
    expect(featureStyles).not.toContain('sidebar-scenery.png');
    expect(shellStyles).not.toContain('sidebar-scenery.png');
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

  it('parses mixed comma groups independently and rejects cross-file feature ownership', () => {
    expect(selectorsFor('@layer features { .reader-demo, .import-demo:is(.a, .b) { display: block; } }'))
      .toEqual([
        { selector: '.reader-demo', inResponsiveContext: false },
        { selector: '.import-demo:is(.a, .b)', inResponsiveContext: false },
      ]);

    const violations = ownershipViolations({
      'reader.css': '@layer features { .reader-demo { display: block; } .import-demo { display: block; } }',
      'features.css': '@layer features { .reader-demo { color: red; } }',
    });
    expect(violations).toContain('.import-demo belongs to import.css, found in reader.css');
    expect(violations).toContain('.reader-demo belongs to reader.css, found in features.css');
    expect(violations).toContain('.reader-demo appears across features.css, reader.css');
  });

  it('gives every known feature selector exactly one authoritative owner', () => {
    const stylesDir = resolve(__dirname, 'styles');
    const sources = Object.fromEntries(
      readdirSync(stylesDir)
        .filter((filename: string) => filename.endsWith('.css'))
        .map((filename: string) => [basename(filename), readFileSync(resolve(stylesDir, filename), 'utf-8')]),
    );

    expect(ownershipViolations(sources)).toEqual([]);
  });

  it('keeps generic status primitives shared instead of assigning them to operations', () => {
    expect(ownersForSelector('.status-error')).toEqual([]);
    expect(ownersForSelector('.status-settings-view')).toEqual(['operations.css']);
    const operationSelectors = selectorsFor(operationsStyles).map(({ selector }) => selector);
    for (const selector of sharedStatusSelectors) {
      expect(operationSelectors, selector).not.toContain(selector);
    }
    expect(featureStyles).toContain('.glossary-filter-tabs .status-chip-success {');
    expect(featureStyles).toContain('.raw-chapter-row .status-pill {');
    expect(computeSimpleClassCascade(['status-error'])).toMatchObject({
      'font-size': '13px',
      'font-weight': '750',
      'line-height': '1.4',
    });
    expect(computeSimpleClassCascade(['status-pill', 'status-translated'])).toMatchObject({
      background: 'var(--success-bg)',
      'border-color': 'var(--success-border)',
      color: 'var(--accent-strong)',
    });
  });

  it('preserves the Import file-preview composite cascade', () => {
    expect(importStyles).toContain('.paste-status-panel {');
    expect(importStyles).toContain('.file-status-panel {');
    expect(computeSimpleClassCascade(['import-preview', 'paste-status-panel', 'file-status-panel']))
      .toMatchObject({
        'max-height': 'none',
        overflow: 'visible',
        padding: '18px',
      });
  });

  it('preserves Reader audio-error typography across shared status styles', () => {
    expect(readerStyles).toContain('.reader-export-status {');
    expect(computeSimpleClassCascade(['reader-export-status', 'status-error'])).toMatchObject({
      'font-size': '12px',
      'font-weight': '760',
      'line-height': '1.35',
    });
  });

  it('colocates base and responsive rules in every feature owner', () => {
    for (const owner of Object.keys(featureOwners) as FeatureOwner[]) {
      const css = readFileSync(resolve(__dirname, 'styles', owner), 'utf-8');
      const ownedRules = selectorsFor(css).filter(({ selector }) => ownersForSelector(selector).includes(owner));
      expect(ownedRules.some(({ inResponsiveContext }) => !inResponsiveContext), `${owner} base rules`).toBe(true);
      expect(ownedRules.some(({ inResponsiveContext }) => inResponsiveContext), `${owner} responsive rules`).toBe(true);
    }
  });

  it('does not introduce a global responsive override tail', () => {
    expect(expectedImports.some((source) => /(?:mobile|responsive|override)/i.test(source))).toBe(false);
    expect(entry).not.toContain('./styles/overrides.css');
  });
});
