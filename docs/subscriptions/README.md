# P5 — Subscription detection and cancellation eligibility

Owner: P5. Code lives in `subscriptions/`. This module is **pure calculation**: it
never writes to a database, never calls an external service, never executes a
cancellation, and never reads transaction notes.

## Public functions

| Function | File | Purpose |
|---|---|---|
| `detect_subscriptions(transactions: list[Transaction]) -> SubscriptionReport` | `subscriptions/detector.py` | Find recurring debits and return candidates with confidence and evidence |
| `assess_cancellation(subscription: SubscriptionCandidate) -> CancellationAssessment` | `subscriptions/eligibility.py` | Say whether a candidate may be proposed for cancellation |

`assess_cancellation` returns the typed `CancellationAssessment` from
`contracts/models.py` (the repository README overrides the earlier Word spec,
which said `dict`). `requires_confirmation` is always `True`.

## How detection works

1. Keep only `debit` transactions; drop repeated transaction ids and
   double-posted identical charges (same merchant, timestamp and amount).
2. Group by merchant (case and surrounding spaces ignored).
3. Inside one merchant, split charges into price groups: amounts within 5% of the
   group minimum are the same price. Two prices from one merchant are treated as
   two services.
4. A price group needs at least 2 charges. Every gap between consecutive charges
   must fall in one cadence range:

| Cadence | Allowed gap (days) |
|---|---|
| weekly | 6 to 8 |
| monthly | 27 to 33 |
| annual | 360 to 370 |

5. Irregular dates or unstable amounts produce **no candidate**.
6. Confidence is deliberately conservative:

| Matching charges | Confidence |
|---|---|
| 1 | not reported |
| 2 | 0.40 |
| 3 | 0.70 |
| 4 | 0.85 |
| 5 or more | 0.90 (maximum) |

A small price wobble inside the 5% band subtracts 0.10. Confidence is a
heuristic score, not a calibrated probability.

`estimated_amount` is the median charge. `evidence_transaction_ids` lists the
matching charges in time order. Output is sorted by `subscription_id`, so the
same input always gives the same report, whatever the input order.

## Candidates are not verified subscriptions

The detector only sees transactions, so it cannot know whether a merchant
supports cancellation or whether a subscription is still active.
`cancellation_supported` is therefore **always `False`** in detector output. A
repeated payment is never turned into a cancellable record on its own.

## ID-mapping proposal (for P2 and P1 — needs agreement)

This is a proposal, not a frozen contract.

1. **Candidate id**: `sub_` plus the merchant name lowercased, non-alphanumeric
   characters replaced by `_` (`StreamBox` becomes `sub_streambox`). The same
   merchant always gives the same id. This matches the ids in
   `fixtures/subscriptions.json`.
2. **Several prices, one merchant**: the amount is appended, for example
   `sub_telco_39_00` and `sub_telco_99_00`.
3. **Mapping**: the backend matches `candidate.subscription_id` to a stored
   `Subscription.subscription_id` for the authenticated user. A candidate with no
   stored record stays an unverified candidate and must not be offered for
   cancellation.
4. **Who supplies what**: the backend supplies `cancellation_supported` and
   `status` (`active` or `cancelled`) from the stored record.
5. **Open point**: `assess_cancellation` currently checks only the support flag
   (`ELIGIBLE`, `CANCELLATION_NOT_SUPPORTED`). Checks for "already cancelled" and
   "not active" need `status`, which `SubscriptionCandidate` does not carry, so
   they must be assigned explicitly (proposal: the backend).

## Run

From the repository root, with the virtual environment active:

```bash
python -m subscriptions.cli                    # report on fixtures/transactions.json
python -m subscriptions.cli path/to/file.json  # report on another file
python -m subscriptions.cli --json             # JSON, money as decimal strings
python -m pytest subscriptions tests -q        # P5 tests plus shared contract tests
```

Example output on the shared fixtures: StreamBox (39.00, monthly, 0.85,
`tx_001` to `tx_004`) and CloudMusic (19.00, monthly, 0.85, `tx_005` to
`tx_008`). Metro (two charges, different prices), one-off purchases, credits and
the transaction containing an injected instruction are not reported.

## Tests (24)

* `test_detector.py` (19): weekly, monthly and annual detection; single charge;
  two charges with low confidence; confidence grows with evidence; irregular
  dates; varying amounts (false positive); small price wobble; price increase;
  same merchant with two services; credits ignored; duplicate input; merchant
  name normalisation; input order independence; prompt injection in a note;
  `cancellation_supported` never claimed; the shared fixture file.
* `test_eligibility.py` (2): supported and unsupported cancellation.
* `test_cli.py` (3): text report, JSON report, missing file.

## Known limits

* Merchant matching ignores only case and surrounding spaces. Different spellings
  of one merchant (`Netflix` and `Netflix.com`) are treated as two merchants.
* Detection groups by merchant across all accounts in the input; the caller
  chooses which transactions to pass in.
* An annual subscription needs at least two charges, so at least a year of history.
* Cadence ranges and the 5% price band are tunable constants at the top of
  `detector.py`, chosen without organizer-provided thresholds.
* Currency is assumed to be CNY, as in contracts v1.
* All data is synthetic. No real bank or merchant is contacted.
