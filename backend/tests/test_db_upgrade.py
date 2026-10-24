# backend/tests/test_db_upgrade.py
"""P3 + P2: databases created before the MFA lifecycle must upgrade in place without data loss."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from contracts.enums import ActionStatus
from app.api import approvals
from app.db import seed
from app.db.models import AccountModel, ActionApprovalModel, UserModel
from app.db.upgrade import upgrade_schema

MFA_COLUMNS = {"mfa_issued_at", "mfa_expires_at", "mfa_consumed_at", "audit_id"}

# action_approvals exactly as created before commit 680ae1a (P3 MFA lifecycle)
PRE_MFA_SCHEMA = [
    """CREATE TABLE users (
        user_id VARCHAR(64) PRIMARY KEY, username VARCHAR(100) NOT NULL,
        is_locked BOOLEAN NOT NULL, created_at DATETIME NOT NULL)""",
    """CREATE TABLE accounts (
        account_id VARCHAR(64) PRIMARY KEY, user_id VARCHAR(64) NOT NULL REFERENCES users(user_id),
        account_number VARCHAR(32) NOT NULL UNIQUE, currency VARCHAR(3) NOT NULL,
        balance NUMERIC(18, 2) NOT NULL, daily_transfer_total NUMERIC(18, 2) NOT NULL,
        created_at DATETIME NOT NULL)""",
    """CREATE TABLE action_approvals (
        action_id VARCHAR(64) PRIMARY KEY, proposal_id VARCHAR(64), user_id VARCHAR(64) NOT NULL,
        tool VARCHAR(64) NOT NULL, tier VARCHAR(16) NOT NULL, payload_json TEXT NOT NULL,
        action_digest VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL,
        verification_code VARCHAR(16), failed_attempts NUMERIC(2, 0) NOT NULL,
        created_at DATETIME NOT NULL, expires_at DATETIME NOT NULL)""",
]


@pytest.fixture
def old_db(tmp_path, monkeypatch):
    """A file-based SQLite DB with the pre-MFA schema and some existing user data."""
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    now, exp = now_dt.isoformat(" "), (now_dt + timedelta(minutes=10)).isoformat(" ")
    with engine.begin() as conn:
        for ddl in PRE_MFA_SCHEMA:
            conn.execute(text(ddl))
        conn.execute(text("INSERT INTO users VALUES ('usr_demo_01', 'Alice Wang', 0, :now)"), {"now": now})
        conn.execute(text(
            "INSERT INTO accounts VALUES ('acc_cny_001', 'usr_demo_01', '6222021001009988', 'CNY', "
            "14750.00, 500.00, :now)"), {"now": now})
        # A RED action left waiting for MFA by the old build (code stored, no challenge metadata)
        conn.execute(text(
            "INSERT INTO action_approvals VALUES ('act_old_red', 'prop_old', 'usr_demo_01', "
            "'request_transfer', 'RED', :payload, :digest, 'PENDING_MFA', '123456', 0, :now, :exp)"),
            {"payload": '{"source_account_id": "acc_cny_001", "recipient_id": "rcp_bob", "amount": "500.00"}',
             "digest": "0" * 64, "now": now, "exp": exp})
    monkeypatch.setattr(seed, "engine", engine)
    monkeypatch.setattr(seed, "SessionLocal", sessionmaker(bind=engine))
    yield engine
    engine.dispose()


def _columns(engine, table="action_approvals") -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_fresh_database_needs_no_upgrade(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(seed, "engine", engine)
    monkeypatch.setattr(seed, "SessionLocal", sessionmaker(bind=engine))
    try:
        seed.seed_database()
        assert MFA_COLUMNS <= _columns(engine)
        assert upgrade_schema(engine) == []
    finally:
        engine.dispose()


def test_startup_upgrades_pre_mfa_database_and_preserves_data(old_db):
    assert not (MFA_COLUMNS & _columns(old_db))

    seed.seed_database()

    assert MFA_COLUMNS <= _columns(old_db)
    with seed.SessionLocal() as db:
        # Existing data untouched; seed did not inject fixtures into a populated DB
        assert db.query(UserModel).count() == 1
        account = db.get(AccountModel, "acc_cny_001")
        assert account.balance == Decimal("14750.00")
        assert account.daily_transfer_total == Decimal("500.00")
        old = db.get(ActionApprovalModel, "act_old_red")
        assert old.status == ActionStatus.PENDING_MFA.value
        assert old.verification_code == "123456"
        assert old.mfa_expires_at is None and old.audit_id is None


def test_upgrade_is_idempotent_across_restarts(old_db):
    seed.seed_database()
    seed.seed_database()  # second restart
    assert upgrade_schema(old_db) == []
    assert MFA_COLUMNS <= _columns(old_db)


def test_old_pending_mfa_row_cannot_execute_after_upgrade(old_db):
    """A pre-upgrade code has no expiry/issue metadata, so it must not be accepted."""
    seed.seed_database()
    with seed.SessionLocal() as db:
        user = db.get(UserModel, "usr_demo_01")
        with pytest.raises(HTTPException) as exc:
            approvals.verify_action(
                "act_old_red", approvals.VerifyActionRequest(verification_code="123456"), user=user, db=db,
            )
        assert exc.value.status_code == 400
        assert "no verification challenge" in exc.value.detail.lower()
        assert db.get(AccountModel, "acc_cny_001").balance == Decimal("14750.00")


def test_missing_not_null_column_is_reported_not_guessed(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'broken.db'}")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE users (user_id VARCHAR(64) PRIMARY KEY, username VARCHAR(100) NOT NULL)"))
        with pytest.raises(RuntimeError, match="users.is_locked"):
            upgrade_schema(engine)
        assert _columns(engine, "users") == {"user_id", "username"}
    finally:
        engine.dispose()
