# Cancel a pending approval

P2 now lets the authenticated demo owner withdraw an issued approval ticket
before its operation completes. This is separate from P1's draft/plan controls
and separate from executing a subscription cancellation.

## API and state transitions

```text
POST /api/v1/actions/{approval.action_id}/cancel
{action_digest: approval.action_digest, idempotency_key}

GET /api/v1/actions/{approval.action_id}
```

Cancellation uses the P2-owned strict `CancelApprovalRequest` in
`backend/app/api/schemas.py`; shared contracts and P1's tool catalog are unchanged.
It requires both fields, rejects extras, and resolves ownership from the trusted
demo session. Wrong-owner/unknown IDs return 404. A mismatched digest returns
400 without changing the ticket, financial data, or verification-failure counter.
Malformed bodies return 422 before the operation starts.

| Current state | Cancellation result |
|---|---|
| `PENDING_CONFIRMATION` | `CANCELLED`, one cancellation audit, no financial execution |
| `PENDING_MFA` | `CANCELLED`, OTP removed/retired, one cancellation audit, no execution |
| Explicitly cancelled by this endpoint | 200 replay with the same cancellation audit ID |
| `COMPLETED`, `FAILED`, `REJECTED` | 409; terminal status and financial outcome remain unchanged |
| Previously expired/cancelled without an explicit cancellation audit | 409; existing cancellation remains intact |

A still-pending ticket can be revoked even if its expiry has passed or the user
is locked. Revocation only removes permission; it does not clear the user lock.
Existing balances, daily totals, transaction records, and subscription status
are never changed by this endpoint. Withdrawing approval for subscription
cancellation leaves the subscription active. No completed operation is reversed.

The response is the existing shared `ExecutionResult`. The successful audit is
`APPROVAL_CANCELLED_BY_USER` with reason `USER_CANCELLED_APPROVAL`, owned action
ID, canonical payload digest, and previous/current status. No OTP or arbitrary
user text is added to it. `record.audit_id` stores the cancellation audit for
replay. Completed records retain their execution audit ID.

The GET endpoint returns only owned `ApprovalMetadata`:
`{action_id, action_digest, tier, status}`. It never executes an action, issues
an OTP, or contacts P1. It supports recovery after a cancellation conflict or a
lost response, including when the mock agent is selected.

## Execution race and retry behavior

Cancellation uses the same `execute_claimed_action` guard as confirmation and
verification, with user/action locks held until commit. If cancellation wins,
later confirmation/MFA cannot execute the ticket. If execution wins, cancellation
cannot overwrite `COMPLETED`. A request that read a pending state before a
competing claim committed gets HTTP 409 and can retrieve the current status.

Status, OTP retirement, and cancellation audit commit together. Failed commits
roll all of them back and leave the original pending ticket retryable. Repeating
a committed cancellation returns the original audit without another event.
Idempotency remains action-scoped; this does not add cross-action deduplication.

## Frontend and continuation

**Cancel approval** appears for pending confirmation and pending MFA. It is not
shown for terminal tickets. The card distinguishes cancelling an approval from
successfully executing `request_subscription_cancel`. Confirmation, verification,
cancellation, and conversation retries on one ticket are disabled while that
ticket has an in-flight operation in the current page. Other tabs/processes are
protected by the database guard.

The frontend does not optimistically label the ticket cancelled. It uses the
successful bank response; on a conflict or uncertain response it retrieves owned
metadata first. If that retrieval also fails, it reports an unverified outcome
and lets the user retry. A server-verified completion is shown as completed,
rather than claiming cancellation succeeded.

After cancellation, the ordinary continuation endpoint feeds P1 the original
conversation/proposal/tool/arguments and `CANCELLED` result, referencing the actual
cancellation audit. P1 consumes the request and stops dependent plan steps.
A missed browser callback is recovered on the next chat turn. Provider failure
does not undo the committed cancellation. Cancelling a later transfer step
does not undo an earlier completed subscription cancellation.

`pause plan`, `stop plan`, and `never mind` retain their existing semantics:
they do not automatically cancel issued tickets. Use the explicit card control
for that purpose. Human review workflow is separate work.

## Deployment and manual checks

Rebuild both services and reload the browser:

```powershell
docker compose up -d --build backend frontend
```

No new migration is required for cancellation. If the previous safety-lock
change has not been deployed, startup still applies its migration `0006_safety_lock`.

1. Ask **Transfer 20 CNY to Bob**, then click **Cancel approval**. The card shows
   cancelled, execution controls disappear, and balance/daily totals are unchanged.
2. Request a transfer that crosses the cumulative 1,000 CNY threshold while within
   available funds. Confirm to reach MFA, then cancel approval. The code no longer
   works and the pending entry leaves the demo inbox.
3. With the subscription active, ask **Cancel iQIYI VIP Monthly then transfer
   45 CNY to Bob**. Cancel the first approval: the subscription remains active,
   P1 stops the plan, and no transfer is proposed.
4. Complete an ordinary transfer: its card offers no cancellation. A direct
   cancellation request returns 409 and cannot restore money or remove the debit.

Tests cover strict bodies, ownership, digest binding, both pending states,
expiry/lock handling, replay, commit rollback, no financial/subscription mutation,
P1 continuation/recovery, provider outage, and deterministic cancellation versus
confirmation/MFA races in both winning orders on SQLite and disposable PostgreSQL.
