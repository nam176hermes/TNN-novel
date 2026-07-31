# Novel-TNN PWA and offline shell

Novel-TNN is a private single-operator web app that can be installed as a PWA. The PWA is only an installable shell around the existing backend. It does not move provider keys, import, translation, TTS, export, backup, or job execution into the browser.

## Current PWA status

The app ships:

- `web/public/manifest.webmanifest` for browser install metadata.
- `web/public/reader-offline-sw.js` for conservative app-shell caching.
- `web/public/offline.html` for a safe offline fallback.
- `PwaInstallPrompt` for install prompts and manual install guidance.
- Reader-side explicit offline cache controls for selected chapters/books, assets, dictionaries, and available audio.

## What the service worker caches

The service worker may cache:

- `/`
- `/index.html`
- `/offline.html`
- `/manifest.webmanifest`
- PWA icons
- built frontend assets under `/assets/...`
- static non-sensitive browser destinations such as local scripts, styles, fonts, images, and the manifest

The service worker must not blindly cache:

- `/api/...`
- `/covers/...`
- `/book-assets/...`
- `/exports/...`
- `/backup` or `/backups/...`
- `/data/...`
- protected audio streams/downloads
- provider settings
- job logs
- glossary or QA APIs
- backups or exported books
- auth/session endpoints

## Explicit reader offline cache

Reader content is cached only after the operator explicitly chooses a reader cache action.

Available reader actions:

- `Tải chương hiện tại offline`
- `Cache toàn bộ truyện offline`
- `Xóa cache chương hiện tại`
- `Xóa cache offline truyện này`

The explicit reader cache may store selected translated chapter text, source text needed by reader modes, rich chapter assets, reader dictionary packs, cover assets, and audio files that already exist for the selected chapter/book. It does not cache provider keys, refresh tokens, arbitrary API responses, raw job logs, backups, or generated export archives.

Important logout behavior:

- Logging out clears the active server session and protected asset cookie.
- Logging out does not automatically delete reader/audio content that the operator manually cached for offline reading.
- Before handing the device/browser to someone else, use the reader cache controls below or clear browser storage.

## Install instructions

Android Chrome:

1. Open the Novel-TNN domain.
2. Log in if required.
3. Use the in-app `Cài app` prompt when available.
4. If the browser does not show the prompt, open Chrome menu and choose `Add to Home screen` or `Install app`.

Desktop Chrome or Edge:

1. Open the Novel-TNN domain.
2. Use the install icon in the address bar or browser menu.
3. Confirm install.

## Offline behavior

Works offline after a previous visit:

- app shell
- offline fallback page
- reader content and audio that the operator explicitly cached

Requires backend connection:

- login/session refresh
- import
- translation jobs
- TTS generation
- job logs/status streams
- export/download creation
- provider settings/tests
- backup/restore operations

When the browser reports offline status, the app shows a small `Bạn đang offline` banner. It does not claim that private API data is available offline.

## Clearing cached app data

From the reader:

- use `Xóa cache chương hiện tại` for one chapter
- use `Xóa cache offline truyện này` for one book
- the reader menu shows a non-blocking warning that offline cached chapters/audio may remain on the device after logout

From the browser:

1. Open DevTools > Application.
2. Clear service worker storage, Cache Storage, IndexedDB, and localStorage for the Novel-TNN origin.
3. Reload the app.

After logout, the service worker still may serve the static shell, but it must not serve stale private API responses because those responses are not runtime-cached by the service worker. Explicit reader offline content remains a local operator-controlled cache; clear it before handing the browser/device to anyone else.

## Production validation

Run locally:

```bash
npm --prefix web test -- pwaAssets.test.ts serviceWorkerFile.test.ts serviceWorker.test.ts App.test.tsx
npm --prefix web run build
```

After deployment:

1. Open DevTools > Application.
2. Confirm the manifest loads and display mode is `standalone`.
3. Confirm the service worker is active.
4. Go offline and reload a previously visited route.
5. Confirm `/api/*`, `/covers/*`, `/book-assets/*`, `/exports/*`, `/backups/*`, and `/data/*` are not service-worker runtime-cached.
6. Confirm protected audio requires authentication and uses private/no-store headers.

## Future work

- Add a storage quota UI before caching very large books/audio.
- Add an explicit “clear all offline reader data” button.
- Add Playwright offline-mode E2E coverage for a real installed PWA shell.
