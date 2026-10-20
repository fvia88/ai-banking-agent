# P3 → P2: what to pass into `analyze_spending`

```python
from finance.analytics import analyze_spending
report = analyze_spending(transactions, period)   # list[Transaction], "YYYY-MM"
```

## Checklist

- [ ] **One account only.** Filter by the selected `account_id` before calling.
  The function **adds up every transaction you pass it, across all accounts**. It does not
  filter by account or by user. (If several accounts get mixed in, it only records a
  `MULTIPLE_ACCOUNTS` note, which is not in the report.)
- [ ] **Requested month + the 3 months before it.** For `2026-10`, pass all transactions from
  `2026-07-01T00:00:00+08:00` up to `2026-11-01T00:00:00+08:00`.
  Totals only use the requested month, but anomaly detection compares against the previous 3
  months. With only one month of data you will get correct totals and **no history-based
  anomalies**. Passing more than 4 months is fine because the extra rows are ignored.
- [ ] **Use Asia/Shanghai (UTC+08:00) month boundaries** in your DB query, not UTC.
  Example: `2026-09-30T16:30:00Z` is 1 Oct 00:30 in China time and counts as **October**.
  Building the window in UTC drops or shifts transactions at month edges.
  `GET /transactions?period=YYYY-MM` should use the same boundaries.
- [ ] **Validated `contracts.models.Transaction` objects.** Build them with
  `Transaction.model_validate(row)` so amounts are 2-decimal strings > 0 and timestamps carry
  an offset. Never use floats. Read the DB `Numeric`/`Decimal` value and format it as `"123.45"`.
- [ ] **Pass the rows raw. Do not pre-clean them.** Include credits, refunds and duplicates.
  P3 excludes credits, de-duplicates identical IDs and flags conflicting ones itself.
  Removing them first hides those flags.
- [ ] **`period` is `YYYY-MM`.** A malformed period is the only thing that raises
  (`ValueError`). Map it to `ErrorResponse` (for example `INVALID_PERIOD`, HTTP 400). Bad
  transactions never raise. They are left out of totals and explained in `report.anomalies`.
- [ ] **Read-only and pure.** No DB session, user ID or config is needed. It is safe to call
  for a Green / read-only tool. Feed the returned `SpendingReport` to P1 as the
  `analyze_spending` tool result.

## Spending rules (gross)

| Item | Treatment |
|---|---|
| Credits (income, inbound transfers) | Never spending, so excluded |
| Refunds | Excluded. They do **not** reduce spending |
| Outbound transfers (debits) | **Counted by default**. Can be excluded with `build_spending_report(..., SpendingConfig(excluded_debit_categories=frozenset({"Transfer"})))` |

## Not in `SpendingReport`

General notes such as "credits excluded", "refund not netted" and "multiple accounts" are
**not** in the report, because the frozen contract has no field for them. They come from
`finance.analytics.spending_diagnostics(transactions, period)`.

## Agreed with P2 (Marvel)

- The backend filters to the selected account(s) before calling.
- The backend computes the 4-month window (requested month + 3 previous) and passes all of it.
- Timestamps are stored in UTC as ISO 8601 strings with an explicit offset.
- Account IDs are opaque strings (for example `acc_cny_001`, or UUIDs at runtime).
- Gross rules confirmed: credits excluded, refunds don't reduce spending, outbound transfers count.
- Notes from `spending_diagnostics` are **not shown in the user-facing app**. The backend
  only logs them for debugging. The UI shows categories, totals and `report.anomalies`.
  No contract change is needed.

## Open issues (found in `main`, 20 Oct)

1. **Two sets of IDs.** The frozen `fixtures/` use `account_001`. The backend seed
   (`backend/app/db/seed.py`) uses `acc_cny_001` / `usr_demo_01`, with 4 transactions of its own.
   T12 (October = 1843.00) can't be reproduced through the backend until the seed loads
   `fixtures/transactions.json` or an ID mapping is agreed.
2. **Month filter matches on text.** `backend/app/api/transactions.py` filters with
   `timestamp.startswith(period)`, which compares the first characters of the timestamp string.
   That only works while timestamps are stored with `+08:00`. With UTC storage, month edges are
   wrong. Use `>= <first day of month−3>T00:00:00+08:00` and
   `< <first day of month+1>T00:00:00+08:00`.
3. **4-month window not built yet.** The current filter returns one month. P3 will check a
   report through the backend once the window is built.

## Sanity check

The frozen `fixtures/transactions.json` for `2026-10` must give `total_spending == "1843.00"`
(T12). Rules: `docs/finance/RULES.md`. Examples: `docs/finance/P1_HANDOFF.md`.
