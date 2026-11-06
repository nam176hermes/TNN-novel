# Workstream 5: TTS Log Privacy

Goal: Ensure TTS and ffmpeg failures cannot log chapter content, prompts, secrets, or private paths.

Scope:
- Replace raw upstream stdout and stderr logging with structured allowlisted fields.
- Redact provider and filesystem values.
- Bound diagnostic length.
- Add adversarial tests containing fake secrets and chapter text.
- Preserve enough diagnostics for GPU and model-loading failures.

Required verification: focused TTS logging tests, secret scan, full backend suite, and GPU-unavailable readiness regression.
