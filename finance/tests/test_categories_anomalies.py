"""Categorization rules, anomaly rules, safety and isolation tests (P3)."""
import ast
import json
from pathlib import Path

import pytest

from finance.analytics import analyze_spending
from finance.categories import categorize
from finance.cli import main as cli_main

FINANCE_DIR = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("category, merchant, expected, source", [
    ("Food", "x", "Food", "provided"),
    ("  Subscriptions ", "x", "Subscriptions", "provided"),
    ("Other", "Didi", "Other", "provided"),            # provided label beats merchant rule
    ("", "Shenzhen Metro Line 1", "Transport", "merchant_rule"),
    ("unknown", "爱奇艺VIP会员", "Subscriptions", "merchant_rule"),
    ("", "Parent Teacher Shop", "Uncategorized", "fallback"),  # 'rent' must not match 'Parent'
])
def test_categorize_precedence(category, merchant, expected, source):
    res = categorize(category, merchant)
    assert (res.label, res.source) == (expected, source)


def by_code(report, code):
    return [a.transaction_id for a in report.anomalies if a.reason.startswith(code + ":")]


def test_spending_anomalies_on_synthetic(synthetic):
    r = analyze_spending(synthetic, "2026-09")
    assert by_code(r, "LARGE_VS_CATEGORY_HISTORY") == ["P3-S05"]
    assert by_code(r, "LARGE_TRANSACTION") == ["P3-S22"]
    assert sorted(by_code(r, "CATEGORY_MONTH_SPIKE")) == ["P3-S05", "P3-S06"]
    assert by_code(r, "POSSIBLE_DUPLICATE_CHARGE") == ["P3-S07"]


def test_steady_months_have_no_anomalies(synthetic, shared):
    assert analyze_spending(synthetic, "2026-08").anomalies == []
    assert analyze_spending(shared, "2026-10").anomalies == []


def test_duplicate_charge_window(tx):
    a = tx(amount="88.00", merchant="Meituan", timestamp="2026-09-12T13:00:00+08:00")
    far = tx(amount="88.00", merchant="Meituan", timestamp="2026-09-12T13:11:00+08:00")
    assert by_code(analyze_spending([a, far], "2026-09"), "POSSIBLE_DUPLICATE_CHARGE") == []


def test_reasons_are_explainable_and_not_advice(synthetic):
    r = analyze_spending(synthetic, "2026-09")
    banned = ("you should", "recommend", "advise", "invest", "cancel", "save money")
    for a in r.anomalies:
        code, _, text = a.reason.partition(": ")
        assert code.isupper() and text
        assert not any(b in a.reason.lower() for b in banned), a


def test_untrusted_text_never_in_reasons(synthetic):
    r = analyze_spending(synthetic, "2026-09")
    reasons = " ".join(a.reason for a in r.anomalies).lower()
    assert "ignore previous" not in reasons and "approve" not in reasons
    assert "system:" not in r.model_dump_json().lower()  # note text is never echoed


def test_category_label_sanitized(tx):
    nasty = "Shop‮\x00\nX" + "A" * 200
    r = analyze_spending([tx(category=nasty)], "2026-09")
    (label,) = r.category_totals
    assert len(label) <= 64 and not any(c in label for c in "\x00‮\n")


def test_no_forbidden_imports():
    """P3 is pure: no backend/agent/peer modules, DB, HTTP or LLM clients."""
    forbidden = {"backend", "agent", "security", "subscriptions", "requests", "httpx", "urllib",
                 "sqlalchemy", "psycopg", "openai", "anthropic", "fastapi", "socket"}
    for path in FINANCE_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for n in names:
                assert n.split(".")[0] not in forbidden, f"{path.name} imports {n}"


def test_cli_json_report_on_team_fixture(capsys, shared, t12):
    assert cli_main(["--period", t12["period"], "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["total_spending"] == t12["expected_total_spending"]


def test_cli_bad_period_exit_code(capsys):
    assert cli_main(["--period", "2026/09"]) == 2
