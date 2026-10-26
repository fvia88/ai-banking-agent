# backend/app/services/session_store.py
"""Copied demo snapshots; real P1 turns also use durable, owner-scoped DB state."""
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


def lock_conversation(db, user_id: str, conversation_id: str):
    """Serialize real turns across workers. Caller owns commit/rollback.

    The conflict-safe insert reserves SQLite's writer as well; PostgreSQL uses
    the row lock. Financial execution never acquires this conversation lock.
    """
    from app.db.models import ConversationModel
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(insert(ConversationModel).values(
        user_id=user_id, conversation_id=conversation_id, state_json="{}",
    ).on_conflict_do_nothing(index_elements=["user_id", "conversation_id"]))
    return db.query(ConversationModel).filter_by(
        user_id=user_id, conversation_id=conversation_id,
    ).populate_existing().with_for_update().one()
