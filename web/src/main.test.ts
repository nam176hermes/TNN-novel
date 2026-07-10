import { describe, expect, it } from 'vitest';
import mainSource from './main.tsx?raw';

describe('frontend entrypoint', () => {
  it('registers the reader offline service worker after mounting the app', () => {
    expect(mainSource).toContain("import { registerReaderOfflineServiceWorker } from './state/serviceWorker';");
    expect(mainSource).toContain('registerReaderOfflineServiceWorker();');
  });
});
