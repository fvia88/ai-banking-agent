# backend/app/services/session_store.py
from typing import Any

# In-memory session store mapping conversation_id -> conversation state dict
_CONVERSATION_STORE: dict[str, dict[str, Any]] = {}

def get_conversation_state(conversation_id: str) -> dict[str, Any]:
  """Retrieves any active session memory for this conversation."""
  return _CONVERSATION_STORE.get(conversation_id, {})

def set_conversation_state(conversation_id: str, state: dict[str, Any]) -> None:
  """Saves session memory for this conversation."""
  _CONVERSATION_STORE[conversation_id] = state

def clear_conversation_state(conversation_id: str) -> None:
  """Clears memory when a draft is completed or abandoned ('never mind')."""
  _CONVERSATION_STORE.pop(conversation_id, None)