import { describe, expect, it } from 'vitest';
import workerSource from '../../public/reader-offline-sw.js?raw';

describe('reader offline service worker file', () => {
  it('ships a public service worker for the Vite build', () => {
    expect(workerSource.trim().length).toBeGreaterThan(0);
  });

  it('caches the app shell and static assets without caching authenticated API responses', () => {
    expect(workerSource).toContain("const SHELL_CACHE = 'reader-offline-shell-v5'");
    expect(workerSource).toContain("const RUNTIME_CACHE = 'reader-offline-runtime-v5'");
    expect(workerSource).not.toContain("const SHELL_CACHE = 'reader-offline-shell-v4'");
    expect(workerSource).toContain("'/index.html'");
    expect(workerSource).toContain("url.pathname.startsWith('/assets/')");
    expect(workerSource).toContain('cacheAppShell()');
    expect(workerSource).toContain("request.mode === 'navigate'");
    expect(workerSource).toContain("'/api/'");
    expect(workerSource).toMatch(/event\.respondWith\(/);
    expect(workerSource).toMatch(/caches\.open\(/);
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
