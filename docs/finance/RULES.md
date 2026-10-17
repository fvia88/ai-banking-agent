# P3 Finance Analytics: Calculation Rules (v0.2.0, matches repo `contracts/`)

All rules are deterministic: the same input set, in any order, produces an identical
`SpendingReport`. Thresholds can be changed in `SpendingConfig` / `AnomalyConfig`. The
defaults below are what `analyze_spending` uses.

## 1. `analyze_spending(transactions, period) -> SpendingReport`

| Item | Rule |
|---|---|
| `period` | Must be `YYYY-MM` (month 01–12), or `ValueError` is raised. Nothing else raises. |
| Month bucketing | Timestamps are converted to **Asia/Shanghai (fixed UTC+08:00)** and bucketed by local calendar month. Example: `2026-08-31T17:30:00Z` → 1 Sep 01:30 CST → `2026-09`. |
| `total_spending` | Exact `Decimal` sum of **valid debits** in the period. Always equals the sum of `category_totals`. |
| Credits | **Never spending.** Income, refunds and inbound transfers are all excluded (T12). |
| Refunds | Credits labelled `Refund`/`Reversal`/`Chargeback`/`退款`, or whose merchant contains those words. Totals are **gross**, so refunds do not reduce spending. They are listed as notes. |
| Outbound transfers | Counted by default. They can be excluded with `SpendingConfig.excluded_debit_categories`. |
| Accounts | All inputs are aggregated. The caller passes one user's transactions. |
| Money | `Decimal`, quantized to cents. The contract serializes it as `"123.45"`. |

## 2. Validation

The shared `Transaction` model rejects these **before** they reach `finance/`:
amount ≤ 0, more than 2 decimals, or not numeric; a timestamp without a timezone; a direction
that isn't `debit`/`credit`. The tests confirm this.

`finance/` also re-checks amount and timestamp for objects built without validation. Those are
excluded with an `INVALID_AMOUNT` / `INVALID_TIMESTAMP` anomaly.

| Condition | Treatment | Anomaly code |
|---|---|---|
| Same `transaction_id`, identical content | Counted **once** | `DUPLICATE_TRANSACTION_ID` |
| Same `transaction_id`, different content | **All copies excluded**, regardless of input order | `CONFLICTING_DUPLICATE_ID` |

## 3. Categories (`category_totals` keys)

1. If the provided `category` carries information, it is **kept as written**: control
   characters are stripped, whitespace is collapsed, and length is capped at 64. T12 expects
   `Food`, `Subscriptions`, `Other` and so on to be preserved. Labels that differ only in
   letter case are merged into one bucket, shown with the spelling of the earliest transaction.
2. If the label is missing or unknown (`""`, `unknown`, `uncategorized`, `n/a`, `none`,
   `null`, `-`, `未知`, `未分类`), ordered merchant keyword rules are used
   (`finance/categories.py`). ASCII keywords match whole words only (`rent` ≠ "Parent").
3. Otherwise → `Uncategorized`.

`Other` is a real label and is **not** treated as unknown.

## 4. Spending anomalies

History = the 3 calendar months immediately before `period`, taken from the same input list.

| Code | Fires when |
|---|---|
| `LARGE_VS_CATEGORY_HISTORY` | The category has ≥3 debits in its history, the debit is > 3 × their median, **and** it is ≥ 100.00 above the median |
| `LARGE_TRANSACTION` | The category has <3 debits in its history **and** the debit is ≥ 2000.00 |
| `CATEGORY_MONTH_SPIKE` | The input reaches back ≥3 months, the category had spending in ≥2 of them, the month total is > 1.5 × the 3-month mean (empty months count as 0) **and** ≥ 200.00 above it. The anomaly is attached to the category's largest debit that month. |
| `POSSIBLE_DUPLICATE_CHARGE` | Two debits with different IDs share account, merchant and amount, ≤ 10 minutes apart. The later one is flagged. **Both are counted.** |

## 5. Output format and safety

* Contract: `Anomaly(transaction_id, reason)`. `reason` is `"<CODE>: <explanation>"`, so it is
  both machine-parseable and readable.
* Findings that are not about one transaction (credits excluded, refunds, no spending, multiple
  accounts) cannot be expressed as an `Anomaly`. They are available from
  `spending_diagnostics()` and are printed as "Notes" by the CLI.
* Order: spending anomalies first, then data quality; warnings before info; then code and ID.
* Explanations come from templates and are **descriptive only**, never financial advice.
* `merchant` and `note` are untrusted (T09). They never appear in any `reason`.

## 6. Fixtures and expected results

**Team fixture** (`fixtures/transactions.json`), T12 for `2026-10`: total **1843.00**.
Category totals: Subscriptions 58.00, Food 360.00, Transport 125.00, Shopping 1200.00,
Education 80.00, Other 20.00. Credits tx_012 (500.00) and tx_019 (300.00 refund) are excluded.

**P3 synthetic fixture** (`finance/tests/data/transactions_synthetic.json`), hand-computed:

| Period | Total | Notes |
|---|---|---|
| 2026-04 | 99.00 | |
| 2026-05 | 0.00 | Empty month (zero-filled by `monthly_totals`) |
| 2026-06 / 07 / 08 | 664.70 / 601.90 / 668.00 | Steady history, no anomalies |
| 2026-09 | **9254.70** | Every edge case: credits, refund, duplicates, UTC boundary, injection text, spikes |
| 2026-10 | 60.00 | `2026-09-30T16:30Z` lands here in CST |
