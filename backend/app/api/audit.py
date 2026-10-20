# backend/app/api/audit.py
from datetime import timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from contracts.api_schemas import AuditResponse, AuditEvent
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import UserModel, AuditLogModel

router = APIRouter()

@router.get("/audit", response_model=AuditResponse)
def get_audit_trail(
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    records = (
        db.query(AuditLogModel)
        .filter(AuditLogModel.user_id == user.user_id)
        .order_by(AuditLogModel.created_at.desc())
        .all()
    )
    
    parsed_events = []
    for r in records:
        ts = r.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        parsed_events.append(
            AuditEvent(
                audit_id=r.audit_id,
                action_id=r.action_id or "act_system",
                event_type=r.action_type,
                timestamp=ts,
                reason_code=r.reason_code or "SUCCESS"
            )
        )

    return AuditResponse(events=parsed_events)