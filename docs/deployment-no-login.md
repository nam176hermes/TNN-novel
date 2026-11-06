# Public access without login

The owner explicitly selected public access after being informed that visitors
receive operator permissions, including book edits/deletion and provider-backed
jobs. The owner confirmed deployment to `novel-tnn.tradingcompanydirect.com` on
2026-10-17. This applies to this deployment; development defaults remain unchanged.

## Release inputs

- Backend source: `9144efc778ea18822586c7ff1df9cecbd6d85725`.
- Base API image: `novel-pipeline-api:glossary-upgrade-20260830-r1`,
  `sha256:db94007569fa29b38aa32927e0ae7ed737b8e934438c3f51a030251e6dfd7e2d`.
- API variant: `novel-pipeline-api:glossary-upgrade-no-login-20261015-r1`,
  `sha256:bafb96bdb7a1d50c0f6a9d43de0311018e21ed3f2da78353d5ae03b5fb360e7c`.
- The variant copies only frontend build output into the base image. Its frontend
  uses the same source commit with `VITE_DISABLE_AUTH=1`,
  `VITE_RELEASE_ID=glossary-upgrade-20260830-r1`, and `VITE_APP_VERSION=0.1.0`.
- The API/worker backend release ID remains unchanged so worker compatibility
  checks retain their meaning. The variant image tag and digest identify the
  changed frontend. The later checkout commits are not part of this release.
- Backend access is enabled by the two explicit flags in
  [the access overlay](../deploy/production/compose.access.no-login-20261017.yaml).

The previous production Compose labels pointed to a deleted worktree. The base
Compose file was recovered byte-for-byte from the source commit above into
`~/.config/novel-tnn/releases/glossary-upgrade-20260830-r1/compose.yaml`.
Its adjacent `compose.release.yaml` preserves the original API and worker image
pins. The external `production.env` remains unchanged and must stay private.

## Apply or restore login

Run from `/home/thenam176/Novel-TNN`. Keep `--project-directory` explicit so the
relative data mount stays bound to the existing production data directory.
Verify there are no queued/running jobs before recreating the API.

```bash
compose_args=(
  --project-directory /home/thenam176/Novel-TNN
  -p novel-tnn-wsl
  --env-file /home/thenam176/.config/novel-tnn/production.env
  -f /home/thenam176/.config/novel-tnn/releases/glossary-upgrade-20260830-r1/compose.yaml
  -f /home/thenam176/.config/novel-tnn/releases/glossary-upgrade-20260830-r1/compose.release.yaml
)
access_overlay=deploy/production/compose.access.no-login-20261017.yaml

# Apply public no-login access, preserving the worker and both data mounts.
docker compose "${compose_args[@]}" -f "$access_overlay" config --quiet
docker compose "${compose_args[@]}" -f "$access_overlay" up -d --no-build --no-deps --force-recreate api

# To restore login, omit the access overlay and return to the original API image.
# Run this only when restoring authenticated access is intended.
# docker compose "${compose_args[@]}" up -d --no-build --no-deps --force-recreate api
```

Verify local/public `/api/ready`, then open a fresh browser session. With public
access enabled, `/api/books` and `/api/auth/me` must return 200 without credentials,
and the application must render without a login form. After restoring login,
those API routes must return 401 without credentials and the login form must show.

Build manifests and retained 2026-10-15 focused test logs are under
`work/operations/no-login-20261015/`. Fresh deployment checks are under
`work/operations/no-login-20261017/`. These local evidence directories are ignored
by Git and contain no production credentials or chapter text.

## Verification on 2026-10-17

- The retained frontend manifest still matched all 49 files from the 2026-10-15
  build. Its nine session tests and the two backend auth tests were retained
  results, not rerun on 2026-10-17.
- Fresh disposable-container checks passed for anonymous API access, a synthetic
  cover asset, the rendered application, and continued blocking of `/docs` and
  `/.env`. The first test volume was 64 MiB, below the existing 100 MiB readiness
  floor; resizing only that disposable volume to 256 MiB resolved its 503.
- Production API and worker are healthy. Local and public readiness return 200;
  API/worker release IDs match. The production mounts and worker container are
  unchanged, and the database still contains six books and 760 chapters.
- Fresh desktop and mobile browser contexts opened the app and Library, then
  reloaded without a login form, access token, or refresh cookie. Neither run
  produced page errors or failed API responses. An existing browser tab loaded
  the old login bundle once; reloading loaded the new bundle without login.
- Translation/provider calls and destructive operations were not exercised.
  TTS continues to report the existing `gpu_unavailable` limitation.

## Desktop UI update on 2026-10-17

The first desktop frontend image was `novel-pipeline-api:desktop-ui-no-login-20261017-r1`
(`sha256:b5bb15c1fcde6cf6c599db6011f918ecc67ebfdf405de1d91af63d9618caa49c`).
It inherits the no-login image above, replacing only the frontend assets. The
frontend was built from `9144efc778ea18822586c7ff1df9cecbd6d85725` with the focused
desktop changes in `web/src/styles/{shell,features,library}.css` backported from
this checkout. The build flags and backend/worker release ID remain unchanged.

After defining `compose_args` and `access_overlay` as above:

```bash
ui_overlay=deploy/production/compose.ui.desktop-20261017.yaml
docker compose "${compose_args[@]}" -f "$access_overlay" -f "$ui_overlay" config --quiet
docker compose "${compose_args[@]}" -f "$access_overlay" -f "$ui_overlay" up -d --no-build --no-deps --force-recreate api

# Roll back the UI while keeping public no-login access:
# docker compose "${compose_args[@]}" -f "$access_overlay" up -d --no-build --no-deps --force-recreate api
```

The desktop patch removes the background image containing duplicate Admin UI,
allows sidebar scrolling, and adapts the Library, Raw list and Workbench to wider
screens. The patch SHA-256 is
`1589a1353a59086ba867e818d90561349fa5a74c465c9423361de3fd45abf5ec`.
Build manifests, test logs and screenshots are retained locally under
`/tmp/novel-tnn-desktop-ui-20261017/` (temporary, not durable release storage).

The checkout's CSS checks and focused desktop/mobile E2E checks pass. On the
production-source candidate, three focused E2E checks pass; the mobile Reader
settings focus check fails identically on the unchanged prior frontend. This
existing keyboard-focus issue is not fixed by the desktop CSS update. No paid
provider calls or production content edits are part of this verification.

After deployment, fresh browser contexts at 1366×768, 1920×1080 and 390×844
passed navigation, search/clear, horizontal-overflow and no-login reload checks.
No application exceptions or failed API/asset responses were observed. Cloudflare
injects an analytics beacon that the existing CSP blocks; this console warning
is recorded separately from application errors. The entry JavaScript and CSS
served locally and publicly match the build hashes. API/worker health, worker
identity, data mounts and the six-book/760-chapter counts were verified unchanged.

## Narrow desktop window correction (r2)

The current frontend image is `novel-pipeline-api:desktop-ui-no-login-20261017-r2`
(`sha256:09872b80d0b292b6117bd3f30df7ab8d8232ae8d10af83575df3f9af583f9f84`).
The same UI overlay and apply command above now select r2. It inherits r1 and
replaces only frontend assets; backend, worker, data and access settings are unchanged.

The owner's screenshot reproduced at 600px on r1: conflicting 560–820px tablet
rules made the sidebar fill the viewport while mobile navigation was also visible.
The first deployment's large-desktop/mobile checks missed this intermediate range.
R2 removes those two obsolete tablet rule blocks and carries the existing mobile
viewport-height fix from this checkout into the production-source frontend.
Only `shell.css` changes between the r1 and r2 frontend sources.

The regression check covers 360, 559, 560, 600, 640, 641, 768, 820 and 821px;
it verifies visible content, one navigation mode and content above the bottom bar.
Five focused checkout E2E tests, four production-candidate E2E tests, 14 CSS tests
and both frontend builds/typechecks pass. The existing Reader focus issue recorded
above is outside this correction.

Evidence is under `/tmp/novel-tnn-narrow-ui-20261017/`. The incremental shell patch
SHA-256 is `8e3811e9612986e7998cae082cb93159303ee3f03d6ee698fd1dc069c7128464`.
For a return specifically to r1, substitute the saved overlay
`~/.config/novel-tnn/releases/glossary-upgrade-20260830-r1/compose.ui.desktop-r1.yaml`
for `ui_overlay` in the apply command. Keep the access overlay to retain no-login use.

Fresh r2 checks on the public site passed at 600×950, 768×900, 390×844 and
1366×768: content placement, navigation, search and anonymous reload. Both HTTP
and HTTPS serve the new entry assets with matching build hashes. API and worker
remain healthy; worker identity, mounts and database counts are unchanged.
