# Reader Mobile PWA Space Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the PWA installation prompt available outside Reader while reclaiming the mobile Reader viewport and preserving safe-area-aware fixed controls.

**Architecture:** The authenticated `App` already owns `activeView`, so it will conditionally mount the existing `PwaInstallPrompt` only outside the Reader workflow. Reader CSS will explicitly include the bottom safe-area inset in its content padding; no new state, storage key, or PWA installation behavior is introduced.

**Tech Stack:** React 18, TypeScript, Vitest, Testing Library, CSS, Playwright browser smoke.

## Global Constraints

- Do not redesign Reader or the PWA installation flow.
- Keep the prompt unchanged on Library, Status, login, session restoration, and public review mode.
- Preserve `novel-pwa-install-dismissed-v1` and the existing install/dismiss behavior.
- Preserve fixed Reader controls and ensure they do not cover chapter text on narrow mobile viewports.
- Do not modify artifact metadata, content, authentication, or API contracts.
- Do not add dependencies.

---

## File Structure

- `web/src/App.tsx`: owns authenticated workflow view selection and conditionally mounts the existing install prompt.
- `web/src/AppPwaVisibility.test.js`: source-level regression contract for the authenticated conditional and unchanged non-workflow prompt surfaces.
- `web/src/styles.css`: makes Reader content bottom padding explicitly safe-area-aware.
- `web/src/pwaMobileStyles.test.js`: verifies the mobile Reader spacing contract without depending on a browser's safe-area implementation.

### Task 1: Hide The Install Prompt In Authenticated Reader

**Files:**
- Create: `web/src/AppPwaVisibility.test.js`
- Modify: `web/src/App.tsx:1978-1986`

**Interfaces:**
- Consumes: `activeView: WorkflowView` already owned by `AuthenticatedApp`.
- Produces: authenticated render expression `activeView !== 'reader' ? <PwaInstallPrompt /> : null`.

- [ ] **Step 1: Write the failing source contract**

```ts
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
```

- [ ] **Step 2: Run the test and verify RED**

Run: `npm --prefix web test -- src/AppPwaVisibility.test.js`

Expected: one failure because `App.tsx` still unconditionally mounts `<PwaInstallPrompt />` beside `WorkflowShell`.

- [ ] **Step 3: Implement the authenticated Reader conditional**

Replace only the prompt in the final authenticated return block:

```tsx
return (
  <>
    {activeView !== 'reader' ? <PwaInstallPrompt /> : null}
    <PwaNetworkStatus />
    <WorkflowShell
```

Do not alter the prompt in login, session-restoration, or public-review returns.

- [ ] **Step 4: Run the focused test and existing App tests**

Run: `npm --prefix web test -- src/AppPwaVisibility.test.js src/App.test.tsx src/App.integration.test.tsx`

Expected: all tests pass.

- [ ] **Step 5: Review the focused diff**

Run: `git diff -- web/src/App.tsx web/src/AppPwaVisibility.test.js`

Expected: one authenticated render conditional and one focused regression file; no PWA component behavior change.

### Task 2: Make Reader Bottom Spacing Safe-Area-Aware

**Files:**
- Modify: `web/src/styles.css:11708-11734`
- Modify: `web/src/pwaMobileStyles.test.js:6-21`

**Interfaces:**
- Consumes: CSS environment variable `env(safe-area-inset-bottom)` and the existing 176px Reader mobile content clearance.
- Produces: `padding-bottom: calc(176px + env(safe-area-inset-bottom));` for `.reader-immersive-main`.

- [ ] **Step 1: Extend the failing CSS contract**

Add this assertion to the existing Reader navigation test:

```js
expect(styles).toContain('padding-bottom: calc(176px + env(safe-area-inset-bottom));');
```

- [ ] **Step 2: Run the test and verify RED**

Run: `npm --prefix web test -- src/pwaMobileStyles.test.js`

Expected: failure because the current value is `padding-bottom: 176px;`.

- [ ] **Step 3: Implement minimal safe-area spacing**

In the `@media (max-width: 720px)` Reader rule, use:

```css
.workflow-shell[data-active-view="reader"] .reader-immersive-main {
  padding-top: 172px;
  padding-bottom: calc(176px + env(safe-area-inset-bottom));
}
```

Keep `.reader-bottom-bar` safe-area padding unchanged.

- [ ] **Step 4: Run focused frontend tests**

Run: `npm --prefix web test -- src/pwaMobileStyles.test.js src/AppPwaVisibility.test.js src/App.test.tsx src/App.integration.test.tsx src/components/ReaderView.test.tsx`

Expected: all tests pass.

- [ ] **Step 5: Run frontend typecheck and production build**

Run: `scripts/lint.sh && npm --prefix web run build`

Expected: TypeScript/lint checks and Vite production build pass.

### Task 3: Verify The Mobile And Non-Reader Browser Behavior

**Files:**
- No source changes.

**Interfaces:**
- Consumes: the locally served production frontend and authenticated operator session.
- Produces: browser evidence that Reader is unobstructed and non-Reader install behavior remains available.

- [ ] **Step 1: Start the production-mode local service**

Run: `scripts/start-cloudflare.sh`

Expected: API readiness and public/static frontend checks succeed without invoking translation or TTS providers.

- [ ] **Step 2: Run the mobile Reader smoke**

Use a 390x844 browser viewport, authenticate with the existing local operator flow, open Library, open a representative book and chapter, then open Reader.

Expected:

- the region named `Cài đặt Novel-TNN như app` is absent in Reader;
- chapter text is non-empty;
- fixed Reader controls remain visible and usable;
- the last text block can scroll above the fixed bottom bar;
- the document has no horizontal overflow.

- [ ] **Step 3: Run the non-Reader prompt smoke**

Navigate from Reader back to Library or Status without dismissing the prompt.

Expected: the install prompt can appear again when the browser offers installation; no absolute filesystem path is rendered.

- [ ] **Step 4: Run focused browser/network checks**

Expected: no failed Reader, cover, or audio application request; no old-root value or absolute data path appears in browser-visible responses.

### Task 4: Integrate With The P0A Recovery Commit

**Files:**
- Modify: `app/mobile_api/routers/health.py` (already prepared runtime responsiveness fix)
- Modify: `tests/test_mobile_api_system_status.py` (already prepared regression test)
- Modify: `web/public/reader-offline-sw.js` (already prepared cache-version bump)
- Modify: `web/src/state/serviceWorker.ts` (already prepared registration-version bump)
- Modify: `web/src/state/serviceWorker.test.ts` (already prepared regression test)
- Modify: `web/src/state/serviceWorkerFile.test.ts` (already prepared regression test)
- Add: `web/src/AppPwaVisibility.test.js`
- Modify: `web/src/App.tsx`
- Modify: `web/src/styles.css`
- Modify: `web/src/pwaMobileStyles.test.js`

**Interfaces:**
- Consumes: the verified runtime/status and service-worker fixes already present in the worktree.
- Produces: one reviewable code commit before operator-data maintenance.

- [ ] **Step 1: Run focused backend and frontend suites**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest tests/test_mobile_api_system_status.py -q
npm --prefix web test -- src/state/serviceWorker.test.ts src/state/serviceWorkerFile.test.ts src/AppPwaVisibility.test.js src/pwaMobileStyles.test.js src/App.test.tsx src/App.integration.test.tsx src/components/StatusSettingsView.test.tsx src/components/ReaderView.test.tsx
```

Expected: all focused tests pass.

- [ ] **Step 2: Run repository validation**

Run: `scripts/verify.sh && git diff --check`

Expected: verify script and whitespace validation pass; no paid provider is invoked.

- [ ] **Step 3: Inspect scope and secrets**

Run: `git status --short && git diff --stat && git diff --check`

Expected: only the listed code/test files are pending; `.env`, operator DB, backup archives, reports with private absolute paths, and credentials are not staged.

- [ ] **Step 4: Commit the code and tests**

```bash
git add app/mobile_api/routers/health.py tests/test_mobile_api_system_status.py \
  web/public/reader-offline-sw.js web/src/state/serviceWorker.ts \
  web/src/state/serviceWorker.test.ts web/src/state/serviceWorkerFile.test.ts \
  web/src/App.tsx web/src/AppPwaVisibility.test.js web/src/styles.css \
  web/src/pwaMobileStyles.test.js
git commit -m "fix: restore stable P0A runtime behavior"
```

Expected: one focused code commit; ignored `.env` remains unstaged.

### Task 5: Execute A Fresh P0A Maintenance Migration

**Files:**
- Operator data only: `data/pipeline.db` metadata fields approved by `scripts/migrate_artifact_paths.py`.
- Protected evidence only: a fresh backup archive, manifest, direct DB rollback copy, dry-run/rehearsal/apply reports.
- Ignored runtime config: `.env` legacy-root fallback, removed only after successful live apply and smoke tests.

**Interfaces:**
- Consumes: `scripts/backup-local.sh`, `scripts/migrate_artifact_paths.py`, exact old root `/home/thenam176/novel_pipeline`, configured current root `$REPO_ROOT/data`, and a newly computed operator DB SHA-256.
- Produces: zero approved old-root matches, a fresh rollback artifact, idempotent live metadata, and a post-migration runtime that no longer requires `ARTIFACT_LEGACY_ROOT`.

- [ ] **Step 1: Enter maintenance mode before capturing the new baseline**

Run:

```bash
scripts/stop-local.sh
pgrep -af 'uvicorn|vite|novel' || true
```

Expected: no Novel-TNN API/job worker remains able to write `data/pipeline.db`.

- [ ] **Step 2: Verify disk and capture a fresh database identity**

Run:

```bash
export PROTECTED_RUN_DIR="$HOME/.local/state/novel-tnn/p0a-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 700 "$PROTECTED_RUN_DIR"
df -h "$PWD" "$PWD/data" "$PWD/backups"
export MAINTENANCE_DB_SHA="$(sha256sum data/pipeline.db | awk '{print $1}')"
printf '%s  %s\n' "$MAINTENANCE_DB_SHA" data/pipeline.db
stat -c '%s %y' data/pipeline.db
```

Expected: enough free space for one full backup plus rehearsal/rollback copies; record this new hash and never reuse the previous P0A apply hash/report.

- [ ] **Step 3: Create a fresh backup without secrets or source-DB event writes**

Run:

```bash
export FRESH_BACKUP="$(BACKUP_RECORD_EVENT=0 BACKUP_CHECKPOINT=0 INCLUDE_ENV=0 \
BACKUP_INCLUDE_AUDIO=1 BACKUP_INCLUDE_EXPORTS=1 \
scripts/backup-local.sh)"
export FRESH_BACKUP_ID="$(basename "$FRESH_BACKUP")"
test -s "$FRESH_BACKUP"
test -s "$FRESH_BACKUP.manifest.json"
```

Expected: a new non-zero protected archive and manifest. Do not continue if either is missing or checksum validation fails.

- [ ] **Step 4: Verify the backup and perform a restore drill**

Run:

```bash
sha256sum "$FRESH_BACKUP" > "$PROTECTED_RUN_DIR/backup.sha256"
.venv/bin/python - "$FRESH_BACKUP.manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(json.dumps({
    "created_at": manifest.get("created_at"),
    "backup_format_version": manifest.get("backup_format_version"),
    "included_modules": manifest.get("included_modules"),
    "excluded_modules": manifest.get("excluded_modules"),
    "secrets_included": manifest.get("secrets_included"),
    "checksums": manifest.get("checksums"),
}, indent=2))
PY
.venv/bin/python scripts/ops.py restore-drill "$FRESH_BACKUP"
```

Expected: restore drill succeeds, manifest version/time/modules are recorded, and no `.env` or secret is included.

- [ ] **Step 5: Create the direct rollback DB copy**

```bash
install -m 600 data/pipeline.db "$PROTECTED_RUN_DIR/pipeline.pre-p0a.db"
sha256sum data/pipeline.db "$PROTECTED_RUN_DIR/pipeline.pre-p0a.db"
```

Expected: the two hashes match exactly.

- [ ] **Step 6: Generate a fresh live dry-run report**

```bash
.venv/bin/python scripts/migrate_artifact_paths.py \
  --db-path data/pipeline.db \
  --old-root /home/thenam176/novel_pipeline \
  --new-root "$PWD/data" \
  --report-dir "$PROTECTED_RUN_DIR/live-dry-run" \
  --verify-files
```

Expected: 12,151 remappable paths, zero unresolved paths, zero containment failures, and a report database hash equal to the maintenance baseline hash.

- [ ] **Step 7: Rehearse against a separate copied DB**

```bash
install -m 600 data/pipeline.db "$PROTECTED_RUN_DIR/pipeline.rehearsal.db"
REHEARSAL_SHA="$(sha256sum "$PROTECTED_RUN_DIR/pipeline.rehearsal.db" | awk '{print $1}')"
.venv/bin/python scripts/migrate_artifact_paths.py \
  --db-path "$PROTECTED_RUN_DIR/pipeline.rehearsal.db" \
  --old-root /home/thenam176/novel_pipeline \
  --new-root "$PWD/data" \
  --report-dir "$PROTECTED_RUN_DIR/rehearsal-first" \
  --verify-files --apply \
  --backup-confirmation "verified:$FRESH_BACKUP_ID" \
  --expected-db-sha256 "$REHEARSAL_SHA"
```

Expected: 12,151 rows updated in one transaction, integrity `ok`, zero foreign-key violations, and a protected rollback mapping is written.

- [ ] **Step 8: Prove rehearsal idempotency and mutation scope**

Run:

```bash
export REHEARSAL_POST_SHA="$(sha256sum "$PROTECTED_RUN_DIR/pipeline.rehearsal.db" | awk '{print $1}')"
.venv/bin/python scripts/migrate_artifact_paths.py \
  --db-path "$PROTECTED_RUN_DIR/pipeline.rehearsal.db" \
  --old-root /home/thenam176/novel_pipeline \
  --new-root "$PWD/data" \
  --report-dir "$PROTECTED_RUN_DIR/rehearsal-second" \
  --verify-files --apply \
  --backup-confirmation "verified:$FRESH_BACKUP_ID" \
  --expected-db-sha256 "$REHEARSAL_POST_SHA"
sqlite3 "$PROTECTED_RUN_DIR/pipeline.rehearsal.db" 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
```

Expected: zero remappable paths, zero rows updated, integrity `ok`, zero foreign-key violations, unchanged table row counts, and only approved path columns differ from the pre-rehearsal copy.

- [ ] **Step 9: Recheck the live DB hash immediately before apply**

Run: `sha256sum data/pipeline.db`

Expected: exact match with the fresh maintenance dry-run hash. Abort and repeat Steps 2-8 if it differs.

- [ ] **Step 10: Apply the reviewed migration to the operator DB**

```bash
.venv/bin/python scripts/migrate_artifact_paths.py \
  --db-path data/pipeline.db \
  --old-root /home/thenam176/novel_pipeline \
  --new-root "$PWD/data" \
  --report-dir "$PROTECTED_RUN_DIR/operator-apply" \
  --verify-files --apply \
  --backup-confirmation "verified:$FRESH_BACKUP_ID" \
  --expected-db-sha256 "$MAINTENANCE_DB_SHA"
```

Expected: exactly the freshly reviewed mappings update, unresolved/containment counts remain zero, integrity is `ok`, and foreign-key violations are zero. On failure, keep the app stopped and restore the direct DB copy; do not regenerate content.

- [ ] **Step 11: Prove live idempotency and remove the fallback**

Run:

```bash
export OPERATOR_POST_SHA="$(sha256sum data/pipeline.db | awk '{print $1}')"
.venv/bin/python scripts/migrate_artifact_paths.py \
  --db-path data/pipeline.db \
  --old-root /home/thenam176/novel_pipeline \
  --new-root "$PWD/data" \
  --report-dir "$PROTECTED_RUN_DIR/operator-post-dry-run" \
  --verify-files
.venv/bin/python scripts/migrate_artifact_paths.py \
  --db-path data/pipeline.db \
  --old-root /home/thenam176/novel_pipeline \
  --new-root "$PWD/data" \
  --report-dir "$PROTECTED_RUN_DIR/operator-second-apply" \
  --verify-files --apply \
  --backup-confirmation "verified:$FRESH_BACKUP_ID" \
  --expected-db-sha256 "$OPERATOR_POST_SHA"
sqlite3 data/pipeline.db 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
```

Expected: zero approved old-root matches and zero rows updated. Only then remove the exact `ARTIFACT_LEGACY_ROOT=/home/thenam176/novel_pipeline` line from ignored `.env`; do not alter other configuration or secrets.

- [ ] **Step 12: Restart and execute representative smoke tests**

Run:

```bash
scripts/start-cloudflare.sh
set -a
source .env
set +a
.venv/bin/python scripts/ops.py smoke \
  --base-url http://127.0.0.1:7860 \
  --username "${MOBILE_API_ADMIN_USERNAME:-admin}" \
  --password "${MOBILE_API_ADMIN_PASSWORD:-change_me}" \
  --web-url http://127.0.0.1:7860
```

Expected: readiness succeeds; authenticated Library, raw Reader, translated Reader, HTML content, cover, audio stream/download, and TTS artifact status/download all succeed; protected routes deny unauthenticated requests; status responses contain no absolute paths; sampled file sizes and hashes equal the pre-migration evidence.

- [ ] **Step 13: Final validation and evidence check**

Run:

```bash
.venv/bin/python -m pytest tests/test_migrate_artifact_paths.py tests/test_artifact_paths.py tests/test_mobile_api_system_status.py -q
scripts/verify.sh
git diff --check
git status --short
```

Expected: all validations pass, operator DB integrity remains `ok`, foreign-key violations remain zero, no paid provider was called, no content file changed, no staging file remains, and the code worktree is clean.
