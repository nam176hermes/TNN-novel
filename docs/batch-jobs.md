# Batch Translation and Audio Jobs

The app supports batch work in three safe modes:

- Authenticated web UI for normal browser use.
- Local foreground CLI commands for operator use without logging into the web app.
- Local background shell commands for work that should continue after the web/API app is stopped.

The public HTTP API is still protected. Do not expose translation or TTS job creation without authentication, because those actions can spend provider credits and process private book content.

## Web UI

Use these controls after logging in:

- `Raw chưa dịch` -> `Dịch hàng loạt` or `Dịch N chương`
  - Starts one translation job for the selected book.
  - The backend selects untranslated chapters that still have source text.
  - Completed chapters with existing translated output are skipped.
- `Xuất file` -> `Tạo audio hàng loạt`
  - Starts one TTS job for the selected book.
  - The backend selects translated chapters that do not already have audio.

Both actions reuse the existing authenticated `/api/jobs/translate` and `/api/jobs/tts` endpoints and then send the operator to `Tác vụ` to monitor progress, cancel, or retry.

Important: UI-started jobs run inside the backend API process. Closing only the browser is fine. Stopping the API/server app stops the worker; the job will be interrupted and must be retried after restart. Use the local background command below when you want the web/API app to be off.

## Local CLI Without Web Login

Run these commands on the server or workstation that has access to the app data directory and `.env` file.

Translate untranslated chapters for one book:

```bash
python -m app.jobs.batch translate --book-id 1 --limit 500 --preset-id balanced
```

Translate with an explicit style profile and chunk size:

```bash
python -m app.jobs.batch translate \
  --book-id 1 \
  --limit 100 \
  --preset-id fast_draft \
  --style-profile-id huyen_huyen \
  --chunk-size 3500
```

Generate audio for translated chapters that do not already have audio:

```bash
python -m app.jobs.batch tts --book-id 1 --limit 200
```

Generate audio with explicit voice options:

```bash
python -m app.jobs.batch tts \
  --book-id 1 \
  --limit 50 \
  --voice vi-VN-HoaiMyNeural \
  --rate=-5% \
  --volume +0%
```

The CLI runs the job inside the current process and waits until it reaches a terminal status. A completed job exits with code `0`; failed, cancelled, or interrupted jobs exit with code `1`.

## Local Background Jobs With The App Off

Use `scripts/batch-local.sh` when you want a batch job to continue without keeping the web app/API process open:

```bash
scripts/batch-local.sh translate --book-id 1 --limit 500 --preset-id balanced
scripts/batch-local.sh tts --book-id 1 --limit 200
```

Check background processes:

```bash
scripts/batch-local.sh status
```

List log files:

```bash
scripts/batch-local.sh logs
```

The script starts `python -m app.jobs.batch ...` under `nohup`/`setsid`, stores pid files and logs in `data/logs/runtime/`, and does not require the web/API app to be running. It still requires the machine itself to remain powered on and connected to any needed local/cloud providers.

## Notes

- The CLI loads `.env` locally so provider keys work the same way as the server.
- The CLI does not require a web session, access token, or browser login.
- The CLI is not a public unauthenticated API. It should only be run by the single operator on a trusted machine.
- Translation and TTS jobs still use the existing job tracker, retry/resume behavior, operational events, and output paths.
