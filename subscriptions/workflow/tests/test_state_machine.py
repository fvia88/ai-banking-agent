import pytest

from contracts.enums import ActionStatus
from subscriptions.workflow.state_machine import (
    TERMINAL_STATES,
    transition,
)

S = ActionStatus


def test_proposed_can_wait_for_confirmation():
    assert transition(S.PROPOSED, S.PENDING_CONFIRMATION) == S.PENDING_CONFIRMATION


def test_cannot_skip_confirmation_from_proposed():
    with pytest.raises(ValueError):
        transition(S.PROPOSED, S.COMPLETED)


@pytest.mark.parametrize("terminal", sorted(TERMINAL_STATES, key=lambda s: s.value))
def test_terminal_states_cannot_restart(terminal):
    with pytest.raises(ValueError):
        transition(terminal, S.PENDING_CONFIRMATION)