# backend/app/services/session_store.py
"""Single-process demo sessions; snapshots are copied and turns are serialized.

Memory is lost on restart and is not shared across backend worker processes.
This does not implement database action/execution idempotency.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from threading import RLock
from typing import Any, Iterator

# In-memory session store mapping conversation_id -> conversation state dict
_CONVERSATION_STORE: dict[str, dict[str, Any]] = {}
# A bounded set of reentrant locks also lets get/set run inside a locked turn.
# Hash collisions may serialize unrelated sessions, but cannot mix their data.
_SESSION_LOCKS = tuple(RLock() for _ in range(64))


def conversation_key(user_id: str, conversation_id: str) -> str:
    """Unambiguous key built from backend-resolved identity, never message text."""
    return json.dumps(["p1", user_id, conversation_id])


@contextmanager
def conversation_session(key: str) -> Iterator[None]:
    """Hold across the entire load -> process -> save sequence, not just set()."""
    with _SESSION_LOCKS[hash(key) % len(_SESSION_LOCKS)]:
        yield

def get_conversation_state(conversation_id: str) -> dict[str, Any]:
  """Retrieves any active session memory for this conversation."""
  with conversation_session(conversation_id):
    return deepcopy(_CONVERSATION_STORE.get(conversation_id, {}))

def set_conversation_state(conversation_id: str, state: dict[str, Any]) -> None:
  """Saves session memory for this conversation."""
  with conversation_session(conversation_id):
    _CONVERSATION_STORE[conversation_id] = deepcopy(state)

def clear_conversation_state(conversation_id: str) -> None:
  """Remove a whole session; real P1 draft abandonment saves returned state instead."""
  with conversation_session(conversation_id):
    _CONVERSATION_STORE.pop(conversation_id, None)
