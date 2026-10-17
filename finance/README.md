# finance/ — P3 Finance Analytics

Deterministic spending categorization, monthly and category totals, and explainable anomaly
flags. These are pure calculations: **no DB, no HTTP, no LLM**, and no imports from backend,
agent or peer modules. It is built against the repo's `contracts/models.py`. Shared DTOs are
never redefined here.

## Entry point (spec §6)

```python
from contracts.models import Transaction, SpendingReport
from finance.analytics import analyze_spending

report: SpendingReport = analyze_spending(transactions, "2026-10")
# report.total_spending   -> Decimal('1843.00')
# report.category_totals  -> {"Food": Decimal('360.00'), ...}   (team labels kept as written)
# report.anomalies        -> [Anomaly(transaction_id="...", reason="CODE: explanation"), ...]
```

* Only a malformed `period` raises `ValueError`, which P2 can map to `ErrorResponse`.
* Credits are never spending, so T12 (`fixtures/expected_cases.json`) passes exactly.
* Months follow the Asia/Shanghai calendar.
* Full rules: [`docs/finance/RULES.md`](../docs/finance/RULES.md).

### Extra helpers (optional for P2)

| Function | Purpose |
|---|---|
| `monthly_totals(txns, start=None, end=None)` | `{YYYY-MM: Decimal}`, with empty months zero-filled |
| `spending_diagnostics(txns, period)` | All findings, including period-level notes (credits excluded, refunds) |
| `build_spending_report(txns, period, SpendingConfig(...))` | Same as `analyze_spending`, with thresholds and excluded categories configurable |

## Layout

```
finance/
  analytics.py   categories.py   anomalies.py   cleaning.py   money.py
  cli.py         _bootstrap.py   README.md      __init__.py
  tests/  conftest.py  test_analytics.py  test_categories_anomalies.py
          data/transactions_synthetic.json
docs/finance/RULES.md
```

## Run (from the repo root)

Requires Python ≥ 3.11, `pydantic>=2,<3` and `pytest>=8`. Tested on Python 3.11, 3.13 and
3.14, and pydantic 2.13 and 2.14. On Windows, use `py` in place of `python`.

```bash
python -m pip install "pydantic>=2,<3" "pytest>=8"
python -m pytest finance/tests -q                       # 46 tests incl. T12 + T09
python -m finance.cli --period 2026-10                  # report on the team fixture
python -m finance.cli --period 2026-09 --synthetic      # report on the P3 edge-case fixture
python -m finance.cli --period 2026-10 --json           # SpendingReport JSON
```

## Decisions (agreed 2026-10-17)

1. **Outbound transfers count as spending.** They are debits like any other.
   (`SpendingConfig(excluded_debit_categories=...)` exists if this ever changes.)
2. **Refunds do not reduce spending.** A refund is a credit, so it is treated as incoming money
   (like a Taobao/Pinduoduo refund arriving in WeChat Pay) and never touches `total_spending`.
3. **No `notes` field in the contract for now.** Period-level notes (e.g. "2 credits excluded")
   stay available via `spending_diagnostics()` and are not part of `SpendingReport`.
4. **Months use China time (Asia/Shanghai, UTC+8).** P2: please filter
   `GET /transactions?period=YYYY-MM` by the same rule, so the transaction list and the
   spending report always match.

All analytics are descriptive, run on synthetic data, and are not financial advice.
