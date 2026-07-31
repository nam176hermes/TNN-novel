import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const appSource = readFileSync(resolve(__dirname, 'App.tsx'), 'utf-8');

describe('authenticated PWA install prompt visibility', () => {
  it('does not mount the install prompt in Reader', () => {
    const readerCase = appSource.slice(appSource.indexOf("case 'reader':"), appSource.indexOf("case 'import':"));
    expect(readerCase).not.toContain('<PwaInstallPrompt />');
  });

  it('places the authenticated install card inside Status instead of the global shell', () => {
    const statusCase = appSource.slice(appSource.indexOf("case 'status':"), appSource.indexOf("case 'export':"));
    expect(statusCase).toContain('<PwaInstallPrompt />');
    expect(appSource.match(/<PwaInstallPrompt \/>/g)?.length).toBeGreaterThanOrEqual(3);
  });
});
