# GPU-only TTS Availability Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject F5 TTS requests before job creation or synthesis whenever the host cannot run the local CUDA-backed F5 runtime.

**Architecture:** A small domain guard classifies F5 provider aliases and checks only local prerequisites: CUDA device configuration, PyTorch CUDA availability, and the installed `f5_tts` package. `JobService` invokes it before tracker-job creation, the two API routes translate its domain exception to a safe HTTP 503 detail, and `PipelineService` invokes the same guard before it can construct a fallback-capable TTS pipeline.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, pytest, monkeypatch, existing SQLite-backed job tracker.

## Global Constraints

- F5 Vietnamese remains GPU-only; a non-GPU host must not start a TTS job or attempt synthesis.
- The unavailable response is HTTP `503` with `detail.code == "tts_unavailable"` and a safe message.
- Do not create a tracker job, TTS database row, audit-start event, fallback call, model download, or provider request when F5 is unavailable.
- Preserve behavior for explicitly configured non-F5 providers.
- Do not change Docker, CUDA/GPU provisioning, Cloudflare, production configuration, or artifact-path metadata.
- Tests must use temporary databases and mocked runtime probes; no real GPU, F5 package, model download, provider request, or production database.

---

## File Structure

- Create `app/services/tts/availability.py`: provider aliases, safe `TTSUnavailableError`, and local-only readiness guard.
- Modify `app/mobile_api/services/job_service.py`: invoke the guard before target selection/tracker creation.
- Modify `app/mobile_api/services/pipeline_service.py`: guard direct generation and remove legacy fallback for F5 only.
- Modify `app/mobile_api/routers/jobs.py` and `app/mobile_api/routers/tts.py`: translate the domain exception to the approved 503 payload.
- Create `tests/test_tts_availability.py`: unit coverage for F5/non-F5 availability decisions.
- Modify `tests/test_job_service_logic.py` and `tests/test_mobile_api_tts.py`: verify no job/fallback on rejection and identical API behavior on both entry points.

### Task 1: Add a local-only F5 readiness guard

**Files:**
- Create: `app/services/tts/availability.py`
- Test: `tests/test_tts_availability.py`

**Interfaces:**
- Produces `TTSUnavailableError(message: str)` with `code = "tts_unavailable"` and `detail()` returning `{"code": "tts_unavailable", "message": message}`.
- Produces `is_f5_provider(provider: str | None) -> bool` and `require_tts_runtime_available(provider: str | None = None, device: str | None = None) -> None`.
- Consumes `settings.tts_provider`, `settings.tts_device`, `importlib.util.find_spec`, and a lazy PyTorch CUDA probe.

- [x] **Step 1: Write failing availability tests**

```python
import pytest

from app.services.tts.availability import TTSUnavailableError, require_tts_runtime_available


def test_f5_without_cuda_raises_safe_unavailable(monkeypatch):
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: False)

    with pytest.raises(TTSUnavailableError) as exc_info:
        require_tts_runtime_available(provider="f5_vietnamese", device="cuda")

    assert exc_info.value.detail()["code"] == "tts_unavailable"


def test_explicit_non_f5_provider_is_not_blocked(monkeypatch):
    monkeypatch.setattr("app.services.tts.availability._cuda_available", lambda: False)

    require_tts_runtime_available(provider="edge_tts", device="cpu")
```

- [x] **Step 2: Run the new test file and confirm import failure**

Run: `NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_tts_availability.py`

Expected: FAIL because `app.services.tts.availability` does not exist.

- [x] **Step 3: Implement the minimal guard**

```python
F5_PROVIDER_ALIASES = frozenset({"f5", "f5_tts", "f5_vietnamese", "vivioice", "vivoice"})


class TTSUnavailableError(RuntimeError):
    code = "tts_unavailable"

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


def require_tts_runtime_available(provider: str | None = None, device: str | None = None) -> None:
    if not is_f5_provider(provider or settings.tts_provider):
        return
    if (device or settings.tts_device).lower() != "cuda" or not _cuda_available():
        raise TTSUnavailableError("Local F5 TTS is unavailable: a CUDA GPU is required.")
    if importlib.util.find_spec("f5_tts") is None:
        raise TTSUnavailableError("Local F5 TTS is unavailable: the F5 runtime is not installed.")
```

The lazy CUDA probe must catch missing PyTorch and return `False`; it must not load F5, download a model, or perform network I/O.

- [x] **Step 4: Run the availability tests**

Run: `NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_tts_availability.py`

Expected: PASS.

- [x] **Step 5: Commit the guard and tests**

```bash
git add app/services/tts/availability.py tests/test_tts_availability.py
git commit -m "feat: gate F5 tts on local gpu availability"
```

### Task 2: Reject API requests before job creation

**Files:**
- Modify: `app/mobile_api/services/job_service.py:1281-1313`
- Modify: `app/mobile_api/routers/jobs.py:173-200`
- Modify: `app/mobile_api/routers/tts.py:62-76`
- Modify: `tests/test_job_service_logic.py`
- Modify: `tests/test_mobile_api_tts.py`

**Interfaces:**
- Consumes `require_tts_runtime_available()` and `TTSUnavailableError` from `app.services.tts.availability`.
- `JobService.start_tts_job` raises `TTSUnavailableError` before target selection and `tracker.create_job`.
- Both API routes convert that exception to `HTTPException(status_code=503, detail=exc.detail())`.

- [x] **Step 1: Write failing service and route tests**

```python
def test_start_tts_job_rejects_before_tracker_creation(monkeypatch):
    class RecordingTracker:
        def __init__(self):
            self.create_calls = 0

        def create_job(self, **kwargs):
            self.create_calls += 1
            pytest.fail("The tracker must not receive an unavailable TTS job")

    tracker = RecordingTracker()
    service = JobService(object(), tracker=tracker)
    monkeypatch.setattr(
        "app.mobile_api.services.job_service.require_tts_runtime_available",
        lambda: (_ for _ in ()).throw(TTSUnavailableError("GPU required")),
    )

    with pytest.raises(TTSUnavailableError):
        service.start_tts_job(book_id=1)

    assert tracker.create_calls == 0
```

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload", [
    ("/api/jobs/tts", {"book_id": 1, "chapter_ids": [2], "limit": 1, "params": {}}),
    ("/api/tts/chapter", {"book_id": 1, "chapter_id": 2, "voice_config": {}}),
])
async def test_tts_start_endpoints_return_safe_unavailable(path, payload):
    service = UnavailableJobService()
    app.dependency_overrides[get_job_service] = lambda: service
    response = await authenticated_client.post(path, json=payload)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "tts_unavailable"
    assert service.calls == 1
```

- [x] **Step 2: Run the focused tests and confirm they fail**

Run: `NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_job_service_logic.py tests/test_mobile_api_tts.py`

Expected: FAIL because unavailable requests currently create/return pending jobs.

- [x] **Step 3: Add the pre-creation guard and router translation**

```python
# JobService.start_tts_job, before target selection
require_tts_runtime_available()
```

```python
# each TTS-start router; pass the existing request fields to the service
try:
    job_id = service.start_tts_job(
        book_id=request.book_id,
        chapter_ids=request.chapter_ids,
        limit=request.limit,
    )
except TTSUnavailableError as exc:
    raise HTTPException(status_code=503, detail=exc.detail()) from exc
```

Do not record a `job_start` audit event in the error path; the existing audit call must remain after a successful service return.

- [x] **Step 4: Run focused service and API tests**

Run: `NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_job_service_logic.py tests/test_mobile_api_tts.py tests/test_tts_availability.py`

Expected: PASS.

- [x] **Step 5: Commit the API gate**

```bash
git add app/mobile_api/services/job_service.py app/mobile_api/routers/jobs.py app/mobile_api/routers/tts.py tests/test_job_service_logic.py tests/test_mobile_api_tts.py
git commit -m "fix: reject unavailable f5 tts jobs before queueing"
```

### Task 3: Remove the F5 legacy fallback escape hatch

**Files:**
- Modify: `app/mobile_api/services/pipeline_service.py:4754-4800`
- Modify: `tests/test_mobile_api_db_logic.py`

**Interfaces:**
- Consumes `is_f5_provider`, `require_tts_runtime_available`, and `TTSUnavailableError`.
- `PipelineService.generate_audio` invokes the guard before constructing `TTSPipeline` for F5.
- For F5, construct `TTSPipeline` with `legacy_fallback=None`. Explicit non-F5 providers retain `legacy_fallback=text_to_speech_file`.

- [x] **Step 1: Write failing direct-pipeline tests**

```python
def test_generate_audio_rejects_unavailable_f5_before_constructing_pipeline(monkeypatch, temp_pipeline, book_id, chapter_id):
    monkeypatch.setattr(
        "app.mobile_api.services.pipeline_service.require_tts_runtime_available",
        lambda: (_ for _ in ()).throw(TTSUnavailableError("GPU required")),
    )
    monkeypatch.setattr(
        "app.mobile_api.services.pipeline_service.TTSPipeline",
        lambda *args, **kwargs: pytest.fail("TTSPipeline must not be constructed"),
    )

    with pytest.raises(TTSUnavailableError):
        temp_pipeline.generate_audio(book_id, chapter_id)
```

```python
def test_generate_audio_keeps_legacy_fallback_for_explicit_non_f5_provider(monkeypatch, temp_pipeline, book_id, chapter_id):
    captured = {}

    class CapturingPipeline:
        def __init__(self, db_path, data_dir, legacy_fallback):
            captured["legacy_fallback"] = legacy_fallback

        def generate_chapter(self, **kwargs):
            return SimpleNamespace(status="completed", output_path="audio.mp3")

    monkeypatch.setattr(pipeline_service_module.settings, "tts_provider", "edge_tts")
    monkeypatch.setattr(pipeline_service_module, "TTSPipeline", CapturingPipeline)
    temp_pipeline.generate_audio(book_id, chapter_id)

    assert callable(captured["legacy_fallback"])
```

- [x] **Step 2: Run the targeted direct-pipeline tests and confirm failure**

Run: `NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_mobile_api_db_logic.py -k 'generate_audio'`

Expected: FAIL because F5 currently constructs `TTSPipeline` with `text_to_speech_file`.

- [x] **Step 3: Implement provider-aware pipeline construction**

```python
provider = settings.tts_provider
legacy_fallback = text_to_speech_file
if is_f5_provider(provider):
    require_tts_runtime_available(provider=provider)
    legacy_fallback = None

pipeline = TTSPipeline(self.db_path, self.data_dir, legacy_fallback=legacy_fallback)
```

The guard runs after validating the requested book/chapter/text but before constructing `TTSPipeline`, writing TTS rows, or calling any fallback.

- [x] **Step 4: Run all focused TTS tests**

Run: `NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_tts_availability.py tests/test_job_service_logic.py tests/test_mobile_api_tts.py tests/test_mobile_api_db_logic.py -k 'tts or generate_audio'`

Expected: PASS.

- [x] **Step 5: Commit the direct-path guard**

```bash
git add app/mobile_api/services/pipeline_service.py tests/test_mobile_api_db_logic.py
git commit -m "fix: prevent f5 fallback without gpu"
```

### Task 4: Run static checks and regression validation

**Files:**
- Modify: no additional source files expected.

**Interfaces:**
- Validates the domain guard, both API routes, job service, and direct pipeline behavior together.

- [ ] **Step 1: Compile changed Python modules**

Run: `NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m compileall -q app/services/tts/availability.py app/mobile_api/services/job_service.py app/mobile_api/services/pipeline_service.py app/mobile_api/routers/jobs.py app/mobile_api/routers/tts.py`

Expected: exit 0.

- [ ] **Step 2: Run focused regression suite**

Run: `NOVEL_PIPELINE_IGNORE_DOTENV=1 .venv/bin/python -m pytest -q tests/test_tts_availability.py tests/test_job_service_logic.py tests/test_mobile_api_tts.py tests/test_mobile_api_db_logic.py`

Expected: PASS with no network/GPU dependency.

- [ ] **Step 3: Check the worktree diff**

Run: `git diff --check 331cdc5..HEAD && git status --short`

Expected: no whitespace errors and only the TTS workstream files changed.

- [ ] **Step 4: Commit any final test-only corrections**

```bash
git add app tests
git commit -m "test: cover gpu-only tts unavailable behavior"
```

Run the commit only if Task 4 required a source or test correction; otherwise do not create an empty commit.
