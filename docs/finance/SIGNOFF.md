# P3 Finance Sign-off (Day 1)

Review of how the backend feeds `finance.analytics.analyze_spending` in the running app,
plus the values the browser demo should show. Checked on `feature/finance` after `632ea84`.
Automated evidence: `backend/tests/test_finance_signoff.py`.

## Checklist

| Item | Result | Evidence |
|---|---|---|
| Backend calls the real engine, not the mock | ✅ `FinanceAdapterService` defaults to real (`USE_MOCK_FINANCE` unset) | `test_finance_bridge_is_real_engine_not_mock` |
| Selected account only | ✅ `api/chat.py` filters `TransactionModel.account_id == account_id`. Alice and the fixture account are never merged | `test_reports_are_scoped_to_the_selected_account` |
| Requested month plus history | ✅ The read loop passes all of the account's stored transactions. The engine picks the period and uses the previous 3 months as the anomaly baseline | `test_alice_september_demo_report`, finance unit tests |
| Timezone-aware timestamps | ✅ Seed and executor both store aware ISO strings. The executor writes UTC, and the engine buckets by the Asia/Shanghai month | `test_utc_executor_timestamp_is_bucketed_by_shanghai_month` |
| Refunds not netted | ✅ Credits, including refunds, are excluded and never subtracted from spending | `test_fixture_account_october_report`, `test_alice_october_demo_report` |

## Expected outputs: fresh database, before any demo transfers

| Dataset | Period | Total (CNY) | Categories | Anomalies |
|---|---|---|---|---|
| Alice / `acc_cny_001` (the browser account) | 2026-10 | **80.00** | Dining 35.00, Entertainment 45.00 | none (the 5000.00 payroll credit is excluded) |
| Alice / `acc_cny_001` | 2026-09 | **45.00** | Entertainment 45.00 | none |
| Fixture / `account_001` | 2026-10 | **1843.00** | Shopping 1200.00, Food 360.00, Transport 125.00, Education 80.00, Subscriptions 58.00, Other 20.00 | none (the 300.00 refund is not netted) |
| P3 synthetic fixture (**not Alice**) | 2026-09 | **9254.70** | see report | 7 flags |

Reports: `reports/2026-10_alice_demo.txt|json`, `reports/2026-10_fixture.txt|json`,
`reports/2026-09_synthetic_anomalies.txt|json`. The Alice data contains no anomaly. For the
"one real anomaly" in the deck, use the **labelled synthetic** September report. Do not
attribute it to Alice.

## Things the team needs to know

1. **Demo transfers change the spending report.** An executed transfer is a debit in the
   `Transfers` category and counts as spending (RULES.md, "Outbound transfers"). After the
   500 CNY Red-transfer demo, Alice's October report shows **580.00** with `Transfers 500.00`.
   Either record the spending scene *before* the transfer scene, or say this on camera.
   P1: the reply should not call it "unusual spending".
   (`test_executed_transfer_counts_as_spending_in_transfers_category`)
2. **The month changes at midnight Shanghai time, not UTC.** A transfer executed between
   00:00 and 08:00 Shanghai time on the 1st already counts in the new month. This is correct,
   but don't let it surprise anyone during recording.
3. **For P2 (`api/chat.py`): one bad stored timestamp breaks the whole report.** The read
   loop builds strict contract `Transaction`s, so a naive or unparseable timestamp raises a
   validation error. The user then gets an error instead of a report with that row flagged.
   Every current writer stores aware timestamps, so this is a robustness note, not a
   current bug.
4. **Demo inbox.** Owner-scoped, unused and unexpired codes only (`test_mfa.py`). Labelled
   simulated in both the API message (`[Simulated] …`) and the UI ("Demo inbox
   (simulated, no SMS/email sent)").
