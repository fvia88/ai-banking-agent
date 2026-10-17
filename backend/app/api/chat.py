# backend/app/api/chat.py
from fastapi import APIRouter, Depends
from contracts.models import ChatInput, ChatOutput
from contracts.enums import ActionStatus
from app.api.deps import get_current_user
from app.db.models import UserModel
from app.services.adapters import agent_service

router = APIRouter()

@router.post("/chat", response_model=ChatOutput)
def handle_chat(
    chat_input: ChatInput,
    user: UserModel = Depends(get_current_user)
):
    # LLM proposals are generated statelessly via the adapter;
    # execution is strictly separated and triggered via /actions/{id}/confirm later.
    result = agent_service.process(chat_input)
    
    status = ActionStatus.PROPOSED if result.proposals else ActionStatus.COMPLETED
    
    return ChatOutput(
        conversation_id=chat_input.conversation_id,
        reply=result.reply,
        actions=result.proposals,
        status=status
    )