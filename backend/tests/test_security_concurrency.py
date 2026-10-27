"""Deterministic concurrency regression tests for execution-time security invariants.

Uses disposable file-backed SQLite databases under pytest tmp_path with one
independent SQLAlchemy Session per worker thread and threading.Barrier
synchronization at the policy-revalidation boundary.
"""
from datetime import timedelta
from decimal import Decimal
import json
import threading
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import approvals
from app.db.models import (
    AccountModel,
    ActionApprovalModel,
    AuditLogModel,
    TransactionModel,
    UserModel,
)
from app.db.session import Base
from app.services import mfa
from app.services.actions import compute_action_digest
from app.services.adapters import policy_service
from contracts.enums import ActionStatus, Tier, ToolName


def _make_session_factory(tmp_path, db_name: str):
    engine = create_engine(
        f"sqlite:///{tmp_path / db_name}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)


def _make_transfer_record(
    action_id: str,
    amount_str: str,
    now,
    user_id: str = "usr_demo_01",
    source_account_id: str = "acc_cny_001",
    recipient_id: str = "usr_bob_01",
    tier: str = Tier.YELLOW.value,
) -> ActionApprovalModel:
    payload = {
        "source_account_id": source_account_id,
        "recipient_id": recipient_id,
        "amount": amount_str,
        "currency": "CNY",
    }
    digest = compute_action_digest(ToolName.REQUEST_TRANSFER.value, payload)
    return ActionApprovalModel(
        action_id=action_id,
        proposal_id=f"prop_{action_id}",
        user_id=user_id,
        tool=ToolName.REQUEST_TRANSFER.value,
        tier=tier,
        payload_json=json.dumps(payload),
        action_digest=digest,
        status=ActionStatus.PENDING_CONFIRMATION.value,
        failed_attempts=0,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
    )


def test_concurrent_duplicate_yellow_confirm_executes_at_most_once(tmp_path, monkeypatch):
    """Test 1 - Duplicate Yellow confirmation on the same action_id.

    Two independent sessions concurrently confirm the same Yellow transfer action.
    Verifies:
    - At most one transfer execution and debit.
    - Exactly one transfer transaction and one execution audit record.
    - Correct final balance (14,750.00 CNY) and daily transfer total (500.00 CNY).
    - The action is COMPLETED once with a consistent audit ID.
    - The second request either receives a safe 409 Conflict or returns an idempotent result.
    """
    monkeypatch.setattr(policy_service, "use_mock", False)
    engine, SessionFactory = _make_session_factory(tmp_path, "dup_yellow.db")

    try:
        with SessionFactory() as setup:
            setup.add(UserModel(user_id="usr_demo_01", username="Alice Wang", is_locked=False))
            setup.add(
                AccountModel(
                    account_id="acc_cny_001",
                    user_id="usr_demo_01",
                    account_number="6222021001009988",
                    currency="CNY",
                    balance=Decimal("15250.00"),
                    daily_transfer_total=Decimal("0.00"),
                )
            )
            now = mfa.utc_now()
            record = _make_transfer_record("act_dup_yellow", "500.00", now)
            digest = record.action_digest
            setup.add(record)
            setup.commit()

        start_barrier = threading.Barrier(2, timeout=5)
        policy_barrier = threading.Barrier(2, timeout=0.2)
        original_current_policy = approvals._current_policy

        def current_policy_then_wait(*args, **kwargs):
            decision = original_current_policy(*args, **kwargs)
            try:
                policy_barrier.wait()
            except threading.BrokenBarrierError:
                pass
            return decision

        monkeypatch.setattr(approvals, "_current_policy", current_policy_then_wait)

        outcomes: list[tuple[str, object, object]] = []

        def confirm_in_thread(idx: int):
            with SessionFactory() as session:
                try:
                    user = session.query(UserModel).filter_by(user_id="usr_demo_01").first()
                    start_barrier.wait()
                    res = approvals.confirm_action(
                        "act_dup_yellow",
                        approvals.ConfirmActionRequest(
                            confirmation_id=f"conf_dup_{idx}",
                            action_digest=digest,
                        ),
                        user=user,
                        db=session,
                    )
                    outcomes.append(("ok", res.status, res.audit_id))
                except HTTPException as exc:
                    outcomes.append(("http", exc.status_code, exc.detail))
                except Exception as exc:
                    outcomes.append(("error", type(exc).__name__, repr(exc)))
                finally:
                    policy_barrier.abort()

        threads = [threading.Thread(target=confirm_in_thread, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
            assert not t.is_alive(), "Worker thread did not terminate within timeout"

        assert len(outcomes) == 2, f"Expected 2 thread outcomes, got: {outcomes}"
        errors = [o for o in outcomes if o[0] == "error"]
        assert not errors, f"Unexpected worker exceptions: {errors}"

        with SessionFactory() as check:
            acc = check.query(AccountModel).filter_by(account_id="acc_cny_001").first()
            txs = check.query(TransactionModel).filter_by(category="Transfers").all()
            audits = (
                check.query(AuditLogModel)
                .filter_by(action_id="act_dup_yellow", action_type="TRANSFER_EXECUTED_ATOMIC")
                .all()
            )
            stored_action = (
                check.query(ActionApprovalModel).filter_by(action_id="act_dup_yellow").first()
            )

            diag = (
                f"outcomes={outcomes}, tx_count={len(txs)}, audit_count={len(audits)}, "
                f"audit_ids={[a.audit_id for a in audits]}, balance={acc.balance}, "
                f"daily_total={acc.daily_transfer_total}, action_status={stored_action.status}, "
                f"action_audit_id={stored_action.audit_id}"
            )
            assert len(txs) == 1, f"Expected 1 transfer ledger entry: {diag}"
            assert txs[0].amount == Decimal("500.00"), f"Expected 500.00 transfer amount: {diag}"
            assert len(audits) == 1, f"Expected 1 execution audit record: {diag}"
            assert audits[0].reason_code == "TRANSFER_SUCCESS", diag
            assert acc.balance == Decimal("14750.00"), f"Expected balance 14750.00: {diag}"
            assert acc.daily_transfer_total == Decimal("500.00"), (
                f"Expected daily_transfer_total 500.00: {diag}"
            )
            assert stored_action.status == ActionStatus.COMPLETED.value, diag
            assert stored_action.audit_id == audits[0].audit_id, diag

            # Second request must either receive 409 Conflict or return idempotent COMPLETED with same audit_id
            ok_outcomes = [o for o in outcomes if o[0] == "ok"]
            http_outcomes = [o for o in outcomes if o[0] == "http"]
            assert len(ok_outcomes) in (1, 2), f"Expected 1 or 2 COMPLETED outcomes: {diag}"
            assert len(ok_outcomes) + len(http_outcomes) == 2, diag
            for _, status_val, returned_audit_id in ok_outcomes:
                assert status_val == ActionStatus.COMPLETED, diag
                assert returned_audit_id == stored_action.audit_id, diag
            for _, code, _ in http_outcomes:
                assert code == 409, f"Expected 409 Conflict for losing request: {diag}"
    finally:
        engine.dispose()


def test_concurrent_yellow_transfers_cannot_bypass_cumulative_daily_threshold(
    tmp_path, monkeypatch
):
    """Test 2 - Concurrent cumulative daily threshold (600 CNY + 600 CNY > 1,000 CNY).

    Two distinct Yellow actions each transfer 600 CNY while daily_transfer_total
    starts at 0.00 CNY and the threshold is 1,000.00 CNY.
    Verifies:
    - Both actions cannot complete as Yellow without MFA.
    - At most one 600.00 CNY debit occurs during confirmation (balance == 14,650.00 CNY,
      daily_transfer_total == 600.00 CNY).
    - The second action is either escalated to Red / PENDING_MFA or rejected safely (409)
      for retry, with no unauthorized second debit.
    """
    monkeypatch.setattr(policy_service, "use_mock", False)
    engine, SessionFactory = _make_session_factory(tmp_path, "threshold_race.db")

    try:
        with SessionFactory() as setup:
            setup.add(UserModel(user_id="usr_demo_01", username="Alice Wang", is_locked=False))
            setup.add(
                AccountModel(
                    account_id="acc_cny_001",
                    user_id="usr_demo_01",
                    account_number="6222021001009988",
                    currency="CNY",
                    balance=Decimal("15250.00"),
                    daily_transfer_total=Decimal("0.00"),
                )
            )
            now = mfa.utc_now()
            rec1 = _make_transfer_record("act_yellow_600_1", "600.00", now)
            rec2 = _make_transfer_record("act_yellow_600_2", "600.00", now)
            d1, d2 = rec1.action_digest, rec2.action_digest
            setup.add_all([rec1, rec2])
            setup.commit()

        start_barrier = threading.Barrier(2, timeout=5)
        policy_barrier = threading.Barrier(2, timeout=0.2)
        original_current_policy = approvals._current_policy

        def current_policy_then_wait(*args, **kwargs):
            decision = original_current_policy(*args, **kwargs)
            try:
                policy_barrier.wait()
            except threading.BrokenBarrierError:
                pass
            return decision

        monkeypatch.setattr(approvals, "_current_policy", current_policy_then_wait)

        outcomes: list[tuple[str, str, object, object]] = []

        def confirm_in_thread(action_id: str, digest: str):
            with SessionFactory() as session:
                try:
                    user = session.query(UserModel).filter_by(user_id="usr_demo_01").first()
                    start_barrier.wait()
                    res = approvals.confirm_action(
                        action_id,
                        approvals.ConfirmActionRequest(
                            confirmation_id=f"conf_{action_id}",
                            action_digest=digest,
                        ),
                        user=user,
                        db=session,
                    )
                    outcomes.append((action_id, "ok", res.status, res.audit_id))
                except HTTPException as exc:
                    outcomes.append((action_id, "http", exc.status_code, exc.detail))
                except Exception as exc:
                    outcomes.append((action_id, "error", type(exc).__name__, repr(exc)))
                finally:
                    policy_barrier.abort()

        threads = [
            threading.Thread(target=confirm_in_thread, args=("act_yellow_600_1", d1)),
            threading.Thread(target=confirm_in_thread, args=("act_yellow_600_2", d2)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
            assert not t.is_alive(), "Worker thread did not terminate within timeout"

        assert len(outcomes) == 2, f"Expected 2 thread outcomes, got: {outcomes}"
        errors = [o for o in outcomes if o[1] == "error"]
        assert not errors, f"Unexpected worker exceptions: {errors}"

        with SessionFactory() as check:
            acc = check.query(AccountModel).filter_by(account_id="acc_cny_001").first()
            txs = check.query(TransactionModel).filter_by(category="Transfers").all()
            exec_audits = (
                check.query(AuditLogModel)
                .filter_by(action_type="TRANSFER_EXECUTED_ATOMIC")
                .all()
            )
            a1 = check.query(ActionApprovalModel).filter_by(action_id="act_yellow_600_1").first()
            a2 = check.query(ActionApprovalModel).filter_by(action_id="act_yellow_600_2").first()

            diag = (
                f"outcomes={outcomes}, statuses=({a1.status}, {a2.status}), "
                f"tiers=({a1.tier}, {a2.tier}), tx_count={len(txs)}, "
                f"exec_audit_count={len(exec_audits)}, balance={acc.balance}, "
                f"daily_total={acc.daily_transfer_total}"
            )
            completed_actions = [a for a in (a1, a2) if a.status == ActionStatus.COMPLETED.value]
            assert len(completed_actions) == 1, (
                f"Both 600 CNY Yellow transfers must not complete without MFA: {diag}"
            )
            assert len(txs) == 1, f"Expected exactly 1 transfer debit transaction: {diag}"
            assert txs[0].amount == Decimal("600.00"), f"Expected 600.00 transfer amount: {diag}"
            assert len(exec_audits) == 1, f"Expected exactly 1 execution audit record: {diag}"
            assert exec_audits[0].reason_code == "TRANSFER_SUCCESS", diag
            assert acc.balance == Decimal("14650.00"), (
                f"Expected balance 14650.00 after one 600 CNY transfer: {diag}"
            )
            assert acc.daily_transfer_total == Decimal("600.00"), (
                f"Expected daily_transfer_total 600.00: {diag}"
            )

            winner = completed_actions[0]
            assert winner.audit_id == exec_audits[0].audit_id, diag
            outcome_by_action = {act_id: (kind, val1, val2) for act_id, kind, val1, val2 in outcomes}
            assert outcome_by_action[winner.action_id] == (
                "ok",
                ActionStatus.COMPLETED,
                winner.audit_id,
            ), diag

            other_action = a2 if a1.action_id == winner.action_id else a1
            other_outcome = outcome_by_action[other_action.action_id]
            if other_action.status == ActionStatus.PENDING_MFA.value:
                assert other_action.tier == Tier.RED.value, diag
                assert other_action.verification_code is not None, diag
                assert other_action.audit_id is not None, diag
                assert other_outcome == (
                    "ok",
                    ActionStatus.PENDING_MFA,
                    other_action.audit_id,
                ), diag
            else:
                assert other_action.status == ActionStatus.PENDING_CONFIRMATION.value, (
                    f"Expected second action to be PENDING_MFA or PENDING_CONFIRMATION for retry: {diag}"
                )
                assert other_action.audit_id is None, diag
                assert other_outcome[0] == "http" and other_outcome[1] == 409, diag
    finally:
        engine.dispose()


def test_concurrent_transfers_exceeding_balance_cannot_both_succeed(
    tmp_path, monkeypatch
):
    """Test 3 - Concurrent insufficient funds (balance 500 CNY, two 400 CNY transfers).

    Account balance starts at 500.00 CNY and two distinct Yellow transfer actions
    request 400.00 CNY each (combined 800.00 CNY <= 1,000.00 CNY daily threshold,
    but > 500.00 CNY available balance).
    Verifies:
    - Exactly one transfer succeeds.
    - Final balance is 100.00 CNY.
    - Daily transfer total is 400.00 CNY.
    - Exactly one transfer transaction and one execution audit record exist.
    - No action is marked COMPLETED unless its transfer actually committed.
    """
    monkeypatch.setattr(policy_service, "use_mock", False)
    engine, SessionFactory = _make_session_factory(tmp_path, "insufficient_race.db")

    try:
        with SessionFactory() as setup:
            setup.add(UserModel(user_id="usr_demo_01", username="Alice Wang", is_locked=False))
            setup.add(
                AccountModel(
                    account_id="acc_cny_001",
                    user_id="usr_demo_01",
                    account_number="6222021001009988",
                    currency="CNY",
                    balance=Decimal("500.00"),
                    daily_transfer_total=Decimal("0.00"),
                )
            )
            now = mfa.utc_now()
            rec1 = _make_transfer_record("act_bal_400_1", "400.00", now)
            rec2 = _make_transfer_record("act_bal_400_2", "400.00", now)
            d1, d2 = rec1.action_digest, rec2.action_digest
            setup.add_all([rec1, rec2])
            setup.commit()

        start_barrier = threading.Barrier(2, timeout=5)
        policy_barrier = threading.Barrier(2, timeout=0.2)
        original_current_policy = approvals._current_policy

        def current_policy_then_wait(*args, **kwargs):
            decision = original_current_policy(*args, **kwargs)
            try:
                policy_barrier.wait()
            except threading.BrokenBarrierError:
                pass
            return decision

        monkeypatch.setattr(approvals, "_current_policy", current_policy_then_wait)

        outcomes: list[tuple[str, str, object, object]] = []

        def confirm_in_thread(action_id: str, digest: str):
            with SessionFactory() as session:
                try:
                    user = session.query(UserModel).filter_by(user_id="usr_demo_01").first()
                    start_barrier.wait()
                    res = approvals.confirm_action(
                        action_id,
                        approvals.ConfirmActionRequest(
                            confirmation_id=f"conf_{action_id}",
                            action_digest=digest,
                        ),
                        user=user,
                        db=session,
                    )
                    outcomes.append((action_id, "ok", res.status, res.audit_id))
                except HTTPException as exc:
                    outcomes.append((action_id, "http", exc.status_code, exc.detail))
                except Exception as exc:
                    outcomes.append((action_id, "error", type(exc).__name__, repr(exc)))
                finally:
                    policy_barrier.abort()

        threads = [
            threading.Thread(target=confirm_in_thread, args=("act_bal_400_1", d1)),
            threading.Thread(target=confirm_in_thread, args=("act_bal_400_2", d2)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
            assert not t.is_alive(), "Worker thread did not terminate within timeout"

        assert len(outcomes) == 2, f"Expected 2 thread outcomes, got: {outcomes}"
        errors = [o for o in outcomes if o[1] == "error"]
        assert not errors, f"Unexpected worker exceptions: {errors}"

        with SessionFactory() as check:
            acc = check.query(AccountModel).filter_by(account_id="acc_cny_001").first()
            txs = check.query(TransactionModel).filter_by(category="Transfers").all()
            exec_audits = (
                check.query(AuditLogModel)
                .filter_by(action_type="TRANSFER_EXECUTED_ATOMIC")
                .all()
            )
            a1 = check.query(ActionApprovalModel).filter_by(action_id="act_bal_400_1").first()
            a2 = check.query(ActionApprovalModel).filter_by(action_id="act_bal_400_2").first()

            diag = (
                f"outcomes={outcomes}, statuses=({a1.status}, {a2.status}), "
                f"tx_count={len(txs)}, exec_audit_count={len(exec_audits)}, "
                f"balance={acc.balance}, daily_total={acc.daily_transfer_total}"
            )
            completed_actions = [a for a in (a1, a2) if a.status == ActionStatus.COMPLETED.value]
            assert len(completed_actions) == 1, (
                f"Expected exactly 1 COMPLETED transfer: {diag}"
            )
            assert len(txs) == 1, f"Expected 1 transfer transaction: {diag}"
            assert txs[0].amount == Decimal("400.00"), f"Expected 400.00 transfer amount: {diag}"
            assert len(exec_audits) == 1, f"Expected 1 execution audit record: {diag}"
            assert exec_audits[0].reason_code == "TRANSFER_SUCCESS", diag
            assert acc.balance == Decimal("100.00"), (
                f"Expected final balance 100.00 CNY: {diag}"
            )
            assert acc.daily_transfer_total == Decimal("400.00"), (
                f"Expected daily_transfer_total 400.00 CNY: {diag}"
            )

            winner = completed_actions[0]
            assert winner.audit_id == exec_audits[0].audit_id, diag
            outcome_by_action = {act_id: (kind, val1, val2) for act_id, kind, val1, val2 in outcomes}
            assert outcome_by_action[winner.action_id] == (
                "ok",
                ActionStatus.COMPLETED,
                winner.audit_id,
            ), diag

            other_action = a2 if a1.action_id == winner.action_id else a1
            assert other_action.status != ActionStatus.COMPLETED.value, diag
            assert other_action.audit_id is None, diag
            other_outcome = outcome_by_action[other_action.action_id]
            assert other_outcome[0] == "http" and other_outcome[1] in (400, 409), (
                f"Expected losing transfer to fail with HTTP 400 or 409: {diag}"
            )
    finally:
        engine.dispose()
