"""Safety regressions for concurrent Yellow confirmations.

Each worker calls the real confirm route function with its own SQLAlchemy
session/connection. A test-only before_flush rendezvous exposes the window
after in-memory debit calculation but before database writes. No executor or
policy result is replaced. The rendezvous times out harmlessly if a future
locking implementation correctly prevents the second worker reaching it.

These safety regressions were reproduced before the execution guard was added.
They run on file-backed SQLite and optional uniquely named disposable PostgreSQL
databases; set MIGRATION_TEST_POSTGRES_ADMIN_URL to enable the latter.
"""
from collections import Counter
from decimal import Decimal
import json
import threading
import os
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from contracts.models import ActionProposal, BankingContext
from app.api.approvals import ConfirmActionRequest, VerifyActionRequest, confirm_action, verify_action
from app.db.models import AccountModel, ActionApprovalModel, AuditLogModel, TransactionModel, UserModel
from app.db.session import Base
from app.services.actions import create_action_record
from app.services.adapters import policy_service


@pytest.fixture(params=["sqlite", "postgresql"])
def race_database(tmp_path, monkeypatch, request):
    monkeypatch.setattr(policy_service, "use_mock", False)
    admin = None
    if request.param == "sqlite":
        engine = create_engine(
            f"sqlite:///{(tmp_path / 'yellow_race.db').as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 5},
        )
    else:
        url = os.getenv("MIGRATION_TEST_POSTGRES_ADMIN_URL")
        if not url:
            pytest.skip("Set MIGRATION_TEST_POSTGRES_ADMIN_URL for disposable PostgreSQL race tests")
        database = "approval_race_" + uuid4().hex
        admin = create_engine(url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        engine = create_engine(make_url(url).set(database=database))
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine)
    finally:
        engine.dispose()
        if admin is not None:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{database}"'))
            admin.dispose()


def seed_actions(sessions, starting_balance, amounts, starting_daily=Decimal("0.00")):
    with sessions() as db:
        db.add(UserModel(user_id="race_user", username="Synthetic race user", is_locked=False))
        db.add(AccountModel(
            account_id="race_account", user_id="race_user", account_number="synthetic_race",
            balance=starting_balance, daily_transfer_total=starting_daily, currency="CNY",
        ))
        db.commit()
        context = BankingContext(
            user_id="race_user", account_id="race_account", account_balance=starting_balance,
            daily_transfer_total=starting_daily, account_locked=False,
        )
        actions = []
        for index, amount in enumerate(amounts):
            proposal = ActionProposal(
                proposal_id=f"race_proposal_{index}", tool="request_transfer",
                arguments={"source_account_id": "race_account", "recipient_id": "synthetic_bob",
                           "amount": str(amount), "currency": "CNY"},
            )
            record, digest, tier = create_action_record("race_user", proposal, "race_account", context)
            assert tier == ("RED" if starting_daily + amount > Decimal("1000.00") else "YELLOW")
            db.add(record)
            actions.append((record.action_id, digest))
        db.commit()
        return actions


def run_confirmations(sessions, actions, verify_codes=None):
    barrier = threading.Barrier(len(actions))
    guard = threading.Lock()
    outcomes, arrivals = [], []

    def before_flush(session, flush_context, instances):
        if session.info.get("race_arrived"):
            return
        if not any(isinstance(row, TransactionModel) for row in session.new):
            return
        session.info["race_arrived"] = True
        with guard:
            arrivals.append(session.info["worker"])
        try:
            barrier.wait(timeout=2)
        except threading.BrokenBarrierError:
            # A correct action/account lock may serialize before this point.
            # Let that worker finish rather than deadlocking a correct fix.
            pass

    def worker(index, action):
        action_id, digest = action
        with sessions() as db:
            db.info["worker"] = index
            try:
                user = db.get(UserModel, "race_user")
                if verify_codes and action_id in verify_codes:
                    result = verify_action(action_id, VerifyActionRequest(verification_code=verify_codes[action_id], idempotency_key="test_request"), user=user, db=db)
                else:
                    result = confirm_action(
                        action_id,
                        ConfirmActionRequest(confirmation_id=f"confirmation_{index}",
                                             action_digest=digest, idempotency_key=f"request_{index}"),
                        user=user, db=db,
                    )
                outcome = {"worker": index, "action_id": action_id, "http": 200,
                           "status": result.status.value, "audit_id": result.audit_id}
            except HTTPException as exc:
                db.rollback()
                outcome = {"worker": index, "action_id": action_id,
                           "http": exc.status_code, "detail": exc.detail}
            except Exception as exc:
                db.rollback()
                outcome = {"worker": index, "action_id": action_id, "error": repr(exc)}
            with guard:
                outcomes.append(outcome)

    event.listen(sessions, "before_flush", before_flush)
    threads = [threading.Thread(target=worker, args=(i, action), daemon=True)
               for i, action in enumerate(actions)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=12)
        assert not any(thread.is_alive() for thread in threads), "A confirmation worker did not terminate"
    finally:
        event.remove(sessions, "before_flush", before_flush)
    assert len(outcomes) == len(actions), outcomes
    assert not any("error" in outcome for outcome in outcomes), outcomes
    return sorted(outcomes, key=lambda item: item["worker"]), arrivals


def inspect_result(sessions, outcomes, arrivals, starting_balance, starting_daily=Decimal("0.00")):
    with sessions() as db:
        account = db.get(AccountModel, "race_account")
        ledger = db.query(TransactionModel).filter_by(account_id="race_account").all()
        audits = db.query(AuditLogModel).filter_by(action_type="TRANSFER_EXECUTED_ATOMIC").all()
        actions = db.query(ActionApprovalModel).order_by(ActionApprovalModel.action_id).all()
        total = sum((row.amount for row in ledger), Decimal("0.00"))
        evidence = {
            "outcomes": outcomes, "workers_reaching_preflush_window": len(arrivals),
            "starting_balance": str(starting_balance), "balance": str(account.balance),
            "daily_total": str(account.daily_transfer_total), "ledger_count": len(ledger),
            "ledger_debits": str(total), "execution_audit_count": len(audits),
            "audits_per_action": dict(Counter(row.action_id for row in audits)),
            "actions": [{"id": row.action_id, "status": row.status, "tier": row.tier,
                         "audit_id": row.audit_id} for row in actions],
        }
        violations = []
        if account.balance != starting_balance - total:
            violations.append("Account balance does not reconcile with the committed ledger")
        if account.daily_transfer_total != starting_daily + total:
            violations.append("Daily total does not reconcile with the committed ledger")
        if account.balance < 0 or total > starting_balance:
            violations.append("Committed transfers exceed available funds")
        if len(audits) != len(ledger):
            violations.append("Execution audit and ledger counts differ")
        for action in actions:
            linked = [row for row in audits if row.action_id == action.action_id]
            if len(linked) > 1:
                violations.append("One action has multiple execution audits")
            if action.status == "COMPLETED" and (len(linked) != 1 or action.audit_id != linked[0].audit_id):
                violations.append("Completed action does not identify exactly one execution audit")
            if action.status != "COMPLETED" and linked:
                violations.append("Non-completed action has a committed execution audit")
        return evidence, violations


def assert_safe(evidence, violations):
    assert not violations, "\n" + "\n".join(violations) + "\nEvidence: " + json.dumps(evidence, indent=2)


def test_same_yellow_action_cannot_execute_twice(race_database):
    starting = Decimal("2000.00")
    action = seed_actions(race_database, starting, [Decimal("100.00")])[0]
    outcomes, arrivals = run_confirmations(race_database, [action, action])
    evidence, violations = inspect_result(race_database, outcomes, arrivals, starting)
    if evidence["ledger_count"] != 1:
        violations.append("Duplicate confirmation must create exactly one ledger debit")
    if evidence["balance"] != "1900.00" or evidence["daily_total"] != "100.00":
        violations.append("Duplicate confirmation must deduct and count the amount once")
    if any(result["http"] not in (200, 409) for result in outcomes):
        violations.append("Duplicate request must complete/replay or receive a conflict")
    successful = [result for result in outcomes if result["http"] == 200]
    if not successful or len({result["audit_id"] for result in successful}) != 1:
        violations.append("Successful duplicate replies must identify the same execution audit")
    assert_safe(evidence, violations)


def test_competing_yellow_actions_cannot_bypass_cumulative_mfa(race_database):
    starting = Decimal("2000.00")
    actions = seed_actions(race_database, starting, [Decimal("600.00"), Decimal("600.00")])
    outcomes, arrivals = run_confirmations(race_database, actions)
    evidence, violations = inspect_result(race_database, outcomes, arrivals, starting)
    statuses = sorted(result.get("status", str(result["http"])) for result in outcomes)
    if statuses != ["COMPLETED", "PENDING_MFA"]:
        violations.append("Only one 600 CNY transfer may complete; the other must require MFA")
    if evidence["ledger_count"] != 1 or evidence["balance"] != "1400.00" or evidence["daily_total"] != "600.00":
        violations.append("No second debit may occur before MFA")
    if sorted(row["status"] for row in evidence["actions"]) != ["COMPLETED", "PENDING_MFA"]:
        violations.append("Stored statuses must reflect one completion and one MFA challenge")
    with race_database() as db:
        assert db.query(AuditLogModel).filter_by(action_type="ESCALATED_TO_RED").count() == 1
        assert db.query(AuditLogModel).filter_by(action_type="MFA_CHALLENGE_ISSUED").count() == 1
    assert_safe(evidence, violations)


def test_competing_yellow_actions_cannot_overspend_account(race_database):
    starting = Decimal("500.00")
    actions = seed_actions(race_database, starting, [Decimal("400.00"), Decimal("400.00")])
    outcomes, arrivals = run_confirmations(race_database, actions)
    evidence, violations = inspect_result(race_database, outcomes, arrivals, starting)
    completed = [result for result in outcomes if result.get("status") == "COMPLETED"]
    if len(completed) != 1 or evidence["ledger_count"] != 1:
        violations.append("Only one 400 CNY transfer can complete against 500 CNY")
    if evidence["balance"] != "100.00" or evidence["daily_total"] != "400.00":
        violations.append("Balance and daily total must reflect the one affordable transfer")
    if any(row["status"] not in ("COMPLETED", "FAILED", "REJECTED") for row in evidence["actions"]):
        violations.append("An executor refusal must not leave its action pending")
    assert_safe(evidence, violations)


def issue_mfa(sessions, action):
    action_id, digest = action
    with sessions() as db:
        result = confirm_action(action_id, ConfirmActionRequest(
            confirmation_id="red_confirmation", action_digest=digest,
            idempotency_key="test_request",
        ), user=db.get(UserModel, "race_user"), db=db)
        assert result.status.value == "PENDING_MFA"
        return db.get(ActionApprovalModel, action_id).verification_code


def test_mixed_confirm_and_verify_reconcile_account(race_database):
    starting = Decimal("2000.00")
    red, yellow = seed_actions(race_database, starting, [Decimal("1200.00"), Decimal("600.00")])
    code = issue_mfa(race_database, red)
    outcomes, arrivals = run_confirmations(race_database, [red, yellow], {red[0]: code})
    evidence, violations = inspect_result(race_database, outcomes, arrivals, starting)
    if outcomes[0].get("status") != "COMPLETED":
        violations.append("The already authorized Red verification should complete")
    if outcomes[1].get("status") not in ("COMPLETED", "PENDING_MFA"):
        violations.append("The Yellow action must complete first or escalate after the Red debit")
    if outcomes[1].get("status") == "COMPLETED" and evidence["daily_total"] != "1800.00":
        violations.append("Both committed debits must be reflected in the daily total")
    assert_safe(evidence, violations)


def test_competing_red_verifications_cannot_overspend_account(race_database):
    starting, daily = Decimal("500.00"), Decimal("800.00")
    actions = seed_actions(race_database, starting, [Decimal("400.00"), Decimal("400.00")], daily)
    codes = {action[0]: issue_mfa(race_database, action) for action in actions}
    outcomes, arrivals = run_confirmations(race_database, actions, codes)
    evidence, violations = inspect_result(race_database, outcomes, arrivals, starting, daily)
    if sum(result.get("status") == "COMPLETED" for result in outcomes) != 1:
        violations.append("Only one Red verification can spend the available funds")
    if evidence["balance"] != "100.00" or evidence["daily_total"] != "1200.00":
        violations.append("The account must reflect exactly one 400 CNY debit")
    if sorted(action["status"] for action in evidence["actions"]) != ["COMPLETED", "FAILED"]:
        violations.append("The refused Red action must be retired without a debit")
    assert_safe(evidence, violations)


def test_first_concurrent_transfers_of_new_day_reset_once(race_database, monkeypatch):
    from datetime import timedelta
    from app.services import daily_transfers, mfa
    instant = daily_transfers.utc_now()
    starting = Decimal("2000.00")
    actions = seed_actions(race_database, starting, [Decimal("600.00"), Decimal("600.00")])
    with race_database() as db:
        row = db.get(AccountModel, "race_account")
        row.daily_transfer_date = daily_transfers.banking_day(instant) - timedelta(days=1)
        row.daily_transfer_total = Decimal("800.00")
        db.commit()
    monkeypatch.setattr(daily_transfers, "utc_now", lambda: instant)
    monkeypatch.setattr(mfa, "utc_now", lambda: instant)
    outcomes, arrivals = run_confirmations(race_database, actions)
    evidence, violations = inspect_result(race_database, outcomes, arrivals, starting)
    if sorted(result.get("status", str(result["http"])) for result in outcomes) != ["COMPLETED", "PENDING_MFA"]:
        violations.append("Concurrent rollover must not erase the first new-day debit")
    if evidence["daily_total"] != "600.00" or evidence["ledger_count"] != 1:
        violations.append("Only the first new-day 600 CNY debit may be counted without MFA")
    with race_database() as db:
        assert db.get(AccountModel, "race_account").daily_transfer_date == daily_transfers.banking_day(instant)
        assert db.query(AuditLogModel).filter_by(action_type="DAILY_TRANSFER_TOTAL_RESET").count() == 1
    assert_safe(evidence, violations)
