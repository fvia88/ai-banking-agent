"""Owner-scoped conversation listing and read-only history retrieval."""
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.api.schemas import ConversationSummary, ConversationList, ConversationDetail
from app.db.models import UserModel, ConversationModel, ChatMessageModel
from app.db.session import get_db
from app.services.session_store import lock_conversation
from app.services.chat_history import display_message

router = APIRouter()


def summary(row):
    return dict(conversation_id=row.conversation_id, title=row.title,
                created_at=row.created_at, updated_at=row.updated_at)


@router.post('/conversations', response_model=ConversationSummary, status_code=201)
def create_conversation(user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    row = lock_conversation(db, user.user_id, 'conv_' + uuid4().hex)
    db.commit()
    return summary(row)


@router.get('/conversations', response_model=ConversationList)
def list_conversations(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                       user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(ConversationModel).filter_by(user_id=user.user_id).order_by(
        ConversationModel.updated_at.desc(), ConversationModel.conversation_id).offset(offset).limit(limit + 1).all()
    return dict(conversations=[summary(row) for row in rows[:limit]], has_more=len(rows) > limit)


@router.get('/conversations/{conversation_id}', response_model=ConversationDetail)
def get_conversation(conversation_id: str, before_id: int | None = Query(None, ge=1),
                     limit: int = Query(100, ge=1, le=100),
                     user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(ConversationModel, (user.user_id, conversation_id))
    if row is None:
        raise HTTPException(404, 'Conversation not found')
    query = db.query(ChatMessageModel).filter_by(user_id=user.user_id, conversation_id=conversation_id)
    if before_id is not None:
        query = query.filter(ChatMessageModel.message_id < before_id)
    messages = query.order_by(ChatMessageModel.message_id.desc()).limit(limit + 1).all()
    return dict(conversation=summary(row), has_more=len(messages) > limit,
                messages=[display_message(db, user.user_id, conversation_id, message)
                          for message in reversed(messages[:limit])])
