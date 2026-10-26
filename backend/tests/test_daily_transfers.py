"""Shanghai day boundaries through real P1/P4 and the guarded approval routes."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.api import approvals
from app.db.models import AccountModel, ActionApprovalModel, AuditLogModel, TransactionModel
from app.services import daily_transfers, mfa
from app.services.adapters import agent_service, policy_service


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    state = {"now": datetime(2026, 10, 26, 15, 59, tzinfo=timezone.utc)}
    monkeypatch.setattr(daily_transfers, "utc_now", lambda: state["now"])
    monkeypatch.setattr(mfa, "utc_now", lambda: state["now"])
    monkeypatch.setattr(agent_service, "use_mock", False)
    monkeypatch.setattr(policy_service, "use_mock", False)
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    return state


def account(db):
    return db.get(AccountModel, "acc_cny_001")


def propose(client, db, clock):
    result = client.post("/api/v1/chat", json={"conversation_id": uuid4().hex, "message": "Transfer 500 CNY to Bob"})
    assert result.status_code == 200
    action = result.json()["actions"][0]
    db.get(ActionApprovalModel, action["approval"]["action_id"]).expires_at = clock["now"] + timedelta(minutes=10)
    db.commit()
    return action


def confirm(client, action):
    return client.post(f'/api/v1/actions/{action["approval"]["action_id"]}/confirm', json={
        "idempotency_key": "test_request",
        "confirmation_id": "daily_test", "action_digest": action["approval"]["action_digest"],
    })


def code(client, action):
    return next(row["code"] for row in client.get("/api/v1/demo/otp-inbox").json()
                if row["action_id"] == action["approval"]["action_id"])


def verify(client, action, otp):
    return client.post(f'/api/v1/actions/{action["approval"]["action_id"]}/verify', json={"idempotency_key": "test_request", "verification_code": otp})


def reset_count(db):
    return db.query(AuditLogModel).filter_by(action_type="DAILY_TRANSFER_TOTAL_RESET").count()


@pytest.mark.parametrize("instant, expected", [
    ("2026-10-26T15:59:59+00:00", date(2026, 10, 26)),
    ("2026-10-26T16:00:00+00:00", date(2026, 10, 27)),
    ("2026-12-31T16:00:00+00:00", date(2027, 1, 1)),
    ("2028-02-28T16:00:00+00:00", date(2028, 2, 29)),
    ("2026-10-27T00:00:00+08:00", date(2026, 10, 27)),
])
def test_shanghai_boundaries(instant, expected):
    assert daily_transfers.banking_day(datetime.fromisoformat(instant)) == expected


def test_naive_time_is_not_accepted():
    with pytest.raises(ValueError, match="timezone"):
        daily_transfers.banking_day(datetime(2026, 10, 26))


def test_old_total_is_read_as_zero_and_reset_atomically_on_execution(client, db_session, clock):
    row = account(db_session)
    row.daily_transfer_total = Decimal("800.00")
    row.daily_transfer_date = date(2026, 10, 25)
    db_session.commit()
    action = propose(client, db_session, clock)
    assert action["approval"]["tier"] == "YELLOW"
    assert row.daily_transfer_total == Decimal("800.00")  # Proposal did not write a reset.
    assert confirm(client, action).json()["status"] == "COMPLETED"
    assert row.daily_transfer_date == date(2026, 10, 26)
    assert row.daily_transfer_total == Decimal("500.00")
    assert row.balance == Decimal("14750.00") and reset_count(db_session) == 1
    assert confirm(client, action).json()["status"] == "COMPLETED"
    assert row.daily_transfer_total == Decimal("500.00") and reset_count(db_session) == 1


def test_same_day_counter_is_preserved_and_requires_mfa(client, db_session, clock):
    row = account(db_session)
    row.daily_transfer_total = Decimal("800.00")
    db_session.commit()
    action = propose(client, db_session, clock)
    assert action["approval"]["tier"] == "RED"
    assert confirm(client, action).json()["status"] == "PENDING_MFA"
    assert row.balance == Decimal("15250.00") and row.daily_transfer_total == Decimal("800.00")
    assert verify(client, action, code(client, action)).json()["status"] == "COMPLETED"
    assert row.daily_transfer_total == Decimal("1300.00") and reset_count(db_session) == 0


def test_yellow_proposed_yesterday_rechecks_todays_counter(client, db_session, clock):
    action = propose(client, db_session, clock)
    row = account(db_session)
    row.daily_transfer_total = Decimal("900.00")
    db_session.commit()
    clock["now"] = datetime(2026, 10, 26, 16, 0, tzinfo=timezone.utc)
    assert confirm(client, action).json()["status"] == "COMPLETED"
    assert row.daily_transfer_date == date(2026, 10, 27)
    assert row.daily_transfer_total == Decimal("500.00")


def test_red_proposal_is_not_downgraded_after_midnight(client, db_session, clock):
    row = account(db_session)
    row.daily_transfer_total = Decimal("800.00")
    db_session.commit()
    action = propose(client, db_session, clock)
    clock["now"] = datetime(2026, 10, 26, 16, 0, tzinfo=timezone.utc)
    assert confirm(client, action).json()["status"] == "PENDING_MFA"
    assert row.daily_transfer_date == date(2026, 10, 27)
    assert row.daily_transfer_total == Decimal("0.00") and row.balance == Decimal("15250.00")


def test_mfa_verified_after_midnight_counts_in_new_day(client, db_session, clock):
    row = account(db_session)
    row.daily_transfer_total = Decimal("800.00")
    db_session.commit()
    action = propose(client, db_session, clock)
    assert confirm(client, action).json()["status"] == "PENDING_MFA"
    otp = code(client, action)
    clock["now"] = datetime(2026, 10, 26, 16, 0, tzinfo=timezone.utc)
    assert verify(client, action, otp).json()["status"] == "COMPLETED"
    assert row.daily_transfer_date == date(2026, 10, 27) and row.daily_transfer_total == Decimal("500.00")
    ledger = db_session.query(TransactionModel).filter_by(category="Transfers").one()
    assert daily_transfers.banking_day(datetime.fromisoformat(ledger.timestamp)) == row.daily_transfer_date


def test_midnight_between_policy_and_executor_uses_one_booking_instant(client, db_session, clock, monkeypatch):
    clock["now"] = datetime(2026, 10, 26, 15, 59, 59, tzinfo=timezone.utc)
    action = propose(client, db_session, clock)
    execute = approvals.execute_transfer
    def cross_midnight(*args):
        clock["now"] = datetime(2026, 10, 26, 16, 0, tzinfo=timezone.utc)
        return execute(*args)
    monkeypatch.setattr(approvals, "execute_transfer", cross_midnight)
    assert confirm(client, action).json()["status"] == "COMPLETED"
    row = account(db_session)
    ledger = db_session.query(TransactionModel).filter_by(category="Transfers").one()
    assert row.daily_transfer_date == daily_transfers.banking_day(datetime.fromisoformat(ledger.timestamp)) == date(2026, 10, 26)
    monkeypatch.setattr(approvals, "execute_transfer", execute)
    second = propose(client, db_session, clock)
    assert confirm(client, second).json()["status"] == "COMPLETED"
    assert row.daily_transfer_date == date(2026, 10, 27) and row.daily_transfer_total == Decimal("500.00")


def test_failed_execution_rolls_back_reset_and_financial_writes(client, db_session, clock, monkeypatch):
    row = account(db_session)
    row.daily_transfer_date, row.daily_transfer_total = date(2026, 10, 25), Decimal("800.00")
    db_session.commit()
    action = propose(client, db_session, clock)
    execute = approvals.execute_transfer
    def crash(*args):
        execute(*args)
        raise RuntimeError("Simulated rollover failure")
    monkeypatch.setattr(approvals, "execute_transfer", crash)
    with pytest.raises(RuntimeError, match="rollover failure"):
        confirm(client, action)
    db_session.expire_all()
    assert row.daily_transfer_date == date(2026, 10, 25) and row.daily_transfer_total == Decimal("800.00")
    assert row.balance == Decimal("15250.00") and reset_count(db_session) == 0
    monkeypatch.setattr(approvals, "execute_transfer", execute)
    assert confirm(client, action).json()["status"] == "COMPLETED"
    assert row.daily_transfer_total == Decimal("500.00") and reset_count(db_session) == 1


def test_clock_cannot_reset_counter_backwards(client, db_session, clock):
    row = account(db_session)
    row.daily_transfer_date, row.daily_transfer_total = date(2026, 10, 27), Decimal("800.00")
    db_session.commit()
    action = propose(client, db_session, clock)
    response = confirm(client, action)
    assert response.status_code == 409 and "clock" in response.json()["detail"].lower()
    assert row.daily_transfer_date == date(2026, 10, 27) and row.daily_transfer_total == Decimal("800.00")
    assert row.balance == Decimal("15250.00")
