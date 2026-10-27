# P3 Finance + MFA: Day 4 Handoff

For P1/P2 assembling the deck, video and README. Everything here was checked against
`main` at `d0581e7` on 2026-10-27. Details: `MFA.md`, `RULES.md`, `SIGNOFF.md`.

## 1. Slide content: MFA (Red-tier transfers)

- Red tier: today's cumulative transfers would exceed CNY 1000 (Asia/Shanghai day).
- Flow: chat proposes, user confirms, OTP challenge, correct code, then exactly one debit and an audit ID.
- **No money moves before the correct code.** Confirm alone never debits.
- Random 6-digit code, 5-minute expiry, 3 attempts per challenge, single use.
- Security policy is re-checked at confirm **and** at verify. A valid code cannot override a
  new account lock or a changed daily tier.
- Safe retries: a duplicate or lost-response retry returns the original audit ID and never
  debits twice. A crash before commit moves no money.
- Safety lock: 3 wrong codes or bad confirmations within 15 minutes lock transfers and
  cancellations until a manual operator reset.

## 2. Slide content: spending analysis

- Deterministic `Decimal` maths: the same input always gives the same report.
- Months are bucketed in Asia/Shanghai time.
- Outbound transfers count as spending. Income and refunds are excluded, and refunds are not netted.
- Category totals plus anomaly flags: large versus category history, large one-off, category month spike.

## 3. Checked report example

Alice / `acc_cny_001`, fresh seed, deterministic mode (`AGENT_PROVIDER=mock`).

| | Before | After "Transfer 1200 CNY to Bob" + OTP |
|---|---|---|
| Balance | 15250.00 | 14050.00 |
| October spending | 80.00 (Starbucks 35 + iQIYI 45) | 1280.00 (+ Transfers 1200.00) |
| September spending | 45.00 | 45.00 |

Browser-tested on 2026-10-27: one wrong code showed "2 attempt(s) remaining", and the correct
code completed the transfer (action `act_69cbc4145e44`, audit `aud_5f4c1feb08`). The audit
trail shows one challenge issued, one verification failure and exactly one execution.

These numbers only hold on a fresh database. Earlier demo transfers on the shared database
change them.

If the deck shows `reports/2026-09_synthetic_anomalies` (CNY 9254.70, seven flags), it
**must be labelled synthetic** and must not be attributed to Alice.

## 4. Limitations (state these in the deck and README)

- OTP delivery is **simulated**: the code appears in the on-screen demo inbox and the backend
  console. No SMS or email is sent.
- Identity is the `X-Demo-User-Id` demo header, not real login.
- Not production MFA: no device binding, and the lock reset is a local operator command.
- The MFA race tests ran on SQLite. P2 reports that the shared race tests pass on PostgreSQL;
  P3 has not re-run them (no PostgreSQL available locally).
- Demo replies use deterministic mode (`AGENT_PROVIDER=mock`). Label them that way, not "live Gemini".

## 5. Test evidence

- Full Python suite on `main` at `d0581e7`: **815 passed, 22 skipped**. All skips are
  PostgreSQL-only tests that need `MIGRATION_TEST_POSTGRES_ADMIN_URL`.
- To be re-run on the final release commit, and this line updated.
- Updated design doc: `MFA.md`.

## 6. For the recording

- Show **at most one** wrong OTP. Three wrong codes lock Alice.
- Do not say "code sent to your phone". Say "simulated code in the demo inbox".
- Do not show "success" until the card says `COMPLETED`.
- P3 reviews the final video for these points.
