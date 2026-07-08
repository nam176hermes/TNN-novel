# Android wrapper evaluation

Novel-TNN should remain a server-first web application. Android support should be a companion surface around the existing PWA, not a migration of import, translation, TTS, export, provider settings, backup, or job execution into a native app.

## Current state

- PWA install mode exists through `web/public/manifest.webmanifest`, `web/public/reader-offline-sw.js`, and `docs/pwa-install.md`.
- The service worker caches the app shell and static assets conservatively.
- Private routes such as `/api/*`, `/covers/*`, and `/book-assets/*` are not blindly runtime-cached by the service worker.
- No Android, Gradle, Capacitor, or Bubblewrap project is currently checked into this repo.
- Android packaging still needs deployment-specific values: package name, signing key, production domain, and Digital Asset Links.

## Recommendation

Use a Trusted Web Activity first when an Android package is required.

Do not add a Capacitor wrapper yet. Capacitor is the right later choice only if Novel-TNN needs native bridges such as Android share targets, download manager integration, local file picker/import bridges, push notifications, or deeper OS integration that the PWA cannot provide safely.

Do not scaffold Android in this phase unless the Android toolchain, production domain, signing key, and asset links can be verified in the same change. A generated native project that cannot be built or verified would add maintenance surface without improving safety.

## Trusted Web Activity option

Trusted Web Activity is the preferred first wrapper because it keeps the web app as the source of truth and launches the owned PWA in a fullscreen Android browser context.

### Pros

- Minimal native surface area.
- Uses the existing PWA, routing, auth, service worker, and reader UI.
- Keeps provider keys, translation jobs, TTS jobs, backup, and source fetching on the backend.
- Web deployments update the app experience without rebuilding native logic.
- Good fit for a fullscreen reader and operator dashboard when the PWA is already usable.
- Avoids duplicating Novel-TNN state between Android and backend.

### Cons

- Requires a public HTTPS origin.
- Requires Digital Asset Links verification for the production domain and Android signing certificate.
- If verification fails, the app can fall back to a browser/custom-tab style experience instead of a trusted fullscreen app.
- Native features are limited unless extra Android work is added.
- Play Store packaging, app signing, versioning, and release management still need operational ownership.

### Future TWA scaffold checklist

Prepare these values before creating the wrapper:

- `ANDROID_PACKAGE_NAME`, for example `com.tradingcompanydirect.noveltnn`
- `ANDROID_APP_NAME`, for example `Novel-TNN`
- production `PUBLIC_APP_URL`, for example `https://novel-tnn.tradingcompanydirect.com`
- release signing key and SHA-256 certificate fingerprint
- hosted `/.well-known/assetlinks.json` for the production domain

Recommended build path for a future dedicated Android phase:

```bash
npx @bubblewrap/cli init --manifest https://novel-tnn.tradingcompanydirect.com/manifest.webmanifest
npx @bubblewrap/cli build
```

After generating the project, verify:

```bash
./gradlew assembleRelease
rg -n "API_KEY|SECRET|TOKEN|PASSWORD|PROVIDER|sk-" .
```

The generated Android package must point only to the configured public web origin and must not embed provider keys, admin credentials, refresh tokens, local `.env` values, or backend secrets.

## Capacitor option

Capacitor can wrap a web app in a native project and provide native APIs. It should be treated as a later bridge layer, not the default wrapper.

### Pros

- Can support native share targets for EPUB/TXT files.
- Can provide stronger Android file/download integration.
- Can add push notifications if the backend exposes safe notification events later.
- Gives more control over native app chrome and app-store packaging.
- Useful if the PWA cannot satisfy required Android workflows.

### Cons

- Adds native project dependencies and Android build maintenance.
- Copies the built web bundle into the native project during sync, so stale Android builds can drift from the deployed web app.
- Increases security review surface around WebView settings, native bridges, file access, deep links, and cleartext traffic.
- Makes it easier to accidentally duplicate backend behavior in the client.
- Requires stricter testing for cookie/session behavior, file imports, downloads, and offline caching.

### Capacitor guardrails if used later

- Use HTTPS only for the production backend.
- Do not enable cleartext traffic for production.
- Keep provider keys, job execution, TTS models, source scraping, exports, and backups backend-only.
- Keep native plugins minimal and purpose-specific.
- Validate all inbound shared files with the existing backend upload/import rules.
- Do not add an offline mutation queue for imports, translation, TTS, provider changes, or deletes.
- Run `npm run build` before every native sync so the copied `webDir` is current.

## Security boundaries

Never put these in an Android package:

- provider API keys
- `MOBILE_API_SECRET`
- admin password or refresh tokens
- `.env` values
- source scraping credentials
- backup encryption passphrases
- raw private book content except content the user explicitly cached for offline reading

Android may do:

- open the existing PWA
- log in through the existing backend auth flow
- render the reader fullscreen
- use explicit offline reader cache already implemented by the web app
- play or download already-created audio/export artifacts through authenticated backend routes

Android must not do:

- run import/scraping logic
- run translation jobs
- run local F5-TTS full models
- test or store provider keys
- create backups
- bypass backend auth/session checks
- bypass source policies
- cache private API responses globally

## What stays backend-only

- source policies and source catalog safety checks
- import and scraping
- translation jobs and retries
- TTS generation and audio QA
- MP3/M4B export creation
- provider key storage and provider tests
- operational events and audit logs
- backups, restore drills, and retention
- session creation, refresh rotation, logout, and throttling

## Implementation decision for this phase

Do not add an Android scaffold in Phase 8.

The safe output of this phase is the wrapper evaluation and future implementation checklist. A native scaffold should be created only in a dedicated Android packaging phase after:

1. PWA deployment is validated on the production domain.
2. Android SDK/Gradle/Bubblewrap or Capacitor toolchain is available in the build environment.
3. Package name and app signing are decided.
4. `/.well-known/assetlinks.json` can be hosted and verified.
5. The wrapper build can be produced and scanned for embedded secrets.

## References

- Trusted Web Activity overview: https://developer.android.com/develop/ui/views/layout/webapps/trusted-web-activities
- Trusted Web Activity quick start and Bubblewrap flow: https://developer.android.com/develop/ui/views/layout/webapps/guide-trusted-web-activities-version2
- Capacitor setup and Android project flow: https://capacitorjs.com/docs/getting-started
