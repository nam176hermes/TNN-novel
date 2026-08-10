# PR8 TTS Capability Errors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Return and display distinct F5 TTS capability failures for CUDA/GPU, runtime, and model prerequisites without suggesting CPU fallback.

**Architecture:** Extend the existing availability gate with safe structured codes and deterministic prerequisite ordering. Preserve the existing FastAPI 503 mapping and teach Reader audio error handling to prioritize `ApiError.code`, with sanitized text heuristics as compatibility fallback.

**Tech Stack:** Python 3.11, FastAPI, pytest, React 19, TypeScript, Vitest.

## Global Constraints

- F5 remains CUDA-only; no CPU fallback is introduced or suggested.
- Error codes are exactly `gpu_unavailable`, `runtime_missing`, and `model_missing`.
- GPU validation runs before runtime validation, which runs before model validation.
- Non-F5 providers retain existing behavior.
- Error responses and UI copy must not expose filesystem paths or upstream payloads.

---

### Task 1: Produce structured availability failures

**Files:**
- Modify: `app/services/tts/availability.py`
- Test: `tests/test_tts_availability.py`
- Test: `tests/test_tts_f5_engine.py`

**Interfaces:**
- Consumes: F5 provider/device/model settings
- Produces: `TTSUnavailableError(message: str, code: str = "tts_unavailable")` and `require_tts_runtime_available(...)`

- [ ] **Step 1: Write failing tests for all codes and ordering**

Add tests asserting:

```python
with pytest.raises(TTSUnavailableError) as exc_info:
    require_tts_runtime_available(provider="f5", device="cuda")
assert exc_info.value.detail()["code"] == "gpu_unavailable"
```

Then mock CUDA available/runtime absent and expect `runtime_missing`. Finally mock CUDA/runtime available with an explicit missing checkpoint/vocabulary pair and expect `model_missing`. In the GPU test, make the runtime/model probes fail the test if called to prove ordering.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `.venv/bin/python -m pytest -q -s tests/test_tts_availability.py`

Expected: FAIL because all raised errors currently use `tts_unavailable` and model prerequisites are not checked.

- [ ] **Step 3: Add code-bearing errors and model prerequisite probe**

Implement:

```python
class TTSUnavailableError(RuntimeError):
    def __init__(self, message: str, *, code: str = "tts_unavailable") -> None:
        super().__init__(message)
        self.code = code

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}
```

Extend the gate parameters with optional `model`, `model_repo`, `ckpt_file`, and `vocab_file`. For ViVoice aliases, accept a non-empty model repository or a complete existing local checkpoint/vocabulary pair; reject incomplete or nonexistent explicit pairs with safe `model_missing` copy. Collapse non-CUDA configuration and unavailable CUDA to `gpu_unavailable`.

- [ ] **Step 4: Keep capability inspection consistent**

Update `inspect_tts_capability` to emit `gpu_unavailable`, `runtime_missing`, or `model_missing` using the same ordering and safe prerequisite helper.

- [ ] **Step 5: Run focused tests and capability consumers**

Run:

```bash
.venv/bin/python -m pytest -q -s tests/test_tts_availability.py tests/test_runtime_readiness.py tests/test_operational_metrics.py
```

Expected: PASS.

- [ ] **Step 6: Commit backend capability logic**

```bash
git add app/services/tts/availability.py tests/test_tts_availability.py tests/test_tts_f5_engine.py
git add -f docs/superpowers/specs/2026-08-09-pr8-tts-capability-errors-design.md docs/superpowers/plans/2026-08-09-pr8-tts-capability.md
git commit -m "fix: distinguish f5 capability failures"
```

### Task 2: Prove the production HTTP contract

**Files:**
- Modify: `tests/test_mobile_api_tts.py`
- Review only: `app/mobile_api/routers/tts.py`

**Interfaces:**
- Consumes: `TTSUnavailableError.detail()`
- Produces: HTTP 503 detail with exact capability code

- [ ] **Step 1: Update the API failure double**

Make the mocked service raise:

```python
raise TTSUnavailableError(
    "Local F5 TTS requires an available CUDA GPU.",
    code="gpu_unavailable",
)
```

Assert response status 503 and exact detail code/message. Add equivalent parameterized coverage for `runtime_missing` and `model_missing` if the router mapping is shared.

- [ ] **Step 2: Run the focused API tests**

Run: `.venv/bin/python -m pytest -q -s tests/test_mobile_api_tts.py`

Expected: PASS using the existing router mapping; modify the router only if the test proves it drops structured detail.

- [ ] **Step 3: Run rejection-before-work tests**

Run:

```bash
.venv/bin/python -m pytest -q -s tests/test_job_service_logic.py tests/test_tts_pipeline.py tests/test_mobile_api_db_logic.py
```

Expected: PASS; unavailable F5 does not queue work or construct the engine.

- [ ] **Step 4: Commit API contract coverage**

```bash
git add tests/test_mobile_api_tts.py app/mobile_api/routers/tts.py
git commit -m "test: lock tts capability error contract"
```

### Task 3: Map capability codes to truthful Reader copy

**Files:**
- Modify: `web/src/components/reader/useReaderAudio.ts`
- Modify: `web/src/components/reader/useReaderAudio.test.tsx`

**Interfaces:**
- Consumes: `ApiError.code`, sanitized legacy error text
- Produces: `friendlyAudioError(error: unknown, fallback?: string): string`

- [ ] **Step 1: Write failing copy tests**

Import `ApiError` and `friendlyAudioError`, then assert:

```tsx
expect(friendlyAudioError(new ApiError('unavailable', 503, 'gpu_unavailable')))
  .toContain('CUDA');
expect(friendlyAudioError(new ApiError('missing', 503, 'runtime_missing')))
  .toContain('runtime F5');
expect(friendlyAudioError(new ApiError('missing', 503, 'model_missing')))
  .toContain('model');
expect(friendlyAudioError('CUDA GPU is unavailable')).not.toContain('TTS_DEVICE=cpu');
```

- [ ] **Step 2: Run focused frontend tests and verify failure**

Run: `npm --prefix web test -- useReaderAudio.test.tsx`

Expected: FAIL because the helper accepts only a string and recommends CPU.

- [ ] **Step 3: Prioritize structured codes and retain safe fallback heuristics**

Change the helper to accept `unknown`, map the three codes first, then sanitize a message extracted from `Error`/string. Replace the CUDA fallback with CUDA-required guidance only. Update `audioErrorFromUnknown` to pass the original error so `ApiError.code` is retained.

- [ ] **Step 4: Run focused frontend tests and verify success**

Run: `npm --prefix web test -- useReaderAudio.test.tsx`

Expected: PASS with distinct copy and no CPU guidance.

- [ ] **Step 5: Run PR8 validation**

Run:

```bash
.venv/bin/python -m pytest -q -s tests/test_tts_availability.py tests/test_mobile_api_tts.py tests/test_job_service_logic.py tests/test_tts_pipeline.py tests/test_mobile_api_db_logic.py tests/test_runtime_readiness.py tests/test_operational_metrics.py
scripts/lint.sh
npm --prefix web test -- useReaderAudio.test.tsx
npm --prefix web run typecheck
npm --prefix web run build
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 6: Commit frontend copy**

```bash
git add web/src/components/reader/useReaderAudio.ts web/src/components/reader/useReaderAudio.test.tsx
git commit -m "fix: show truthful f5 capability guidance"
```
