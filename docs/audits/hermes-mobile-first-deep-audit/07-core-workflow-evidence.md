# Core Workflow Evidence

## Focused test gate

A fresh isolated run passed 271 tests covering:

- Import metadata and idempotency
- Durable import repository, runtime, worker, retry, cancellation, and observability
- URL and ebook import
- Translation presets and mocked Ollama behavior
- Deterministic QA and glossary QA
- Export
- Backup API, schedule, listing, and job service

[Source: focused pytest command output, 271 passed in 109.91 seconds]

## TTS

A fresh TTS run passed 42 tests. The production API container returned `tts_unavailable` with a safe error code when CUDA was unavailable. No synthesis was attempted. [Source: focused pytest output and production availability probe]

The low-level F5 engine contains a CUDA-to-CPU fallback, while current API and pipeline entry points call `require_tts_runtime_available`. This is a defense-in-depth risk if a future caller bypasses the gate. [Source: `app/services/tts/f5_vietnamese_engine.py:118-130`; current callers]

## Backup and restore

The backup timer was active and the newest local encrypted set was about ten hours old at inspection. Six encrypted archives had matching manifest and checksum sidecars. A fresh isolated restore drill completed successfully and passed authenticated Reader smoke. [Source: systemd timer/service output and latest restore validation]

## Intentionally untested

- Paid translation calls
- Live third-party challenge behavior
- GPU voice quality
- CPU F5/ViVoice synthesis
- Destructive production restore

Verdict: workflows GO with limitations.
