"""Cancellation walkthrough on the shared fixtures (the P5 expected-output set).

These tests are the executable version of docs/subscriptions/expected_outputs.md.
If a rule changes, update the tests and that document together.
"""
import json
from decimal import Decimal
from pathlib import Path

from contracts.enums import Cadence
from contracts.models import Subscription, Transaction
from subscriptions.detector import detect_subscriptions
from subscriptions.mapping import (
    ALREADY_CANCELLED,
    NOT_FOUND,
    assess_stored_cancellation,
    enrich_candidates,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
USER = "user_001"


def load():
    txs = [Transaction(**r) for r in json.loads((FIXTURES / "transactions.json").read_text())]
    stored = [Subscription(**r) for r in json.loads((FIXTURES / "subscriptions.json").read_text())]
    return detect_subscriptions(txs), stored


def by_id(report):
    return {c.subscription_id: c for c in report.candidates}


def cancelled(stored, sid):
    """What P2 must persist after a confirmed cancellation."""
    return [s.model_copy(update={"status": "cancelled"}) if s.subscription_id == sid else s
            for s in stored]


def test_listing_shows_both_candidates_with_evidence():
    report, _ = load()
    got = by_id(report)
    assert sorted(got) == ["sub_cloudmusic", "sub_streambox"]
    s = got["sub_streambox"]
    assert (s.estimated_amount, s.cadence, s.confidence) == (Decimal("39.00"), Cadence.MONTHLY, 0.85)
    assert s.evidence_transaction_ids == ["tx_001", "tx_002", "tx_003", "tx_004"]
    m = got["sub_cloudmusic"]
    assert (m.estimated_amount, m.cadence, m.confidence) == (Decimal("19.00"), Cadence.MONTHLY, 0.85)
    assert m.evidence_transaction_ids == ["tx_005", "tx_006", "tx_007", "tx_008"]


def test_listing_alone_grants_no_cancellation_permission():
    report, _ = load()
    assert all(c.cancellation_supported is False for c in report.candidates)


def test_only_supported_verified_name_is_eligible():
    report, stored = load()
    got = by_id(report)
    assert assess_stored_cancellation(got["sub_streambox"], stored, USER).eligible is True
    music = assess_stored_cancellation(got["sub_cloudmusic"], stored, USER)
    assert (music.eligible, music.reason_code) == (False, "CANCELLATION_NOT_SUPPORTED")


def test_cancel_once_relist_and_retry():
    report, stored = load()
    after = cancelled(stored, "sub_streambox")

    # Re-listing: the recurring charges are still evidence, the candidate is not erased.
    relisted = detect_subscriptions(
        [Transaction(**r) for r in json.loads((FIXTURES / "transactions.json").read_text())])
    assert "sub_streambox" in by_id(relisted)

    # Enrichment no longer marks it as cancellable.
    enriched = by_id(enrich_candidates(relisted, after, USER))
    assert enriched["sub_streambox"].cancellation_supported is False

    # Retry gives a defined safe result and names the stored record.
    retry = assess_stored_cancellation(by_id(relisted)["sub_streambox"], after, USER)
    assert (retry.eligible, retry.reason_code) == (False, ALREADY_CANCELLED)
    assert retry.stored_subscription_id == "sub_streambox"
    assert retry.requires_confirmation is True


def test_cancelling_one_does_not_affect_the_other_record():
    report, stored = load()
    after = cancelled(stored, "sub_streambox")
    music = assess_stored_cancellation(by_id(report)["sub_cloudmusic"], after, USER)
    assert music.reason_code == "CANCELLATION_NOT_SUPPORTED"


def test_another_user_sees_no_record():
    report, stored = load()
    for c in report.candidates:
        d = assess_stored_cancellation(c, stored, "user_002")
        assert (d.eligible, d.reason_code, d.stored_subscription_id) == (False, NOT_FOUND, None)


def test_detected_but_not_stored_stays_a_candidate():
    report, _ = load()
    d = assess_stored_cancellation(by_id(report)["sub_streambox"], [], USER)
    assert (d.eligible, d.reason_code) == (False, NOT_FOUND)
    assert all(c.cancellation_supported is False
               for c in enrich_candidates(report, [], USER).candidates)


def test_confidence_does_not_decide_the_match_or_the_permission():
    # Few charges (low confidence) but a stored, active, supported record exists: still matched.
    report, stored = load()
    weak = by_id(report)["sub_streambox"].model_copy(update={"confidence": 0.40})
    assert assess_stored_cancellation(weak, stored, USER).eligible is True
    # High confidence with no stored record: never eligible.
    strong = weak.model_copy(update={"confidence": 0.90, "subscription_id": "sub_unknown", "merchant": "Unknown"})
    assert assess_stored_cancellation(strong, stored, USER).reason_code == NOT_FOUND


# ---- Alice's backend demo data (copied from backend/app/db/seed.py and adapters.py) ----

def alice():
    txs = [
        Transaction(transaction_id="tx_demo_003", account_id="acc_cny_001",
                    timestamp="2026-09-05T14:15:00+08:00", amount=Decimal("45.00"),
                    direction="debit", merchant="iQIYI VIP Monthly", category="Entertainment"),
        Transaction(transaction_id="tx_demo_002", account_id="acc_cny_001",
                    timestamp="2026-10-05T14:15:00+08:00", amount=Decimal("45.00"),
                    direction="debit", merchant="iQIYI VIP Monthly", category="Entertainment"),
        Transaction(transaction_id="tx_demo_001", account_id="acc_cny_001",
                    timestamp="2026-10-01T09:30:00+08:00", amount=Decimal("35.00"),
                    direction="debit", merchant="Starbucks Reserve", category="Dining"),
        Transaction(transaction_id="tx_demo_004", account_id="acc_cny_001",
                    timestamp="2026-10-10T18:00:00+08:00", amount=Decimal("5000.00"),
                    direction="credit", merchant="Payroll Inward", category="Income"),
    ]
    stored = [Subscription(
        subscription_id="sub_iQIYI_01", user_id="usr_demo_01", merchant="iQIYI VIP Monthly",
        estimated_amount=Decimal("45.00"), cadence=Cadence.MONTHLY,
        status="active", cancellation_supported=True)]
    return txs, stored


def test_alice_iqiyi_is_recurrence_evidence_with_low_confidence():
    txs, _ = alice()
    (c,) = detect_subscriptions(txs).candidates
    assert c.subscription_id == "sub_iqiyi_vip_monthly"
    assert (c.estimated_amount, c.cadence, c.confidence) == (Decimal("45.00"), Cadence.MONTHLY, 0.40)
    assert c.evidence_transaction_ids == ["tx_demo_003", "tx_demo_002"]
    assert c.cancellation_supported is False


def test_alice_candidate_id_differs_from_stored_id_but_maps_by_name():
    txs, stored = alice()
    (c,) = detect_subscriptions(txs).candidates
    assert c.subscription_id != stored[0].subscription_id
    d = assess_stored_cancellation(c, stored, "usr_demo_01")
    assert (d.eligible, d.reason_code) == (True, "ELIGIBLE")
    assert d.stored_subscription_id == "sub_iQIYI_01"


def test_alice_record_is_not_visible_to_another_user():
    txs, stored = alice()
    (c,) = detect_subscriptions(txs).candidates
    d = assess_stored_cancellation(c, stored, "usr_other")
    assert (d.eligible, d.reason_code) == (False, NOT_FOUND)


def test_alice_cancel_once_then_repeat_is_refused():
    txs, stored = alice()
    (c,) = detect_subscriptions(txs).candidates
    after = cancelled(stored, "sub_iQIYI_01")
    d = assess_stored_cancellation(c, after, "usr_demo_01")
    assert (d.eligible, d.reason_code) == (False, ALREADY_CANCELLED)
    assert d.stored_subscription_id == "sub_iQIYI_01"
