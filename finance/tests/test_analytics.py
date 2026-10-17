"""Aggregation, validation and edge-case tests for analyze_spending (P3)."""
import json
import random
from decimal import Decimal

import pytest
from pydantic import ValidationError

from contracts.models import Anomaly, SpendingReport, Transaction
from finance.analytics import (SpendingConfig, analyze_spending, build_spending_report,
                               monthly_totals, spending_diagnostics)

D = Decimal


def codes(report):
    return [a.reason.split(":", 1)[0] for a in report.anomalies]


def ids_for(report, code):
    return sorted(a.transaction_id for a in report.anomalies if a.reason.startswith(code + ":"))


# --- T12 (shared frozen fixture) -------------------------------------------------

def test_t12_matches_expected_cases(shared, t12):
    r = analyze_spending(shared, t12["period"])
    assert r.total_spending == D(t12["expected_total_spending"])
    assert r.category_totals == {k: D(v) for k, v in t12["expected_category_totals"].items()}


def test_t12_credit_inflows_excluded(shared):
    r = analyze_spending(shared, "2026-10")
    debit_sum = sum((t.amount for t in shared
                     if t.direction.value == "debit" and t.timestamp.month == 10), D(0))
    assert r.total_spending == debit_sum  # 500.00 income + 300.00 refund never counted
    notes = {f.code for f in spending_diagnostics(shared, "2026-10")}
    assert {"CREDITS_EXCLUDED", "REFUND_NOT_NETTED"} <= notes


def test_t09_injection_in_note_is_inert(shared):
    r = analyze_spending(shared, "2026-10")
    blob = r.model_dump_json().lower()
    assert "ignore previous" not in blob and "attacker" not in blob
    assert r.category_totals["Other"] == D("20.00")  # still just counted as data


# --- P3 synthetic fixture ----------------------------------------------------------

def test_synthetic_exact_totals(synthetic):
    r = analyze_spending(synthetic, "2026-09")
    assert isinstance(r, SpendingReport) and r.currency == "CNY"
    assert r.total_spending == D("9254.70")  # hand-computed, docs/finance/RULES.md §6
    assert r.category_totals == {
        "Dining": D("327.50"), "Education": D("5800.00"), "Groceries": D("128.00"),
        "Shopping": D("2680.00"), "Subscriptions": D("30.00"), "Telecom": D("156.80"),
        "Transport": D("57.40"), "Uncategorized": D("75.00"),
    }
    assert sum(r.category_totals.values()) == r.total_spending


def test_decimal_exactness_no_float_drift(tx):
    txns = [tx(amount="0.10") for _ in range(3)] + [tx(amount="0.20")]
    assert analyze_spending(txns, "2026-09").total_spending == D("0.50")


def test_credit_only_month(tx):
    r = analyze_spending([tx(amount="8000.00", direction="credit", category="Income")], "2026-09")
    assert r.total_spending == D("0.00") and r.category_totals == {} and r.anomalies == []


def test_refund_not_netted(tx):
    r = analyze_spending([tx(amount="100.00"),
                          tx(amount="40.00", direction="credit", category="Refund")], "2026-09")
    assert r.total_spending == D("100.00")


# --- duplicates -------------------------------------------------------------------

def test_identical_duplicate_ids_counted_once(tx):
    a = tx(amount="66.00", transaction_id="DUP-1")
    r = analyze_spending([a, a.model_copy(), tx(amount="1.00")], "2026-09")
    assert r.total_spending == D("67.00")
    assert ids_for(r, "DUPLICATE_TRANSACTION_ID") == ["DUP-1"]


def test_conflicting_duplicate_ids_excluded_order_independent(tx):
    a = tx(amount="99.00", transaction_id="DUP-2")
    b = tx(amount="999.00", transaction_id="DUP-2")
    for order in ([a, b], [b, a]):
        r = analyze_spending(order, "2026-09")
        assert r.total_spending == D("0.00")
        assert ids_for(r, "CONFLICTING_DUPLICATE_ID") == ["DUP-2"]


# --- time zones -------------------------------------------------------------------

def test_month_boundaries_use_asia_shanghai(synthetic):
    # P3-S16 2026-08-31T17:30Z == 09-01 01:30 CST -> September
    assert analyze_spending(synthetic, "2026-09").category_totals["Transport"] == D("57.40")
    # P3-S18 2026-09-30T16:30Z == 10-01 00:30 CST -> October only
    assert analyze_spending(synthetic, "2026-10").total_spending == D("60.00")


# --- invalid inputs ---------------------------------------------------------------

@pytest.mark.parametrize("field, value", [
    ("amount", "-50.00"), ("amount", "0.00"), ("amount", "12.345"), ("amount", "abc"),
    ("timestamp", "2026-09-10T12:00:00"),  # naive: no timezone
    ("direction", "sideways"),
])
def test_contract_rejects_invalid_transactions(field, value):
    """Rule: invalid amounts/timestamps are rejected by the shared Transaction model
    before they ever reach finance/ (documented in RULES.md §2)."""
    row = dict(transaction_id="X", account_id="A", timestamp="2026-09-10T12:00:00+08:00",
               amount="1.00", direction="debit", merchant="m", category="c")
    row[field] = value
    with pytest.raises(ValidationError):
        Transaction.model_validate(row)


def test_unvalidated_bad_amount_still_excluded(tx):
    """Defense in depth: objects built WITHOUT validation are re-checked."""
    good = tx(amount="5.00")
    bad = Transaction.model_construct(**{**good.model_dump(), "transaction_id": "BAD",
                                         "amount": D("-50.00")})
    r = analyze_spending([good, bad], "2026-09")
    assert r.total_spending == D("5.00") and ids_for(r, "INVALID_AMOUNT") == ["BAD"]


@pytest.mark.parametrize("period", ["2026-9", "2026-13", "202609", "Sept 2026", "", None, "2026-00"])
def test_invalid_period_raises(synthetic, period):
    with pytest.raises(ValueError):
        analyze_spending(synthetic, period)


# --- categories -------------------------------------------------------------------

def test_categories_kept_as_written_and_case_merged(tx):
    r = analyze_spending([
        tx(amount="10.00", category="Food", timestamp="2026-09-01T10:00:00+08:00"),
        tx(amount="5.00", category="food"),                      # merged into "Food"
        tx(amount="7.00", category="Other"),                     # "Other" is a real label
        tx(amount="3.00", category="", merchant="滴滴出行"),       # empty -> merchant rule
        tx(amount="2.00", category="unknown", merchant="Mystery Ltd"),  # -> Uncategorized
    ], "2026-09")
    assert r.category_totals == {"Food": D("15.00"), "Other": D("7.00"),
                                 "Transport": D("3.00"), "Uncategorized": D("2.00")}


def test_excluded_debit_categories_config(tx):
    txns = [tx(amount="500.00", category="Transfer"), tx(amount="20.00")]
    assert analyze_spending(txns, "2026-09").total_spending == D("520.00")  # default: counted
    cfg = SpendingConfig(excluded_debit_categories=frozenset({"transfer"}))
    assert build_spending_report(txns, "2026-09", cfg).total_spending == D("20.00")


# --- months, determinism, contract shape ----------------------------------------

def test_empty_input_and_empty_month(synthetic):
    assert analyze_spending([], "2026-09").total_spending == D("0.00")
    may = analyze_spending(synthetic, "2026-05")
    assert may.total_spending == D("0.00") and may.category_totals == {}


def test_monthly_totals_zero_fill(synthetic):
    assert {k: str(v) for k, v in monthly_totals(synthetic).items()} == {
        "2026-04": "99.00", "2026-05": "0.00", "2026-06": "664.70", "2026-07": "601.90",
        "2026-08": "668.00", "2026-09": "9254.70", "2026-10": "60.00"}
    assert list(monthly_totals([], "2026-01", "2026-02").values()) == [D("0.00"), D("0.00")]


def test_deterministic_under_input_shuffle(synthetic):
    base = analyze_spending(synthetic, "2026-09").model_dump()
    for seed in range(5):
        shuffled = synthetic[:]
        random.Random(seed).shuffle(shuffled)
        assert analyze_spending(shuffled, "2026-09").model_dump() == base


def test_report_roundtrips_through_contract_json(synthetic):
    r = analyze_spending(synthetic, "2026-09")
    data = json.loads(r.model_dump_json())
    assert data["total_spending"] == "9254.70"
    assert SpendingReport.model_validate(data) == r
    assert all(isinstance(a, Anomaly) and a.transaction_id and a.reason for a in r.anomalies)


def test_multiple_accounts_noted(tx):
    txns = [tx(account_id="A1"), tx(account_id="A2")]
    assert analyze_spending(txns, "2026-09").total_spending == D("20.00")
    assert "MULTIPLE_ACCOUNTS" in {f.code for f in spending_diagnostics(txns, "2026-09")}
