## Phase 9 Implementation Note

### Current backup/export/deploy state

- Book export already exists through authenticated FastAPI routes under `/api/books/{book_id}/exports`.
- Supported book export formats today are `txt`, `docx`, and `epub`.
- Audiobook download exists through authenticated routes:
  - `/api/books/{book_id}/exports/audiobook/m4b/download`
  - `/api/books/{book_id}/chapters/{chapter_id}/audio/download`
- Glossary export already exists at `/api/glossary/export` with `json` and `csv`.
- System backup currently exists mainly as operator scripts and docs:
  - `scripts/backup-local.sh`
  - `scripts/ops.py backup|restore|restore-drill`
- Status UI currently shows backup guidance, but it is mixed into the status page as operational help, not a real System Backup workflow.

### Current risks

- `scripts/backup-local.sh` can include `.env` without forcing encryption.
- Script backup logic and `scripts/ops.py` backup logic have drifted apart.
- Export metadata can still expose internal filesystem paths through `path`.
- There is no dedicated authenticated backup API for operator-triggered backup/download from the web app.
- Book Export and System Backup are not clearly separated in UI and docs.
- Restore is documented, but there is no manifest-driven backup summary shown in the app.

### What this phase changes

- Unify backup behavior around manifest-driven backup metadata.
- Require encryption when secrets are included.
- Add authenticated system-backup API endpoints for create/list/download.
- Keep restore as CLI/doc workflow, not a risky one-click restore UI.
- Stop exposing raw export filesystem paths in API responses.
- Separate Book Export from System Backup in UI and docs.
- Expand docs for export workflow, backup/restore, and deployment hardening.

### What stays unchanged

- No restore UI that overwrites live data.
- No auth weakening.
- No change to core job runner architecture.
- No new public file serving.
- No new crawler/source automation.
