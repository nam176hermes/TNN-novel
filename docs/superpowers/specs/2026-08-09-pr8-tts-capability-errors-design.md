# PR8 TTS Capability Error Design

## Goal

Make production F5 TTS failures accurately distinguish unavailable GPU, missing runtime, and missing model resources, without suggesting unsupported CPU execution.

## Error contract

F5 availability failures use HTTP 503 with a structured detail object containing `code` and safe `message`:

- `gpu_unavailable`: F5 requires a CUDA-capable GPU, CUDA device configuration, and an available CUDA runtime/device.
- `runtime_missing`: the Python F5 runtime/dependencies are not installed or importable.
- `model_missing`: required model configuration or local model files are missing/unavailable before synthesis.

Non-F5 providers retain their existing behavior. Messages must not expose private paths or upstream payloads.

## Ordering

Availability validation checks GPU first, runtime second, and model prerequisites third. This provides one deterministic, actionable reason and avoids model/runtime work when CUDA cannot run F5.

## Frontend copy

- Prefer the structured API code when available.
- `gpu_unavailable`: say that F5 requires CUDA and the server GPU/CUDA environment must be made available.
- `runtime_missing`: say that the F5 runtime/dependencies are missing on the server.
- `model_missing`: say that the configured F5 model/checkpoint/vocabulary resources are missing.
- Retain safe text heuristics for legacy/unstructured job failures, but never recommend `TTS_DEVICE=cpu` for F5.

## Implementation boundary

- Port only the useful GPU-only guards from the old `feat/tts-gpu-unavailable` worktree onto a fresh `origin/main` branch.
- Do not bring unrelated commits from that branch.
- Do not add CPU fallback or change non-F5 provider capabilities.

## Verification

- Unit tests cover each error code and check ordering.
- API tests prove production-style `gpu_unavailable` returns HTTP 503 with the exact code.
- Frontend tests prove all three messages differ and contain no CPU-switch guidance.
- Relevant TTS pipeline/job tests confirm unavailable F5 work is rejected before queueing or model construction.
