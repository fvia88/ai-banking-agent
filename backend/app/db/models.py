# backend/app/db/models.py
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, Integer, Numeric, Date, DateTime, ForeignKey, Text
from app.services.daily_transfers import banking_day
from sqlalchemy.orm import relationship
from app.db.session import Base

class UserModel(Base):
    __tablename__ = "users"
    
    user_id = Column(String(64), primary_key=True)
    username = Column(String(100), nullable=False)
    is_locked = Column(Boolean, default=False, nullable=False)
    security_failure_count = Column(Integer, default=0, server_default="0", nullable=False)
    security_failure_window_at = Column(DateTime, nullable=True)
    safety_locked_at = Column(DateTime, nullable=True)
    safety_lock_reason = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    accounts = relationship("AccountModel", back_populates="user", cascade="all, delete-orphan")

class AccountModel(Base):
    __tablename__ = "accounts"
    
    account_id = Column(String(64), primary_key=True)
    user_id = Column(String(64), ForeignKey("users.user_id"), nullable=False)
    account_number = Column(String(32), unique=True, nullable=False)
    currency = Column(String(3), default="CNY", nullable=False)
    balance = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    daily_transfer_total = Column(Numeric(18, 2), default=Decimal("0.00"), nullable=False)
    daily_transfer_date = Column(Date, default=lambda: banking_day(), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("UserModel", back_populates="accounts")
    transactions = relationship("TransactionModel", back_populates="account", cascade="all, delete-orphan")

class TransactionModel(Base):
    __tablename__ = "transactions"
    
    transaction_id = Column(String(64), primary_key=True)
    account_id = Column(String(64), ForeignKey("accounts.account_id"), nullable=False)
    timestamp = Column(String(32), nullable=False)  # ISO 8601 string
    amount = Column(Numeric(18, 2), nullable=False)
    direction = Column(String(8), nullable=False)   # 'debit' | 'credit'
    merchant = Column(String(128), nullable=False)
    category = Column(String(64), nullable=False)

    account = relationship("AccountModel", back_populates="transactions")

class SubscriptionModel(Base):
    __tablename__ = "subscriptions"

    subscription_id = Column(String(128), primary_key=True)
    user_id = Column(String(64), ForeignKey("users.user_id"), nullable=False)
    account_id = Column(String(64), ForeignKey("accounts.account_id"), nullable=False)
    merchant = Column(String(128), nullable=False)
    estimated_amount = Column(Numeric(16, 2), nullable=False)
    cadence = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="active")
    cancellation_supported = Column(Boolean, nullable=False, default=False)
    cancelled_at = Column(DateTime, nullable=True)


class AuditLogModel(Base):
    __tablename__ = "audit_logs"
    
    audit_id = Column(String(64), primary_key=True)
    action_id = Column(String(64), nullable=True)
    user_id = Column(String(64), nullable=False)
    action_type = Column(String(64), nullable=False)
    payload_digest = Column(String(128), nullable=False)
    reason_code = Column(String(64), default="SUCCESS", nullable=False)
    details = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

class ActionApprovalModel(Base):
    __tablename__ = "action_approvals"

    action_id = Column(String(64), primary_key=True)
    proposal_id = Column(String(64), nullable=True)
    user_id = Column(String(64), nullable=False)
    tool = Column(String(64), nullable=False)
    tier = Column(String(16), default="YELLOW", nullable=False)
    payload_json = Column(Text, nullable=False)
    action_digest = Column(String(64), nullable=False)  # SHA-256 hex
    status = Column(String(32), default="PENDING_CONFIRMATION", nullable=False)
    verification_code = Column(String(16), nullable=True)  # Simulated OTP for RED tier
    failed_attempts = Column(Numeric(2, 0), default=0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    # P3 MFA challenge lifecycle (see app/services/mfa.py)
    mfa_issued_at = Column(DateTime, nullable=True)
    mfa_expires_at = Column(DateTime, nullable=True)
    mfa_consumed_at = Column(DateTime, nullable=True)
    audit_id = Column(String(64), nullable=True)  # Execution or explicit cancellation audit, returned on replay
    conversation_id = Column(String(128), nullable=True)
    continuation_status = Column(String(32), nullable=True)
    continuation_json = Column(Text, nullable=True)


class ConversationModel(Base):
    __tablename__ = "agent_conversations"

    user_id = Column(String(64), primary_key=True)
    conversation_id = Column(String(128), primary_key=True)
    state_json = Column(Text, nullable=False)
