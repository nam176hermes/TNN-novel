const SHELL_CACHE = 'reader-offline-shell-v5';
const RUNTIME_CACHE = 'reader-offline-runtime-v5';
const CACHE_PREFIX = 'reader-offline-';
const APP_SHELL_URLS = [
  '/',
  '/index.html',
  '/offline.html',
  '/manifest.webmanifest',
  '/pwa-icon-192.png',
  '/pwa-icon-512.png',
  '/pwa-maskable-512.png',
];
const STATIC_DESTINATIONS = new Set(['font', 'image', 'manifest', 'script', 'style']);
const PRIVATE_PATH_PREFIXES = [
  '/api/',
  '/covers/',
  '/book-assets/',
  '/exports/',
  '/backup',
  '/backups/',
  '/data/',
];

async function cacheAppShell() {
  const cache = await caches.open(SHELL_CACHE);
  await cache.addAll(APP_SHELL_URLS);

  const cachedIndex = await cache.match('/index.html');
  if (!cachedIndex) return;
  const html = await cachedIndex.text();
  const assetUrls = new Set();
  const attributePattern = /(?:src|href)=["']([^"']+)["']/g;
  for (const match of html.matchAll(attributePattern)) {
    const url = new URL(match[1], self.location.origin);
    if (sameOrigin(url) && url.pathname.startsWith('/assets/')) assetUrls.add(url.href);
  }
  await Promise.all(Array.from(assetUrls, (url) => cache.add(url)));
}

self.addEventListener('install', (event) => {
  event.waitUntil(cacheAppShell().then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key.startsWith(CACHE_PREFIX) && key !== SHELL_CACHE && key !== RUNTIME_CACHE)
          .map((key) => caches.delete(key)),
      ))
      .then(() => self.clients.claim()),
  );
});

function sameOrigin(url) {
  return url.origin === self.location.origin;
}

function isPrivateAppPath(url) {
  return PRIVATE_PATH_PREFIXES.some((prefix) => url.pathname === prefix || url.pathname.startsWith(prefix));
}

function isStaticAssetRequest(request, url) {
  if (request.method !== 'GET') return false;
  if (!sameOrigin(url)) return false;
  if (isPrivateAppPath(url)) return false;
  if (url.pathname.startsWith('/assets/')) return true;
  if (APP_SHELL_URLS.includes(url.pathname)) return true;
  return STATIC_DESTINATIONS.has(request.destination);
}

async function networkFirstNavigation(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(SHELL_CACHE);
      await cache.put('/index.html', response.clone());
    }
    return response;
  } catch {
    const cachedIndex = await caches.match('/index.html');
    const cachedRoot = await caches.match('/');
    const cachedOffline = await caches.match('/offline.html');
    return cachedIndex || cachedRoot || cachedOffline || Response.error();
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);
  const networkResponse = fetch(request)
    .then((response) => {
      if (response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  return cached || await networkResponse || Response.error();
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (!sameOrigin(url)) return;
  if (isPrivateAppPath(url)) return;

  if (request.mode === 'navigate') {
    event.respondWith(networkFirstNavigation(request));
    return;
  }

  if (isStaticAssetRequest(request, url)) {
    event.respondWith(staleWhileRevalidate(request));
  }
});
