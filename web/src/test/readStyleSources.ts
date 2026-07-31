// @ts-expect-error -- Test-only Node built-in; the browser bundle intentionally omits @types/node.
import { readFileSync, realpathSync } from 'node:fs';
// @ts-expect-error -- Test-only Node built-in; the browser bundle intentionally omits @types/node.
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';

const LOCAL_CSS_IMPORT = /^\s*@import\s+(?:url\(\s*)?["']([^"']+\.css)["']\s*\)?(?:\s+[^;]+)?;/gm;

function readStyleFile(path: string, root: string, visited: Set<string>): string[] {
  const requestedPath = resolve(path);
  const canonicalPath = realpathSync(requestedPath);
  const relativePath = relative(root, canonicalPath);
  if (relativePath === '..' || relativePath.startsWith(`..${sep}`) || isAbsolute(relativePath)) {
    throw new Error(`Style import escapes source root: ${canonicalPath}`);
  }

  if (visited.has(canonicalPath)) {
    return [];
  }

  visited.add(canonicalPath);
  const source = readFileSync(canonicalPath, 'utf-8');
  const sources = [source];
  const importSource = source.replace(/\/\*[\s\S]*?\*\//g, '');
  for (const match of importSource.matchAll(LOCAL_CSS_IMPORT)) {
    const importedPath = match[1];
    if (!importedPath.startsWith('.')) {
      continue;
    }
    sources.push(...readStyleFile(resolve(dirname(requestedPath), importedPath), root, visited));
  }
  return sources;
}

export function readStyleSources(entryPath: string): string {
  const resolvedEntry = resolve(entryPath);
  const canonicalRoot = realpathSync(dirname(resolvedEntry));
  return readStyleFile(resolvedEntry, canonicalRoot, new Set()).join('\n');
}
