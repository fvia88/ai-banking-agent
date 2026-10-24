# P5 expected outputs and cancellation walkthrough

Owner: P5. Companion to `README.md` in this folder. The shared-fixture cases below are
checked by `subscriptions/tests/test_walkthrough.py`; if a rule changes, change both.

All data is synthetic. Merchant cancellation is **simulated**: nothing real is contacted.

## 1. Words to use in the UI and in chat replies

Confidence is evidence that a charge repeats. It is not status, permission or support.

| What the system knows | Say | Never say |
|---|---|---|
| Detector found it, no stored record for this user | "Recurring charge detected" (a candidate) | "active subscription", "you can cancel it" |
| Stored record, status `active`, support `true` | "Active subscription, cancellation available" | |
| Stored record, status `active`, support `false` | "Active subscription, cancellation not available here" | "I will cancel it" |
| Stored record, status `cancelled` | "Cancelled" (charges before the cancellation remain visible as history) | "active" |
| Low confidence (below 0.70) | "Possible recurring charge" | "subscription" as a fact |

Confidence 0.70 or higher is read as "likely recurring"; lower scores as "possible".
This cut-off was agreed with P2. It never replaces the stored status.

## 2. Listing (shared fixtures, user_001)

`detect_subscriptions` on `fixtures/transactions.json`:

| Candidate id | Merchant | Amount | Cadence | Confidence | Evidence |
|---|---|---|---|---|---|
| `sub_cloudmusic` | CloudMusic | 19.00 | monthly | 0.85 | tx_005, tx_006, tx_007, tx_008 |
| `sub_streambox` | StreamBox | 39.00 | monthly | 0.85 | tx_001, tx_002, tx_003, tx_004 |

Raw `cancellation_supported` is `false` for both. This is intended. Metro (two charges,
different prices), one-off purchases, credits and the transaction with an injected
instruction are not listed. Listing alone grants no permission to cancel.

## 3. Cancellation walkthrough (stored records from `fixtures/subscriptions.json`)

| Step | Call | Expected result |
|---|---|---|
| 1. Ask about StreamBox | `assess_stored_cancellation(candidate, stored, "user_001")` | `eligible=True`, `ELIGIBLE`, `stored_subscription_id="sub_streambox"`, `requires_confirmation=True` |
| 2. Ask about CloudMusic | same | `eligible=False`, `CANCELLATION_NOT_SUPPORTED` |
| 3. User confirms StreamBox | P2 stores `status="cancelled"` once | stored record changes; no credit or refund; one audit id |
| 4. Re-list | `detect_subscriptions` again | StreamBox is still detected (past charges stay as evidence) |
| 5. Enrich after cancel | `enrich_candidates` | StreamBox `cancellation_supported=False` |
| 6. Retry cancel | `assess_stored_cancellation` | `eligible=False`, `ALREADY_CANCELLED`, record id returned |
| 7. Restart the app | same call | still `ALREADY_CANCELLED` (only if P2 persisted the status) |
| 8. Another user | same call with another `user_id` | `eligible=False`, `SUBSCRIPTION_NOT_FOUND`, `stored_subscription_id=None` |
| 9. Unknown name | candidate with no stored record | `eligible=False`, `SUBSCRIPTION_NOT_FOUND` |
| 10. Two records, same merchant and price | candidate for that merchant | `eligible=False`, `AMBIGUOUS_SUBSCRIPTION` |

Blocked cases (3 reason codes besides the two older ones) must produce **no executable
proposal**. The reply should offer the verified choices instead (stored, active, supported).

## 4. Alice's backend records (iQIYI)

Data: `backend/app/db/seed.py` (account `acc_cny_001`) and the stored record in
`adapters.py` (`usr_demo_01`). Checked by the `test_alice_*` tests.

Detector input: two debits of 45.00 for "iQIYI VIP Monthly" (`tx_demo_003` on 2026-09-05,
`tx_demo_002` on 2026-10-05, 30 days apart). The Starbucks debit and the payroll credit
are not recurring and are not listed.

| Item | Expected |
|---|---|
| Candidate id | `sub_iqiyi_vip_monthly` |
| Amount, cadence | 45.00, monthly |
| Confidence | 0.40 (only two charges) |
| Evidence | tx_demo_003, tx_demo_002 |
| Raw `cancellation_supported` | `false` |
| Stored record | `sub_iQIYI_01`, user `usr_demo_01`, active, supported |

What this shows:

* The charges are **recurrence evidence at low confidence**, so the listing wording is
  "possible recurring charge". They do not prove the subscription is active.
* The candidate id and the stored id **differ**, so mapping works by merchant name (the
  name is unique for this user). Never assume the ids are equal.
* Confidence does not decide permission. The stored record is active and supported, so
  `assess_stored_cancellation` gives `ELIGIBLE` with `stored_subscription_id="sub_iQIYI_01"`.
  The UI may call it an active subscription because the **stored record** says so.
* After the stored status becomes `cancelled`: `ALREADY_CANCELLED`, same stored id.
* Another user id: `SUBSCRIPTION_NOT_FOUND`.
* Test iQIYI separately from StreamBox and CloudMusic (shared fixtures). Do not mention
  any merchant that is not in the data (for example Netflix).

## 5. Rules for P2 when wiring (no change to `backend/` is made by P5)

1. Call `detect_subscriptions` on one selected account's history. The dashboard and chat
   must use the same account scope, so two accounts never merge into one recurrence.
2. Load only the authenticated user's stored `Subscription` records. Never take `user_id`
   from the request body or from chat text.
3. List with `enrich_candidates(report, stored, user_id)`.
4. Before proposing and again before executing, call
   `assess_stored_cancellation(candidate, stored, user_id)` and act on
   `stored_subscription_id`, not on the candidate id.
5. After a confirmed cancellation save `status="cancelled"` in one atomic step with the
   audit entry. Without this, repeat protection does not exist.

## 6. Limits to state in the report and demo

* Detection needs at least two charges, so confidence is low for new subscriptions.
  Annual detection needs more than a year of history.
* Confidence is a heuristic score, not a probability.
* Different spellings of one merchant are treated as two merchants.
* The three added reason codes need P2 and P1 agreement before the UI relies on them.
* Cancellation is simulated; no merchant is contacted and no balance is credited.
