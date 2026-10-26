"""Backend-resolved context shared by chat and verified-result continuation."""
from app.config import settings
from app.services.adapters import build_tool_catalog
from app.services.subscriptions import selected_account, stored_records


def trusted_agent_context(db, user):
    db.refresh(user)
    account = selected_account(db, user.user_id)
    account_id = account.account_id if account else None
    demo = (build_tool_catalog()[0]["context"]
            if user.user_id == settings.DEFAULT_DEMO_USER_ID else {})
    return account, dict(
        account_id=account_id, account_locked=user.is_locked,
        recipients=[r for r in demo.get("recipients", []) if r["user_id"] == user.user_id],
        subscriptions=[s.model_dump(mode="json") for s in stored_records(db, user.user_id, account_id)],
    )
