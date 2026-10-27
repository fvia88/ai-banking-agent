# P5 final evidence: subscription detection, mapping and cancellation semantics

Owner: P5. Short version for the report and the demo. Details and the full tables are in
`expected_outputs.md` (same folder); module rules are in `README.md`. All data is
synthetic. Cancellation is simulated: no merchant is contacted and no money moves.

## 1. What P5 delivers

* **Detection** (`subscriptions/detector.py`): finds recurring debits in one account's
  history and returns candidates with amount, cadence, confidence and evidence
  transaction ids. Pure calculation: no database writes, no external calls, and the
  transaction `note` is never read.
* **Mapping** (`subscriptions/mapping.py`): links a candidate to the user's own stored
  record and decides whether cancellation may be proposed. The stored record, not the
  detector, is the source of truth for status and support.
* **Decision order**: `SUBSCRIPTION_NOT_FOUND`, then `AMBIGUOUS_SUBSCRIPTION`, then
  `ALREADY_CANCELLED`, then `CANCELLATION_NOT_SUPPORTED`, then `ELIGIBLE`.
  `requires_confirmation` is always true. Confidence is evidence only and never gives
  permission.

## 2. Short detection and mapping example (Alice, iQIYI)

Input: two debits of 45.00 for "iQIYI VIP Monthly", 30 days apart (`tx_demo_003`,
`tx_demo_002`).

| Step | Result |
|---|---|
| Detector | candidate `sub_iqiyi_vip_monthly`, 45.00, monthly, confidence 0.40 (two charges only) |
| Wording | "Possible recurring charge" (below 0.70) |
| Stored record | `sub_iQIYI_01`, user `usr_demo_01`, active, cancellation supported |
| Mapping | by merchant name; the two ids differ, so the stored id is used |
| Decision | `ELIGIBLE`, `stored_subscription_id = sub_iQIYI_01`, confirmation required |
| Other user | `SUBSCRIPTION_NOT_FOUND` |
| After cancellation | `ALREADY_CANCELLED` |

## 3. Cancel, repeat and restart walkthrough (real backend, disposable database)

Run on 26 Oct 2026 through the HTTP API with the demo identity `usr_demo_01`.

| Step | Observed |
|---|---|
| Ask to cancel iQIYI | `PENDING_CONFIRMATION`, one proposal for `sub_iQIYI_01`; record still `active` |
| Approve | `COMPLETED`, one audit id; record `cancelled` |
| Replay the approval | `COMPLETED`, "idempotent replay", same audit id, no second cancellation |
| Ask again | `REJECTED`, `ALREADY_CANCELLED`, no action |
| Restart the app | existing data preserved; record still `cancelled`; not reactivated |
| Balance | 15250.00 CNY before and after; cancellation adds or removes no money |
| Wrong account | 404 |
| Blocked requests (`user_001`) | unsupported (CloudMusic), unknown (Netflix) and vague ("my subscription") create no action and offer only verified choices; StreamBox gets a proposal that still needs approval |

## 4. Test evidence

| Check | Result |
|---|---|
| `python -m pytest subscriptions tests -q` | 76 passed |
| `python - < p5_check.py` (27 scripted cases) | 27 OK, 0 MISMATCH |
| Backend subset (`PYTHONPATH=backend`, `-k "subscri or cancel"` and the full backend run) | 27 passed, 7 skipped (the skipped tests need PostgreSQL) |

Fill in at the freeze: release commit `________` (`git rev-parse --short HEAD`), date
`________`. Re-run the first two checks on that commit.

## 5. Limits to state

* Detection needs at least two charges, so new subscriptions have low confidence (0.40).
  Annual detection needs more than a year of history.
* Confidence is a heuristic score, not a probability.
* Different spellings of one merchant count as two merchants.
* The raw detector flag `cancellation_supported` is always false by design; support
  comes only from the stored record.
* Cancellation is simulated; the merchant is never contacted.
* Detection is per selected account. Dashboard and chat must use the same account scope.
* Not verified by P5: the browser screen (no Node.js on the P5 machine) and PostgreSQL.
* The agent runs above used a deterministic mock provider, not a live model.
* **Open item for P1 and P2** (not a P5 defect): after a completed cancellation the
  planner does not yet propose the follow-up transfer, so "cancel, then transfer" must
  not be described as working end to end until demonstrated. Blocked replies also use
  the status `COMPLETED` while a repeated cancellation uses `REJECTED`.

## 6. Freeze checklist (27 Oct)

1. `git status` is clean on `feature/subscriptions-detector`.
2. Re-run the two checks in section 4 on the final team commit.
3. Put the commit id and date in section 4 here and in `expected_outputs.md` section 7.
4. Re-run the planner check (section 8 of `expected_outputs.md`) only if P1 and P2 report
   the transfer step is wired; otherwise keep the open-item wording.
5. Compare the screen wording with section 1 of `expected_outputs.md` once screenshots
   are available.
6. Commit `docs/subscriptions` only. Do not push until the team agrees.
