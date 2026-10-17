# backend/app/api/deps.py (dependencies)
from fastapi import Header, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.config import settings
from app.db.session import get_db
from app.db.models import UserModel

def get_current_user(
    x_demo_user_id: str | None = Header(default=None),
    db: Session = Depends(get_db)
) -> UserModel:
    # Fallback to configured demo user if header is not passed
    user_id = x_demo_user_id or settings.DEFAULT_DEMO_USER_ID
    user = db.query(UserModel).filter(UserModel.user_id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid demo session for user_id: {user_id}"
        )
    return user