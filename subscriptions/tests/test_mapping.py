from decimal import Decimal

from contracts.enums import Cadence
from contracts.models import Subscription, SubscriptionCandidate, SubscriptionReport
from subscriptions.mapping import (
    ALREADY_CANCELLED,
    AMBIGUOUS,
    NOT_FOUND,
    MatchStatus,
    assess_stored_cancellation,
    enrich_candidates,
    match_stored,
)

USER = "user_001"


def cand(sid="sub_streambox", merchant="StreamBox", amount="39.00", supported=False):
    return SubscriptionCandidate(
        subscription_id=sid, merchant=merchant, estimated_amount=Decimal(amount),
        cadence=Cadence.MONTHLY, confidence=0.85,
        evidence_transaction_ids=["t1", "t2", "t3", "t4"], cancellation_supported=supported,
    )


def rec(sid="sub_streambox", merchant="StreamBox", amount="39.00", status="active",
        supported=True, user=USER):
    return Subscription(
        subscription_id=sid, user_id=user, merchant=merchant,
        estimated_amount=Decimal(amount), cadence=Cadence.MONTHLY,
        status=status, cancellation_supported=supported,
    )


# Same data as fixtures/subscriptions.json
FIXTURE_STORED = [
    rec("sub_streambox", "StreamBox", "39.00", supported=True),
    rec("sub_cloudmusic", "CloudMusic", "19.00", supported=False),
]


# ---- matching -------------------------------------------------------------

def test_match_by_id_and_merchant():
    m = match_stored(cand(), [rec()], USER)
    assert m.status is MatchStatus.MATCHED
    assert m.record.subscription_id == "sub_streambox"


def test_match_by_merchant_name_when_ids_differ():
    m = match_stored(cand(sid="sub_stream_box_x"), [rec()], USER)
    assert m.status is MatchStatus.MATCHED


def test_merchant_name_case_and_spaces_are_ignored():
    m = match_stored(cand(merchant="STREAMBOX "), [rec()], USER)
    assert m.status is MatchStatus.MATCHED


def test_unknown_merchant_is_not_found():
    m = match_stored(cand(sid="sub_newapp", merchant="NewApp"), [rec()], USER)
    assert m.status is MatchStatus.NOT_FOUND


def test_empty_store_is_not_found():
    assert match_stored(cand(), [], USER).status is MatchStatus.NOT_FOUND


def test_same_id_but_different_merchant_is_not_a_match():
    stored = [rec(sid="sub_streambox", merchant="SomethingElse")]
    assert match_stored(cand(), stored, USER).status is MatchStatus.NOT_FOUND


def test_other_users_record_is_never_matched():
    assert match_stored(cand(), [rec(user="user_002")], USER).status is MatchStatus.NOT_FOUND


def test_two_records_same_merchant_are_told_apart_by_price():
    stored = [rec("sub_telco_39_00", "Telco", "39.00"), rec("sub_telco_99_00", "Telco", "99.00")]
    m = match_stored(cand("sub_other", "Telco", "99.00"), stored, USER)
    assert m.status is MatchStatus.MATCHED
    assert m.record.subscription_id == "sub_telco_99_00"


def test_two_records_same_merchant_same_price_are_ambiguous():
    stored = [rec("sub_a", "Telco", "39.00"), rec("sub_b", "Telco", "39.00")]
    assert match_stored(cand("sub_x", "Telco", "39.00"), stored, USER).status is MatchStatus.AMBIGUOUS


def test_two_records_same_merchant_no_price_match_is_not_found():
    stored = [rec("sub_a", "Telco", "39.00"), rec("sub_b", "Telco", "99.00")]
    assert match_stored(cand("sub_x", "Telco", "500.00"), stored, USER).status is MatchStatus.NOT_FOUND


def test_duplicate_id_records_are_ambiguous():
    stored = [rec(), rec()]
    assert match_stored(cand(), stored, USER).status is MatchStatus.AMBIGUOUS


# ---- cancellation decision ------------------------------------------------

def test_supported_active_subscription_is_eligible():
    d = assess_stored_cancellation(cand(), [rec()], USER)
    assert d.eligible is True
    assert d.reason_code == "ELIGIBLE"
    assert d.stored_subscription_id == "sub_streambox"
    assert d.requires_confirmation is True


def test_unsupported_subscription_is_blocked():
    d = assess_stored_cancellation(cand(), [rec(supported=False)], USER)
    assert (d.eligible, d.reason_code) == (False, "CANCELLATION_NOT_SUPPORTED")


def test_unknown_subscription_is_blocked():
    d = assess_stored_cancellation(cand("sub_newapp", "NewApp"), [rec()], USER)
    assert (d.eligible, d.reason_code) == (False, NOT_FOUND)
    assert d.stored_subscription_id is None


def test_ambiguous_subscription_is_blocked():
    stored = [rec("sub_a", "Telco", "39.00"), rec("sub_b", "Telco", "39.00")]
    d = assess_stored_cancellation(cand("sub_x", "Telco", "39.00"), stored, USER)
    assert (d.eligible, d.reason_code) == (False, AMBIGUOUS)


def test_cancelled_subscription_is_blocked():
    d = assess_stored_cancellation(cand(), [rec(status="cancelled")], USER)
    assert (d.eligible, d.reason_code) == (False, ALREADY_CANCELLED)
    assert d.stored_subscription_id == "sub_streambox"


def test_repeated_cancellation_is_refused_after_state_changes():
    before = [rec()]
    assert assess_stored_cancellation(cand(), before, USER).eligible is True
    after = [rec(status="cancelled")]  # what P2 stores once the first one executed
    second = assess_stored_cancellation(cand(), after, USER)
    assert (second.eligible, second.reason_code) == (False, ALREADY_CANCELLED)


def test_cancelled_is_reported_before_unsupported():
    d = assess_stored_cancellation(cand(), [rec(status="cancelled", supported=False)], USER)
    assert d.reason_code == ALREADY_CANCELLED


def test_detector_flag_is_never_trusted():
    # Candidate claims support, stored record says no.
    d = assess_stored_cancellation(cand(supported=True), [rec(supported=False)], USER)
    assert (d.eligible, d.reason_code) == (False, "CANCELLATION_NOT_SUPPORTED")
    # Candidate claims nothing, stored record says yes.
    assert assess_stored_cancellation(cand(supported=False), [rec(supported=True)], USER).eligible


def test_other_users_record_cannot_be_cancelled():
    d = assess_stored_cancellation(cand(), [rec(user="user_002")], USER)
    assert (d.eligible, d.reason_code) == (False, NOT_FOUND)


def test_fixture_streambox_eligible_cloudmusic_not():
    stream = assess_stored_cancellation(cand(), FIXTURE_STORED, USER)
    music = assess_stored_cancellation(
        cand("sub_cloudmusic", "CloudMusic", "19.00"), FIXTURE_STORED, USER)
    assert stream.eligible is True
    assert (music.eligible, music.reason_code) == (False, "CANCELLATION_NOT_SUPPORTED")


# ---- enrich ---------------------------------------------------------------

def test_enrich_sets_support_only_for_matched_active_supported():
    report = SubscriptionReport(candidates=[
        cand(),
        cand("sub_cloudmusic", "CloudMusic", "19.00"),
        cand("sub_newapp", "NewApp", "9.00"),
    ])
    out = {c.subscription_id: c.cancellation_supported
           for c in enrich_candidates(report, FIXTURE_STORED, USER).candidates}
    assert out == {"sub_streambox": True, "sub_cloudmusic": False, "sub_newapp": False}


def test_enrich_does_not_trust_candidate_flag_or_cancelled_record():
    report = SubscriptionReport(candidates=[cand(supported=True)])
    out = enrich_candidates(report, [rec(status="cancelled")], USER)
    assert out.candidates[0].cancellation_supported is False


def test_enrich_keeps_other_fields_and_does_not_change_input():
    original = cand()
    report = SubscriptionReport(candidates=[original])
    out = enrich_candidates(report, [rec()], USER)
    got = out.candidates[0]
    assert got.cancellation_supported is True
    assert original.cancellation_supported is False
    assert (got.subscription_id, got.estimated_amount, got.confidence, got.evidence_transaction_ids) == (
        original.subscription_id, original.estimated_amount, original.confidence,
        original.evidence_transaction_ids)
