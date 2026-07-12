import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const appSource = readFileSync(resolve(__dirname, 'App.tsx'), 'utf-8');

describe('authenticated PWA install prompt visibility', () => {
  it('does not mount the install prompt in Reader', () => {
    expect(appSource).toContain(
      "{activeView !== 'reader' ? <PwaInstallPrompt /> : null}",
    );
  });

  it('retains install prompts outside the authenticated workflow', () => {
    expect(appSource.match(/<PwaInstallPrompt \/>/g)?.length).toBeGreaterThanOrEqual(3);
  });
});
