"""Display-only transcript storage. Reading history never invokes an agent or executor."""
from datetime import datetime, timezone
import json

from app.db.models import ConversationModel, ChatMessageModel
from app.services.proposals import restore_cached_chat
from app.services.session_store import lock_conversation


def save_message(db, user_id, conversation_id, sender, text, *, response=None, event_key=None):
    row = db.get(ConversationModel, (user_id, conversation_id))
    if row is None:
        row = lock_conversation(db, user_id, conversation_id)
    now = datetime.now(timezone.utc)
    row.updated_at = now
    if sender == 'user' and row.title == 'New chat':
        row.title = ' '.join(text.split())[:80] or 'New chat'
    values = dict(user_id=user_id, conversation_id=conversation_id, sender=sender,
                  text=text, response_json=response.model_dump_json() if response is not None else None,
                  event_key=event_key, created_at=now)
    if event_key is None:
        db.add(ChatMessageModel(**values))
    else:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        insert = pg_insert if db.get_bind().dialect.name == 'postgresql' else sqlite_insert
        db.execute(insert(ChatMessageModel).values(**values).on_conflict_do_nothing(
            index_elements=['user_id', 'conversation_id', 'event_key']))
    db.flush()


def save_turn(db, user_id, chat, response):
    save_message(db, user_id, chat.conversation_id, 'user', chat.message)
    save_message(db, user_id, chat.conversation_id, 'agent', response.reply, response=response)


def display_message(db, user_id, conversation_id, row):
    actions = []
    if row.response_json:
        # Reuse P2's verified ticket restoration: current status, original pure
        # arguments, owned action, matching conversation/digest. No new proposal.
        actions = restore_cached_chat(db, user_id, conversation_id, json.loads(row.response_json)).actions
    return dict(id=row.message_id, sender=row.sender, text=row.text,
                created_at=row.created_at, event_key=row.event_key, actions=actions)
