# backend/app/api/audit.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import UserModel, AuditLogModel

router = APIRouter()

class AuditResponse(BaseModel):
    audit_id: str
    action_type: str
    payload_digest: str
    details: str
    created_at: str

@router.get("/audit", response_model=list[AuditResponse])
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
    return [
        AuditResponse(
            audit_id=r.audit_id,
            action_type=r.action_type,
            payload_digest=r.payload_digest,
            details=r.details,
            created_at=r.created_at.isoformat()
        )
        for r in records
    ]