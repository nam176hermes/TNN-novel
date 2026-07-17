# GPU-only TTS Availability Gate

## Goal

When the configured TTS provider is F5 Vietnamese, the API must reject a TTS
request before any job, artifact, database row, audit-start event, fallback,
or provider call is created if the host cannot run local F5 synthesis.

## Scope

- Keep F5 Vietnamese as a GPU-only local provider.
- Return HTTP `503` for unavailable F5 TTS with a safe structured detail:
  `{"code": "tts_unavailable", "message": "..."}`.
- Cover both API entry points: `POST /api/jobs/tts` and
  `POST /api/tts/chapter`.
- Protect the direct mobile pipeline path so it cannot silently use the
  Edge-TTS legacy fallback for an unavailable F5 configuration.
- Add focused unit and API regression tests using mocked GPU/dependency state.

## Out Of Scope

- GPU drivers, Docker image changes, CUDA/PyTorch/F5 installation, model
  downloads, proxy configuration, and Cloudflare changes.
- Changing explicitly configured non-F5 providers.
- Retrying, cancelling, or rewriting existing historical TTS jobs.
- Artifact-path data migration or production database changes.

## Design

Create one TTS availability guard near the F5 provider integration. It will
evaluate only local, non-network prerequisites:

1. the configured provider is an F5 Vietnamese alias;
2. the configured device is CUDA;
3. PyTorch is installed and reports CUDA available; and
4. the `f5_tts` package is installed.

The guard raises a dedicated safe domain exception with a stable unavailable
message. It must not instantiate F5, download a model, or make a provider
request.

`JobService.start_tts_job` calls this guard before selecting targets or
creating a tracker job. Both API routes already delegate there, so both return
the same `503` response without a job ID or job-start audit event.

`PipelineService.generate_audio` calls the same guard and does not pass
`text_to_speech_file` as a fallback when the provider is F5. That makes the
direct internal path fail safely too. An explicitly configured non-F5 provider
retains its existing behavior.

Routers translate the domain exception to the approved `503` detail shape;
other TTS exceptions retain their current behavior.

## Acceptance Criteria

- With F5 configured and CUDA unavailable, both TTS endpoints return `503`
  with `detail.code == "tts_unavailable"`.
- The rejection occurs before tracker-job creation, audit-start recording, or
  synthesis/fallback invocation.
- The direct `PipelineService.generate_audio` path raises the same safe
  unavailable error before constructing a fallback-capable pipeline.
- An explicitly non-F5 provider is not blocked by the GPU-only F5 gate.
- Tests do not require a real GPU, F5 package, network request, or production
  database.
