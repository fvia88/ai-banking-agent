"""Operation lifecycle rules (state machine only; no money moves here)."""
from contracts.enums import ActionStatus

S = ActionStatus

ALLOWED_TRANSITIONS: dict[ActionStatus, set[ActionStatus]] = {
    S.PROPOSED: {S.PENDING_CONFIRMATION, S.PENDING_MFA, S.REJECTED},
    S.PENDING_CONFIRMATION: {
        S.PENDING_MFA, S.COMPLETED, S.REJECTED, S.FAILED, S.CANCELLED,
    },
    S.PENDING_MFA: {S.COMPLETED, S.REJECTED, S.FAILED, S.CANCELLED},
    S.COMPLETED: set(),
    S.REJECTED: set(),
    S.FAILED: set(),
    S.CANCELLED: set(),
}

TERMINAL_STATES = {S.COMPLETED, S.REJECTED, S.FAILED, S.CANCELLED}


def transition(current: ActionStatus, target: ActionStatus) -> ActionStatus:
    """Return target if the move is legal, otherwise raise ValueError."""
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"Invalid transition: {current.value} -> {target.value}")
    return target