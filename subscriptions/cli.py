"""Command-line report for the subscription detector (P5).

Usage (from the repository root):
    python -m subscriptions.cli                      # uses fixtures/transactions.json
    python -m subscriptions.cli path/to/file.json    # any transactions JSON file
    python -m subscriptions.cli --json               # machine-readable output

Read-only: it prints a report and changes nothing.
"""
import argparse
import json
import sys
from pathlib import Path

from contracts.models import SubscriptionReport, Transaction
from subscriptions.detector import detect_subscriptions

DEFAULT_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "transactions.json"


def report_to_dict(report: SubscriptionReport) -> dict:
    """Plain-JSON form: money as decimal strings, as the shared contract requires."""
    return {
        "candidates": [
            {
                "subscription_id": c.subscription_id,
                "merchant": c.merchant,
                "estimated_amount": str(c.estimated_amount),
                "cadence": c.cadence.value,
                "confidence": c.confidence,
                "evidence_transaction_ids": list(c.evidence_transaction_ids),
                "cancellation_supported": c.cancellation_supported,
            }
            for c in report.candidates
        ]
    }


def format_report(report: SubscriptionReport) -> str:
    if not report.candidates:
        return "No recurring charges detected."
    lines = [f"Detected {len(report.candidates)} recurring-charge candidate(s):", ""]
    for c in report.candidates:
        lines += [
            f"- {c.merchant} ({c.subscription_id})",
            f"    amount:     {c.estimated_amount} CNY, {c.cadence.value}",
            f"    confidence: {c.confidence:.2f}",
            f"    evidence:   {', '.join(c.evidence_transaction_ids)}",
        ]
    lines += [
        "",
        "Note: these are candidates, not verified subscriptions. Whether a",
        "candidate can be cancelled is decided from stored records by the backend.",
    ]
    return "\n".join(lines)


def load_transactions(path: Path) -> list[Transaction]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [Transaction(**row) for row in rows]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Detect recurring charges.")
    parser.add_argument("file", nargs="?", type=Path, default=DEFAULT_FILE,
                        help="transactions JSON file (default: fixtures/transactions.json)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args(argv)

    try:
        transactions = load_transactions(args.file)
    except FileNotFoundError:
        print(f"File not found: {args.file}", file=sys.stderr)
        return 2
    except (ValueError, TypeError) as exc:
        print(f"Could not read transactions from {args.file}: {exc}", file=sys.stderr)
        return 2

    report = detect_subscriptions(transactions)
    if args.json:
        print(json.dumps(report_to_dict(report), indent=2))
    else:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
