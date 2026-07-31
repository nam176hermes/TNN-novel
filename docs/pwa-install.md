# Novel-TNN PWA install mode

See also: [PWA and offline shell](pwa-offline.md) for the current cache policy, offline fallback behavior, and validation checklist.

Novel-TNN can be installed as a browser PWA. This gives the current web app a standalone window on Android Chrome, desktop Chrome, and Edge. It is not a native Android app and it does not move import, translation, TTS, export, provider keys, or background jobs into the client.

## What gets cached

The service worker uses a conservative cache policy:

- App shell: `/`, `/index.html`, `/offline.html`, manifest, icons.
- Built static assets: `/assets/...`.
- Public browser-managed static destinations such as scripts, styles, fonts, images, and the manifest.

The service worker does not blindly cache private content routes:

- `/api/...`
- `/covers/...`
- `/book-assets/...`
- `/exports/...`
- `/backup` or `/backups/...`
- `/data/...`

Reader chapter/audio/book assets are only cached through the existing explicit reader offline controls, such as `Cache toàn bộ truyện offline`. Do not configure Cloudflare or another proxy to cache `/api/*`, `/covers/*`, `/book-assets/*`, `/exports/*`, `/backups/*`, or `/data/*`.

## Reader and audio offline cache policy

Offline reader cache is user-initiated only. The app does not automatically cache every book and it does not run import, translation, TTS, or export jobs offline.

Reader controls:

- `Tải chương hiện tại offline`: caches the selected translated chapter text, rich chapter assets where present, chapter dictionary pack, and the chapter audio file if audio already exists.
- `Xóa cache chương hiện tại`: removes the selected chapter's cached text, rich assets, audio, and manifest entry.
- `Cache toàn bộ truyện offline`: caches translated chapters for the selected book, including available rich assets, audio, dictionary metadata, and cover asset where available.
- `Xóa cache offline truyện này`: removes cached reader data for the selected book.

Cache status shown in the reader:

- whether the current chapter is cached
- whether the next chapter is cached
- local storage estimate
- cached asset count and size
- cached audio count and size
- offline manifest coverage and resource summary

Storage limits:

- Chapter text cache is bounded by the reader cache entry limit in the web client.
- Rich assets and audio are stored in browser IndexedDB when available, with a localStorage fallback for smaller records.
- Browser quota still applies. If storage is full, live reading and streaming remain available when the backend is reachable.

The offline cache must never contain provider keys, admin credentials, refresh tokens, raw job logs, provider prompts, or arbitrary API responses. It only stores reader content that the operator explicitly requested for offline use.

## Install on Android Chrome

1. Open the Novel-TNN public domain in Chrome.
2. Log in if needed.
3. When Chrome shows the install prompt, tap `Cài app`.
4. If no prompt appears, open Chrome menu and choose `Add to Home screen` or `Install app`.
5. Launch Novel-TNN from the home screen.

## Install on desktop Chrome or Edge

1. Open the Novel-TNN public domain.
2. Use the install icon in the address bar, or use browser menu `Install Novel-TNN`.
3. Confirm install.
4. Launch Novel-TNN from the installed app shortcut.

## Offline behavior

Works offline:

- Static app shell can open after the app has loaded once.
- A friendly offline fallback page is available if the shell cannot be loaded.
- Reader content and chapter audio already cached with the explicit reader offline controls can be read or played from that cache.

Still requires backend connection:

- Login/session refresh.
- Import and scraping.
- Translation jobs and job status streams.
- TTS/audio generation.
- Exports and downloads that have not already been created.
- Provider settings and provider tests.
- Backup/restore operations.

## Validation

Run:

```bash
npm --prefix web test -- pwaAssets.test.ts serviceWorkerFile.test.ts App.test.tsx
npm --prefix web run build
```

After deployment, open DevTools > Application and verify:

- Manifest loads without errors.
- Service worker is active.
- `Display mode` is standalone after install.
- `/api/*`, `/covers/*`, `/book-assets/*`, `/exports/*`, `/backups/*`, and `/data/*` are not listed as service-worker runtime-cached entries.
