"""Compatibility exports for the shared durable job state rules."""
from app.jobs import states as _states

CANONICAL_JOB_STATES = _states.CANONICAL_JOB_STATES
TERMINAL_JOB_STATES = _states.TERMINAL_JOB_STATES
RUNNING_JOB_STATES = _states.RUNNING_JOB_STATES
ALLOWED_JOB_STATE_TRANSITIONS = _states.ALLOWED_JOB_STATE_TRANSITIONS
STATUS_TO_STATE = _states.STATUS_TO_STATE
STAGE_TO_STATE = _states.STAGE_TO_STATE
normalize_job_state = _states.normalize_job_state
state_for_stage = _states.state_for_stage
is_valid_job_state_transition = _states.is_valid_job_state_transition
