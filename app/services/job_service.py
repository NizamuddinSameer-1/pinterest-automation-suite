"""
Job Service — state machine enforcement for generation jobs.

Validates state transitions and prevents invalid operations.
"""

from __future__ import annotations

# Valid state transitions
TRANSITIONS: dict[str, list[str]] = {
    "DRAFT": ["ANALYZED", "FAILED"],
    "ANALYZED": ["PRODUCT_MATCHED", "FAILED"],
    "PRODUCT_MATCHED": ["SCENE_READY", "FAILED"],
    "SCENE_READY": ["PROMPT_READY", "FAILED"],
    "PROMPT_READY": ["GENERATING", "WAITING_FOR_FLOW", "FAILED"],
    # GENERATING is written while a Google Flow / pollinations run is in flight.
    # It was previously assigned by the API but missing from this dict, so any
    # later validate_transition() call from GENERATING raised
    # InvalidTransitionError and the job could never legally move on.
    "GENERATING": ["OUTPUT_UPLOADED", "WAITING_FOR_FLOW", "FAILED"],
    "WAITING_FOR_FLOW": ["OUTPUT_UPLOADED", "FAILED"],
    "OUTPUT_UPLOADED": ["CRITIQUED", "FAILED"],
    "CRITIQUED": ["PASS", "REWORK", "FAILED"],
    "PASS": ["PIN_DRAFT", "FAILED"],
    "REWORK": ["PROMPT_READY", "FAILED"],
    "PIN_DRAFT": ["APPROVED", "REJECTED", "FAILED"],
    "APPROVED": ["EXPORTED"],
    "REJECTED": [],
    "EXPORTED": [],
    "FAILED": ["DRAFT"],  # Can retry from DRAFT
}

# Every state the machine knows about, for validating stored values.
ALL_STATES: frozenset[str] = frozenset(TRANSITIONS)

# States that require specific prerequisites
PREREQUISITES: dict[str, list[str]] = {
    "SCENE_READY": ["visual_dna_id"],  # Must have DNA before scene
    "PROMPT_READY": ["scene_json"],  # Must have scene before prompt
    "CRITIQUED": [],  # Must have outputs (checked in API)
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(
            f"Cannot transition from '{current}' to '{target}'. "
            f"Allowed: {TRANSITIONS.get(current, [])}"
        )


def validate_transition(current_state: str, target_state: str) -> bool:
    """
    Check if a state transition is valid.

    Raises:
        InvalidTransitionError if the transition is not allowed.
    """
    allowed = TRANSITIONS.get(current_state, [])
    if target_state not in allowed:
        raise InvalidTransitionError(current_state, target_state)
    return True


def can_compile_prompt(job_state: str) -> bool:
    """Check if prompt compilation is allowed for the current state."""
    return job_state in ("SCENE_READY", "REWORK")


def can_upload_outputs(job_state: str) -> bool:
    """
    Check if output upload is allowed.

    GENERATING is included because that is the state a job sits in while the
    Flow subprocess runs, and the subprocess is what uploads the outputs.
    """
    return job_state in ("WAITING_FOR_FLOW", "PROMPT_READY", "GENERATING")


def can_run_critique(job_state: str) -> bool:
    """Check if critique can run."""
    return job_state == "OUTPUT_UPLOADED"
