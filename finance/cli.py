"""Sample spending report CLI (development/demo only).

    py -m finance.cli --period 2026-10                      # team fixture
    py -m finance.cli --period 2026-09 --synthetic          # P3 edge-case fixture
    py -m finance.cli --period 2026-10 --json               # SpendingReport JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ._bootstrap import REPO_ROOT, ensure_repo_on_path

SHARED_FIXTURE = REPO_ROOT / "fixtures" / "transactions.json"
SYNTHETIC_FIXTURE = Path(__file__).resolve().parent / "tests" / "data" / "transactions_synthetic.json"


def load_transactions(path: Path):
    ensure_repo_on_path()
    from contracts.models import Transaction

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("transactions", [])
    return [Transaction.model_validate(row) for row in data]


def render_text(report, monthly, diagnostics) -> str:
    lines = [f"Spending report {report.period} ({report.currency})", "=" * 44,
             f"Total spending: {report.total_spending:.2f}", "", "By category:"]
    if report.category_totals:
        width = max(len(k) for k in report.category_totals)
        for cat, amt in sorted(report.category_totals.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"  {cat:<{width}}  {amt:>12.2f}")
    else:
        lines.append("  (none)")
    lines += ["", "Monthly spending (empty months shown as 0.00):"]
    lines += [f"  {p}  {amt:>12.2f}" for p, amt in monthly.items()]
    lines += ["", f"Anomalies in report ({len(report.anomalies)}):"]
    lines += [f"  - [{a.transaction_id}] {a.reason}" for a in report.anomalies] or ["  (none)"]
    notes = [d for d in diagnostics if d.kind == "info"]
    lines += ["", f"Notes ({len(notes)}):"]
    lines += [f"  - {d.code}{f' [{d.transaction_id}]' if d.transaction_id else ''}: {d.message}"
              for d in notes] or ["  (none)"]
    lines += ["", "Descriptive analytics on synthetic data only; not financial advice."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P3 sample spending report")
    parser.add_argument("--period", required=True, help="YYYY-MM")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--transactions", type=Path, help="path to a transactions JSON file")
    src.add_argument("--synthetic", action="store_true", help="use the P3 edge-case fixture")
    parser.add_argument("--json", action="store_true", help="emit SpendingReport JSON")
    args = parser.parse_args(argv)

    if args.transactions:
        path = args.transactions
    elif args.synthetic or not SHARED_FIXTURE.exists():
        path = SYNTHETIC_FIXTURE
    else:
        path = SHARED_FIXTURE
    txns = load_transactions(path)
    from .analytics import analyze_spending, monthly_totals, spending_diagnostics

    try:
        report = analyze_spending(txns, args.period)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print(f"source: {path}")
        print(render_text(report, monthly_totals(txns), spending_diagnostics(txns, args.period)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
