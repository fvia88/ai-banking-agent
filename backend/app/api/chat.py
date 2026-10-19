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

    # 1. Fetch user's account IDs and generate proposal via adapter
    user_accounts = db.query(AccountModel).filter(AccountModel.user_id == user.user_id).all()
    account_ids = [acc.account_id for acc in user_accounts] or ["acc_cny_001"]

    result = agent_service.process(chat_input, account_ids=account_ids)

    # 2. If the AI proposed an action, evaluate policy and save if confirmation is required
    has_pending_actions = False

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
            try:
                action_record, digest, tier = create_action_record(
                    user_id=user.user_id,
                    proposal=proposal,
                    source_account_id=source_account_id,
                    context=context
                )

                # ONLY queue into action_approvals if it requires user confirmation (Yellow/Red)
                if tier in ["YELLOW", "RED"]:
                    db.add(action_record)
                    proposal.arguments["action_id"] = action_record.action_id
                    proposal.arguments["action_digest"] = digest
                    proposal.arguments["tier"] = tier
                    has_pending_actions = True
                else:
                    # GREEN tier: Automatic query, no ticket needed
                    proposal.arguments["tier"] = "GREEN"

            except ValueError as e:
                return ChatOutput(
                    conversation_id=chat_input.conversation_id,
                    reply=f"Action blocked: Your account is currently locked for state-changing operations.",
                    actions=[],
                    status=ActionStatus.REJECTED
                )

        db.commit()
        status = ActionStatus.PENDING_CONFIRMATION if has_pending_actions else ActionStatus.COMPLETED
    else:
        status = ActionStatus.COMPLETED

    return ChatOutput(
        conversation_id=chat_input.conversation_id,
        reply=result.reply,
        actions=result.proposals,
        status=status
    )