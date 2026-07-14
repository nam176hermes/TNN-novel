// @ts-expect-error -- Test-only Node built-in; the browser bundle intentionally omits @types/node.
import { readFileSync } from 'node:fs';
// @ts-expect-error -- Test-only Node built-in; the browser bundle intentionally omits @types/node.
import { dirname, resolve, sep } from 'node:path';

const LOCAL_CSS_IMPORT = /^\s*@import\s+(?:url\(\s*)?["']([^"']+\.css)["']\s*\)?(?:\s+[^;]+)?;/gm;

function readStyleFile(path: string, root: string, visited: Set<string>): string[] {
  const resolvedPath = resolve(path);
  if (visited.has(resolvedPath)) {
    return [];
  }

  const allowedPrefix = `${resolve(root)}${sep}`;
  if (resolvedPath !== resolve(root) && !resolvedPath.startsWith(allowedPrefix)) {
    throw new Error(`Style import escapes source root: ${resolvedPath}`);
  }

  visited.add(resolvedPath);
  const source = readFileSync(resolvedPath, 'utf-8');
  const sources = [source];
  const importSource = source.replace(/\/\*[\s\S]*?\*\//g, '');
  for (const match of importSource.matchAll(LOCAL_CSS_IMPORT)) {
    const importedPath = match[1];
    if (!importedPath.startsWith('.')) {
      continue;
    }
    sources.push(...readStyleFile(resolve(dirname(resolvedPath), importedPath), root, visited));
  }
  return sources;
}

export function readStyleSources(entryPath: string): string {
  const resolvedEntry = resolve(entryPath);
  return readStyleFile(resolvedEntry, dirname(resolvedEntry), new Set()).join('\n');
}
