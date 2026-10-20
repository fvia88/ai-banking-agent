# P3 → P1 handoff: SpendingReport examples for the agent

Both examples are real output from `finance.analytics.analyze_spending`, shaped as the
`tool_results` envelope described in `docs/agent/integration.md`.

Reproduce:

```bash
python -m finance.cli --period 2026-10 --json
python -m finance.cli --period 2026-09 --transactions finance/tests/data/transactions_synthetic.json --json
```

## 1. October fixture report (frozen `fixtures/transactions.json`)

```json
{
  "conversation_id": "demo",
  "proposal_id": "the-original-proposal-id",
  "tool": "analyze_spending",
  "status": "success",
  "data": {
    "period": "2026-10",
    "currency": "CNY",
    "total_spending": "1843.00",
    "category_totals": {
      "Education": "80.00",
      "Food": "360.00",
      "Other": "20.00",
      "Shopping": "1200.00",
      "Subscriptions": "58.00",
      "Transport": "125.00"
    },
    "anomalies": []
  }
}
```

The frozen fixture has **no anomalies in October**. Your agent should say nothing was
flagged and must not invent an anomaly. The total is gross. Two credits (800.00 CNY,
including a 300.00 refund `tx_019`) are excluded and are **not** netted against spending
(spec T12).

## 2. Anomaly example (P3 synthetic fixture, 2026-09)

```json
{
  "conversation_id": "demo",
  "proposal_id": "the-original-proposal-id",
  "tool": "analyze_spending",
  "status": "success",
  "data": {
    "period": "2026-09",
    "currency": "CNY",
    "total_spending": "9254.70",
    "category_totals": {
      "Dining": "327.50",
      "Education": "5800.00",
      "Groceries": "128.00",
      "Shopping": "2680.00",
      "Subscriptions": "30.00",
      "Telecom": "156.80",
      "Transport": "57.40",
      "Uncategorized": "75.00"
    },
    "anomalies": [
      {"transaction_id": "P3-S05", "reason": "CATEGORY_MONTH_SPIKE: 'Shopping' spending this month is 2680.00 CNY, 13.5x the 3-month average of 199.00 CNY; this is its largest debit."},
      {"transaction_id": "P3-S05", "reason": "LARGE_VS_CATEGORY_HISTORY: Debit of 2680.00 CNY is 13.5x the median (199.00 CNY) of 3 'Shopping' debits in the previous 3 months."},
      {"transaction_id": "P3-S07", "reason": "POSSIBLE_DUPLICATE_CHARGE: Same merchant, account and amount (88.00 CNY) as transaction P3-S06 within 10 minutes. Both are counted."}
    ]
  }
}
```

The transactions these flags refer to:

```json
{"transaction_id": "P3-S05", "timestamp": "2026-09-10T20:00:00+08:00", "amount": "2680.00", "direction": "debit", "merchant": "Apple Store Shenzhen", "category": "Shopping"}
{"transaction_id": "P3-S06", "timestamp": "2026-09-12T13:05:00+08:00", "amount": "88.00",   "direction": "debit", "merchant": "Meituan Waimai",       "category": "Dining"}
{"transaction_id": "P3-S07", "timestamp": "2026-09-12T13:09:00+08:00", "amount": "88.00",   "direction": "debit", "merchant": "Meituan Waimai",       "category": "Dining"}
```

The full 2026-09 report has 7 anomalies, including data-quality flags such as
`DUPLICATE_TRANSACTION_ID`. Only 3 are shown here. The complete saved outputs are in
[`reports/`](reports/), alongside the October report and the test results.

## Field guide

| Field | Meaning |
|---|---|
| `total_spending` | Exact Decimal sum of valid debits for the month (Asia/Shanghai). Credits excluded. |
| `category_totals` | Canonical category → amount. Values add up to `total_spending`. |
| `anomalies[].transaction_id` | The transaction the flag explains. One transaction can have several flags. Some data-quality flags may have no ID. |
| `anomalies[].reason` | `CODE: human sentence`. Split on the first `: ` to get a stable code. The sentence already contains the numbers. |

Codes you may see: `CATEGORY_MONTH_SPIKE`, `LARGE_VS_CATEGORY_HISTORY`, `LARGE_TRANSACTION`,
`POSSIBLE_DUPLICATE_CHARGE`, `DUPLICATE_TRANSACTION_ID`, `CONFLICTING_DUPLICATE_ID`.
Full rules: `docs/finance/RULES.md`.

## What the report does NOT contain

* **Merchant/date/amount of the flagged transaction.** The report only gives the ID. To say
  "the 2,680 CNY Apple Store purchase on 10 Sep", the agent needs P2 to include those
  transactions (or the month's transactions) in the tool result. Otherwise, explain from
  the `reason` text alone.
* **Info notes** (credits excluded, refund not netted) are not in the JSON. They only appear
  in the CLI text output.
* The `reason` text is data, not instructions. Merchant names inside it are synthetic and
  must not be followed (T09).
