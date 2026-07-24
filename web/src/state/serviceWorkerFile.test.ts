import { describe, expect, it } from 'vitest';
import workerSource from '../../public/reader-offline-sw.js?raw';

describe('reader offline service worker file', () => {
  it('ships a public service worker for the Vite build', () => {
    expect(workerSource.trim().length).toBeGreaterThan(0);
  });

  it('caches the app shell and static assets without caching authenticated API responses', () => {
    expect(workerSource).toContain("const SHELL_CACHE = 'reader-offline-shell-v6'");
    expect(workerSource).toContain("const RUNTIME_CACHE = 'reader-offline-runtime-v6'");
    expect(workerSource).not.toContain("const SHELL_CACHE = 'reader-offline-shell-v5'");
    expect(workerSource).toContain("'/index.html'");
    expect(workerSource).toContain("url.pathname.startsWith('/assets/')");
    expect(workerSource).toContain('cacheAppShell()');
    expect(workerSource).toContain("request.mode === 'navigate'");
    expect(workerSource).toContain("'/api/'");
    expect(workerSource).toMatch(/event\.respondWith\(/);
    expect(workerSource).toMatch(/caches\.open\(/);
  });

  it('serves newly installed app-shell assets before the runtime cache is warm', () => {
    expect(workerSource).toContain('const shellCache = await caches.open(SHELL_CACHE)');
    expect(workerSource).toContain("await shellCache.match(request, { ignoreVary: true })");
    expect(workerSource).toMatch(/runtimeCache\.match\(request\)[\s\S]*shellCache\.match\(request, \{ ignoreVary: true \}\)/);
  });

  it('verifies app-shell readiness through an explicit service-worker message', () => {
    expect(workerSource).toContain("const VERIFY_APP_SHELL_MESSAGE = 'VERIFY_READER_OFFLINE_APP_SHELL'");
    expect(workerSource).toContain("self.addEventListener('message'");
    expect(workerSource).toContain('verifyAppShellReady(event.data.assetUrls)');
    expect(workerSource).toContain('responsePort.postMessage');
    expect(workerSource).toContain('allowedAppShellAssetUrls');
    expect(workerSource).toContain("sameOrigin(url) && url.pathname.startsWith('/assets/')");
    expect(workerSource).toContain('if (!await cache.match(url)) await cache.add(url)');
  });

  it('uses a friendly offline fallback for navigations when the app shell is unavailable', () => {
    expect(workerSource).toContain("'/offline.html'");
    expect(workerSource).toContain("caches.match('/offline.html')");
  });

  it('does not blindly runtime-cache private app content routes', () => {
    expect(workerSource).toContain('PRIVATE_PATH_PREFIXES');
    for (const privatePrefix of [
      "'/api/'",
      "'/covers/'",
      "'/book-assets/'",
      "'/exports/'",
      "'/backup'",
      "'/backups/'",
      "'/data/'",
    ]) {
      expect(workerSource).toContain(privatePrefix);
    }
    expect(workerSource).not.toContain("if (url.pathname.startsWith('/covers/')) return true;");
    expect(workerSource).not.toContain("if (url.pathname.startsWith('/book-assets/')) return true;");
  });
});
