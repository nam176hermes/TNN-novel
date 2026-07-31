// @ts-expect-error -- Vitest-only Node built-ins; the browser bundle intentionally omits @types/node.
import { mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
// @ts-expect-error -- Vitest-only Node built-in; the browser bundle intentionally omits @types/node.
import { tmpdir } from 'node:os';
// @ts-expect-error -- Vitest-only Node built-in; the browser bundle intentionally omits @types/node.
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { readStyleSources } from './readStyleSources';

const fixtureRoots: string[] = [];

function fixtureRoot(): string {
  const root = mkdtempSync(join(tmpdir(), 'novel-tnn-styles-'));
  fixtureRoots.push(root);
  return root;
}

afterEach(() => {
  for (const root of fixtureRoots.splice(0)) {
    rmSync(root, { force: true, recursive: true });
  }
});

describe('readStyleSources', () => {
  it('follows recursive local imports while ignoring comments and non-local imports', () => {
    const root = fixtureRoot();
    mkdirSync(join(root, 'nested'));
    writeFileSync(join(root, 'entry.css'), [
      '@import "./nested/one.css";',
      '/* @import "./ignored.css"; */',
      '@import "https://example.test/remote.css";',
      '.entry-marker { color: red; }',
    ].join('\n'));
    writeFileSync(join(root, 'nested/one.css'), '@import "../two.css";\n.one-marker { color: green; }');
    writeFileSync(join(root, 'two.css'), '.two-marker { color: blue; }');
    writeFileSync(join(root, 'ignored.css'), '.ignored-marker { color: pink; }');

    const sources = readStyleSources(join(root, 'entry.css'));
    expect(sources).toContain('.entry-marker');
    expect(sources).toContain('.one-marker');
    expect(sources).toContain('.two-marker');
    expect(sources).not.toContain('.ignored-marker');
    expect(sources.match(/\.one-marker/g)).toHaveLength(1);
  });

  it('deduplicates cycles and symlink aliases by canonical file identity', () => {
    const root = fixtureRoot();
    writeFileSync(join(root, 'entry.css'), '@import "./one.css";\n@import "./one-alias.css";');
    writeFileSync(join(root, 'one.css'), '@import "./entry.css";\n.one-marker { color: green; }');
    symlinkSync(join(root, 'one.css'), join(root, 'one-alias.css'));

    const sources = readStyleSources(join(root, 'entry.css'));
    expect(sources.match(/\.one-marker/g)).toHaveLength(1);
  });

  it('rejects lexical traversal outside the source root', () => {
    const parent = fixtureRoot();
    const root = join(parent, 'styles');
    mkdirSync(root);
    writeFileSync(join(parent, 'outside.css'), '.outside { color: red; }');
    writeFileSync(join(root, 'entry.css'), '@import "../outside.css";');

    expect(() => readStyleSources(join(root, 'entry.css'))).toThrow('Style import escapes source root');
  });

  it('rejects a symlink import that resolves outside the source root', () => {
    const parent = fixtureRoot();
    const root = join(parent, 'styles');
    mkdirSync(root);
    writeFileSync(join(parent, 'outside.css'), '.outside { color: red; }');
    symlinkSync(join(parent, 'outside.css'), join(root, 'escape.css'));
    writeFileSync(join(root, 'entry.css'), '@import "./escape.css";');

    expect(() => readStyleSources(join(root, 'entry.css'))).toThrow('Style import escapes source root');
  });
});
