# backend/app/api/demo_inbox.py
"""
P3: simulated OTP delivery channel ("demo inbox").

Stands in for the user's phone/email during the hackathon demo. Shows only the
authenticated user's own unexpired, unused codes. No SMS/email is sent.
"""
from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import UserModel
from app.services import mfa

router = APIRouter()

class DemoInboxMessage(BaseModel):
    action_id: str
    code: str
    issued_at: datetime
    expires_at: datetime
    attempts_remaining: int
    message: str

@router.get("/demo/otp-inbox", response_model=list[DemoInboxMessage])
def get_demo_otp_inbox(
    user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    now = mfa.utc_now()
    return [
        DemoInboxMessage(
            action_id=record.action_id,
            code=record.verification_code,
            issued_at=mfa.as_utc(record.mfa_issued_at),
            expires_at=mfa.as_utc(record.mfa_expires_at),
            attempts_remaining=mfa.remaining_attempts(record),
            message=f"[Simulated] Your verification code is {record.verification_code}. Do not share it.",
        )
        for record in mfa.active_challenges(db, user.user_id, now)
    ]
