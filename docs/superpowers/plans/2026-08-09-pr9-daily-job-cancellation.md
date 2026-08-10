# PR9 Daily-job Cancellation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a durable SQLite cancellation stop a daily job before the next chapter and preserve `cancelled` / `CANCELED` as the final state.

**Architecture:** Keep the existing `JobService` and canonical state graph. Extend the cancellation read to consult the persisted mobile-job row when a tracker is database-backed, and make `_run_daily_job()` return immediately at cancellation boundaries instead of falling through to completion.

**Tech Stack:** Python 3.11, asyncio, raw `sqlite3`, pytest, pytest-asyncio.

## Global Constraints

- The new regression must be observed RED before any production change.
- A cancelled daily job must not start a later chapter.
- The final persisted status/state must remain `cancelled` / `CANCELED`.
- Preserve all public API contracts and non-daily job behavior.
- Do not modify operator data; use the existing temporary database fixture.

---

### Task 1: Reproduce durable cancellation with a RED test

**Files:**
- Modify: `tests/test_job_service_logic.py`

**Interfaces:**
- Consumes: `request_cancel_mobile_job(db_path: Path, *, job_id: str) -> bool` and `JobService._run_daily_job(job_id: str, limit: int) -> None`.
- Produces: regression test `test_daily_job_observes_durable_cancel_and_does_not_start_next_chapter`.

- [ ] **Step 1: Import the durable cancellation helper**

Add `request_cancel_mobile_job` to the existing import list from `app.database.db`.

- [ ] **Step 2: Write the failing async regression test**

```python
@pytest.mark.asyncio
async def test_daily_job_observes_durable_cancel_and_does_not_start_next_chapter(
    temp_db_path,
) -> None:
    translated: list[int] = []

    class DurableCancelPipeline:
        db_path = temp_db_path

        def get_pending_chapters(self, *, limit: int) -> list[dict[str, int]]:
            assert limit == 2
            return [
                {"id": 101, "book_id": 1},
                {"id": 102, "book_id": 1},
            ]

        def translate_chapter(self, **kwargs) -> str:
            translated.append(int(kwargs["chapter_id"]))
            if len(translated) == 1:
                assert request_cancel_mobile_job(temp_db_path, job_id=str(kwargs["job_id"]))
            return "translated"

    service = JobService(DurableCancelPipeline())  # type: ignore[arg-type]
    job = service.tracker.create_job("daily", None, 100)

    await service._run_daily_job(job.job_id, 2)

    persisted = JobTracker(db_path=temp_db_path).get_job(job.job_id)
    assert persisted is not None
    assert translated == [101]
    assert persisted.status == "cancelled"
    assert persisted.state == "CANCELED"
```

- [ ] **Step 3: Run the test and verify the expected RED result**

Run:

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python \
  -m pytest -q -s \
  tests/test_job_service_logic.py::test_daily_job_observes_durable_cancel_and_does_not_start_next_chapter
```

Expected: FAIL because `translated` contains chapter `102` and/or persisted status is `completed`. A syntax/import error is not an acceptable RED result.

- [ ] **Step 4: Commit the RED test**

```bash
git add tests/test_job_service_logic.py
git commit -m "test: reproduce durable daily-job cancellation race"
```

---

### Task 2: Make daily cancellation durable and terminal

**Files:**
- Modify: `app/mobile_api/services/job_service.py`
- Test: `tests/test_job_service_logic.py`

**Interfaces:**
- Consumes: imported `get_mobile_job(db_path, job_id)` and the existing `JobTracker.db_path`.
- Produces: `_job_cancel_requested(job_id: str) -> bool` that honors persisted cancellation and `_run_daily_job()` cancellation boundaries that return immediately.

- [ ] **Step 1: Read persisted cancellation for database-backed jobs**

Update `_job_cancel_requested` so its behavior is equivalent to:

```python
def _job_cancel_requested(self, job_id: str) -> bool:
    job = self.tracker.get_job(job_id)
    if self.tracker.db_path is not None:
        persisted = get_mobile_job(self.tracker.db_path, job_id)
        if persisted is not None and (
            bool(persisted.get("cancel_requested"))
            or str(persisted.get("status") or "").lower() in {"cancelled", "canceled"}
        ):
            if job is not None:
                job.cancel_requested = True
            return True
    return bool(job and job.cancel_requested)
```

Do not add a new database API or schema field.

- [ ] **Step 2: Return at every daily-job cancellation boundary**

In `_run_daily_job()`:

- replace the pre-chapter `break` with `return` after `_cancel_if_requested` records the terminal state;
- add the same check immediately after each `translate_chapter` call and provider-attempt recording;
- add one final check before the `completed` update.

The final structure must not contain a path from an observed cancellation to `status="completed"`.

- [ ] **Step 3: Run the RED test and verify GREEN**

Run the same focused command from Task 1.

Expected: PASS; `translated == [101]` and persisted state is `CANCELED`.

- [ ] **Step 4: Run focused job cancellation coverage**

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python \
  -m pytest -q -s tests/test_job_service_logic.py -k "cancel or daily"
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the minimal production fix**

```bash
git add app/mobile_api/services/job_service.py
git commit -m "fix: preserve durable daily-job cancellation"
```

---

### Task 3: Verify PR9 as an isolated backend change

**Files:**
- Verify: `app/mobile_api/services/job_service.py`
- Verify: `tests/test_job_service_logic.py`

**Interfaces:**
- Consumes: completed Task 1 and Task 2 commits.
- Produces: fresh verification evidence and a clean PR9 worktree.

- [ ] **Step 1: Run the complete job-service test file**

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python \
  -m pytest -q -s tests/test_job_service_logic.py
```

- [ ] **Step 2: Run backend lint/typecheck wrapper**

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 scripts/lint.sh
```

- [ ] **Step 3: Run the full backend suite**

```bash
NOVEL_PIPELINE_IGNORE_DOTENV=1 /home/thenam176/Novel-TNN/.venv/bin/python -m pytest -q -s
```

- [ ] **Step 4: Check the final diff and worktree**

```bash
git diff --check
git status --short --branch
git log --oneline --decorate -5
```

Expected: no unstaged or untracked implementation artifacts; all checks exit `0`.

