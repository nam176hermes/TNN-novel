from __future__ import annotations

CANONICAL_JOB_STATES = {
    "QUEUED",
    "CLAIMED",
    "LOADING_SOURCE",
    "CLEANING_TEXT",
    "SPLITTING_CHUNKS",
    "TRANSLATING",
    "QA_CHECKING",
    "GLOSSARY_EXTRACTING",
    "SAVING_CHAPTER",
    "GENERATING_TTS",
    "EXPORTING",
    "PREPARING_BACKUP",
    "WRITING_BACKUP",
    "VALIDATING_BACKUP",
    "ENCRYPTING_BACKUP",
    "PUBLISHING_BACKUP",
    "COMPLETED",
    "FAILED",
    "CANCELED",
    "STALE_INTERRUPTED",
    "RETRYING",
}

TERMINAL_JOB_STATES = {"COMPLETED", "FAILED", "CANCELED", "STALE_INTERRUPTED"}
RUNNING_JOB_STATES = CANONICAL_JOB_STATES - TERMINAL_JOB_STATES - {"QUEUED", "RETRYING"}

ALLOWED_JOB_STATE_TRANSITIONS = {
    "QUEUED": RUNNING_JOB_STATES | {"CLAIMED", "CANCELED", "COMPLETED", "FAILED", "STALE_INTERRUPTED"},
    "RETRYING": RUNNING_JOB_STATES | {"CLAIMED", "CANCELED", "COMPLETED", "FAILED", "STALE_INTERRUPTED"},
    "CLAIMED": RUNNING_JOB_STATES | {"COMPLETED", "FAILED", "CANCELED", "STALE_INTERRUPTED"},
    "LOADING_SOURCE": {"LOADING_SOURCE", "SAVING_CHAPTER", "COMPLETED", "FAILED", "CANCELED", "STALE_INTERRUPTED"},
    "CLEANING_TEXT": {"CLEANING_TEXT", "SPLITTING_CHUNKS", "TRANSLATING", "COMPLETED", "FAILED", "CANCELED", "STALE_INTERRUPTED"},
    "SPLITTING_CHUNKS": {"SPLITTING_CHUNKS", "TRANSLATING", "COMPLETED", "FAILED", "CANCELED", "STALE_INTERRUPTED"},
    "TRANSLATING": {
        "TRANSLATING",
        "QA_CHECKING",
        "GLOSSARY_EXTRACTING",
        "SAVING_CHAPTER",
        "COMPLETED",
        "FAILED",
        "CANCELED",
        "STALE_INTERRUPTED",
    },
    "QA_CHECKING": {
        "QA_CHECKING",
        "GLOSSARY_EXTRACTING",
        "SAVING_CHAPTER",
        "GENERATING_TTS",
        "EXPORTING",
        "COMPLETED",
        "FAILED",
        "CANCELED",
        "STALE_INTERRUPTED",
    },
    "GLOSSARY_EXTRACTING": {
        "GLOSSARY_EXTRACTING",
        "QA_CHECKING",
        "SAVING_CHAPTER",
        "COMPLETED",
        "FAILED",
        "CANCELED",
        "STALE_INTERRUPTED",
    },
    "SAVING_CHAPTER": {"SAVING_CHAPTER", "LOADING_SOURCE", "COMPLETED", "FAILED", "CANCELED", "STALE_INTERRUPTED"},
    "GENERATING_TTS": {"GENERATING_TTS", "EXPORTING", "COMPLETED", "FAILED", "CANCELED", "STALE_INTERRUPTED"},
    "EXPORTING": {"EXPORTING", "COMPLETED", "FAILED", "CANCELED", "STALE_INTERRUPTED"},
    "PREPARING_BACKUP": {
        "PREPARING_BACKUP",
        "WRITING_BACKUP",
        "FAILED",
        "CANCELED",
        "STALE_INTERRUPTED",
    },
    "WRITING_BACKUP": {
        "WRITING_BACKUP",
        "VALIDATING_BACKUP",
        "FAILED",
        "CANCELED",
        "STALE_INTERRUPTED",
    },
    "VALIDATING_BACKUP": {
        "VALIDATING_BACKUP",
        "ENCRYPTING_BACKUP",
        "FAILED",
        "CANCELED",
        "STALE_INTERRUPTED",
    },
    "ENCRYPTING_BACKUP": {
        "ENCRYPTING_BACKUP",
        "PUBLISHING_BACKUP",
        "FAILED",
        "CANCELED",
        "STALE_INTERRUPTED",
    },
    "PUBLISHING_BACKUP": {
        "PUBLISHING_BACKUP",
        "COMPLETED",
        "FAILED",
        "CANCELED",
        "STALE_INTERRUPTED",
    },
    "COMPLETED": {"COMPLETED"},
    "FAILED": {"FAILED"},
    "CANCELED": {"CANCELED"},
    "STALE_INTERRUPTED": {"STALE_INTERRUPTED"},
}

STATUS_TO_STATE = {
    "pending": "QUEUED",
    "queued": "QUEUED",
    "retrying": "RETRYING",
    "running": "CLAIMED",
    "completed": "COMPLETED",
    "failed": "FAILED",
    "cancelled": "CANCELED",
    "canceled": "CANCELED",
    "interrupted": "STALE_INTERRUPTED",
}

STAGE_TO_STATE = {
    "translate": "TRANSLATING",
    "polish": "TRANSLATING",
    "rewrite": "TRANSLATING",
    "qa": "QA_CHECKING",
    "tts": "GENERATING_TTS",
    "import": "LOADING_SOURCE",
    "export": "EXPORTING",
    "preparing_backup": "PREPARING_BACKUP",
    "writing_backup": "WRITING_BACKUP",
    "validating_backup": "VALIDATING_BACKUP",
    "encrypting_backup": "ENCRYPTING_BACKUP",
    "publishing_backup": "PUBLISHING_BACKUP",
}


def normalize_job_state(status: str, *, current_step: str = "", existing_state: str = "") -> str:
    normalized_status = (status or "").strip().lower()
    if normalized_status in {"completed", "failed", "cancelled", "canceled", "interrupted"}:
        return STATUS_TO_STATE[normalized_status]

    step = (current_step or "").strip().upper()
    if step in CANONICAL_JOB_STATES:
        return step

    state = (existing_state or "").strip().upper()
    if state in CANONICAL_JOB_STATES:
        return state
    return STATUS_TO_STATE.get(normalized_status, "QUEUED")


def state_for_stage(stage: str, status: str = "running") -> str:
    normalized_status = (status or "").strip().lower()
    if normalized_status in {"failed", "completed", "cancelled", "canceled"}:
        return STATUS_TO_STATE.get(normalized_status, "CLAIMED")
    return STAGE_TO_STATE.get((stage or "").strip().lower(), "CLAIMED")


def is_valid_job_state_transition(previous_state: str, next_state: str) -> bool:
    previous = normalize_job_state("", existing_state=previous_state)
    next_value = normalize_job_state("", existing_state=next_state)
    if previous == next_value:
        return True
    return next_value in ALLOWED_JOB_STATE_TRANSITIONS.get(previous, set())
