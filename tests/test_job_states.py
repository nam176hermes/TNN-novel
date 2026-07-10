from __future__ import annotations

import pytest

from app.mobile_api import job_states


@pytest.mark.parametrize("terminal_state", ["COMPLETED", "FAILED", "CANCELED", "STALE_INTERRUPTED"])
@pytest.mark.parametrize("active_state", ["QUEUED", "CLAIMED", "TRANSLATING", "QA_CHECKING", "GENERATING_TTS", "RETRYING"])
def test_terminal_states_do_not_transition_to_active_states(terminal_state: str, active_state: str) -> None:
    assert not job_states.is_valid_job_state_transition(terminal_state, active_state)


def test_canceled_job_cannot_become_completed() -> None:
    assert not job_states.is_valid_job_state_transition("CANCELED", "COMPLETED")


def test_failed_and_stale_jobs_do_not_enter_retrying_state_in_place() -> None:
    assert not job_states.is_valid_job_state_transition("FAILED", "RETRYING")
    assert not job_states.is_valid_job_state_transition("STALE_INTERRUPTED", "RETRYING")


@pytest.mark.parametrize("invalid_next", ["QUEUED", "RETRYING", "LOADING_SOURCE"])
def test_active_translation_job_cannot_jump_to_earlier_or_retry_states(invalid_next: str) -> None:
    assert not job_states.is_valid_job_state_transition("TRANSLATING", invalid_next)


def test_allowed_transition_map_covers_every_canonical_state() -> None:
    assert set(job_states.ALLOWED_JOB_STATE_TRANSITIONS) == job_states.CANONICAL_JOB_STATES
