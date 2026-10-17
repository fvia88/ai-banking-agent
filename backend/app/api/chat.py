# backend/app/api/chat.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from contracts.models import ChatInput, ChatOutput, BankingContext
from contracts.enums import ActionStatus
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import UserModel, AccountModel
from app.services.adapters import agent_service
from app.services.actions import create_action_record

router = APIRouter()

@router.post("/chat", response_model=ChatOutput)
def handle_chat(
    chat_input: ChatInput,
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if user.is_locked:
        raise HTTPException(status_code=403, detail="Account is locked. State-changing actions blocked.")

    # 1. Generate proposal via adapter
    result = agent_service.process(chat_input)

    # 2. If the AI proposed an action, save it to the DB with a cryptographic digest
    if result.proposals:
        primary_account = db.query(AccountModel).filter(AccountModel.user_id == user.user_id).first()
        source_account_id = primary_account.account_id if primary_account else "acc_cny_001"
        balance_str = f"{primary_account.balance:.2f}" if primary_account else "0.00"
        daily_total_str = f"{primary_account.daily_transfer_total:.2f}" if primary_account else "0.00"

        context = BankingContext(
            user_id=user.user_id,
            account_id=source_account_id,
            daily_transfer_total=daily_total_str,
            account_balance=balance_str,
            account_locked=user.is_locked
        )

        for proposal in result.proposals:
            action_record, digest, tier = create_action_record(
                user_id=user.user_id,
                proposal=proposal,
                source_account_id=source_account_id,
                context=context
            )
            db.add(action_record)
            
            proposal.arguments["action_id"] = action_record.action_id
            proposal.arguments["action_digest"] = digest
            proposal.arguments["tier"] = tier

        db.commit()
        status = ActionStatus.PENDING_CONFIRMATION
    else:
        status = ActionStatus.COMPLETED

    return ChatOutput(
        conversation_id=chat_input.conversation_id,
        reply=result.reply,
        actions=result.proposals,
        status=status
    )