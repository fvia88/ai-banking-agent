# Frontend approval metadata transport

The P2 HTTP layer now keeps server approval metadata separate from canonical
tool arguments. Both mock and real P1 proposals use this representation, including
follow-up actions from `/api/v1/actions/{action_id}/continue` and missed-callback
recovery on `/api/v1/chat`.

## Response contract

Each mutation in `ChatOutput.actions` has this shape:

```json
{
  "proposal_id": "prop_from_p1",
  "tool": "request_transfer",
  "arguments": {
    "source_account_id": "acc_cny_001",
    "recipient_id": "usr_bob_01",
    "amount": "20.00",
    "currency": "CNY"
  },
  "rationale": "Transfer requested by the user",
  "approval": {
    "action_id": "act_from_backend",
    "action_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "tier": "YELLOW",
    "status": "PENDING_CONFIRMATION"
  }
}
```

The digest above is illustrative. Runtime digests are computed from the tool
name and canonical financial payload only. Cancellation arguments contain only
`subscription_id`. Read results and clarification replies have `actions: []`.

`approval.action_id` identifies the server ticket for confirmation, verification,
and continuation. `proposal_id` correlates P1's original request; it is never used
as the execution ID. Tier and status come from backend records, not agent text.
The frontend displays explicit status and requires a valid approval object;
it does not default missing metadata to Yellow or extract it from arguments.

`backend/app/api/schemas.py` defines P2's `AppChatOutput`, `PresentedAction`, and
`ApprovalMetadata`. Shared `contracts.models.ActionProposal`, `ChatOutput`, P1's
state, and P1's `tool_results` envelopes remain unchanged. HTTP consumers use the
P2 presentation schema. Internal agent calls use the original canonical models;
do not pass the presentation object back into P1. All canonical tool argument
models continue rejecting metadata and other unexpected fields.

## Confirmation and MFA requests

The backend now imports both request classes directly from
`contracts.api_schemas`; local permissive duplicates are removed.

```text
POST /api/v1/actions/{approval.action_id}/confirm
{confirmation_id, action_digest: approval.action_digest, idempotency_key}

POST /api/v1/actions/{approval.action_id}/verify
{verification_code, idempotency_key}
```

All listed fields are required. ID fields are nonempty, bounded strings under
the shared contract. Unexpected fields, including user identity or an asserted
tier, return HTTP 422 before execution. The trusted demo session still determines
the owner. Responses remain the shared `ExecutionResult`:
`{action_id, status, message, audit_id}`. A wrong digest still returns the existing
tamper refusal; a well-formed request never grants permission by itself.

Both TypeScript request types match these schemas. `idempotency_key` is accepted
and required; the current execution guarantee remains tied to the server action
ID. This change does not add a cross-action idempotency registry or request-body
response caching. Retrying an existing action does not execute it twice.

## Display and cache behavior

`ApprovalCard` reads canonical transfer/cancellation arguments for the preview
and `approval` for controls. It shows confirmation only for
`PENDING_CONFIRMATION`, OTP entry only for `PENDING_MFA`, and no execution control
for terminal statuses. Yellow-to-Red escalation displays Red and retains that
tier on completion. Incoming metadata updates all visible cards for the ticket;
older pending metadata cannot reopen a completed ticket or remove an MFA step.
Conversation notification failure still offers a separate retry without marking
a completed bank operation failed.

Existing server-side continuation caches are upgraded when read. The backend
matches every cached follow-up against an owned action in the same conversation,
including its proposal ID, tool, canonical payload and digest. It reconstructs
metadata from current database status/tier and returns the new representation.
It does not call P1 again or create another ticket. This compatibility path is
only for stored backend responses; it does not accept metadata-in-arguments from
new proposals or HTTP request bodies. Cached agent wording remains a historical
reply, while the card and aggregate status reflect current ticket state.

## Deployment and checks

This is a coordinated HTTP response change: rebuild backend and frontend
together, then reload the browser so it uses the updated client. Keep existing
agent/provider environment settings:

```powershell
docker compose up -d --build backend frontend
```

No new database migration or reset is required by this change. Existing startup
migrations, including the prior continuation migration, still apply normally.

Manual checks:

1. Ask **Transfer 20 CNY to Bob**, inspect the chat response in browser Network,
   and confirm. `arguments` contains only the four transfer fields; `approval`
   contains the server ID, digest, tier, and status. Confirmation uses that ID
   in the URL and sends only the three shared request fields.
2. Request an amount that crosses the 1,000 CNY cumulative daily threshold,
   within the available balance. Confirm, then verify with the demo inbox code.
   The card shows Red/MFA, and completion removes execution controls.
3. With the seeded subscription active, ask **Cancel iQIYI VIP Monthly then
   transfer 45 CNY to Bob**. The next transfer has its own clean arguments and
   separate approval object; it still needs a separate approval.

Automated checks cover outgoing mock/real payloads and digests, unchanged P1
proposals/state, metadata injection refusals, shared request validation, legacy
cache upgrade, cached conversation isolation, and frontend card/API behavior.
Run frontend checks with `npm test` and `npm run build` inside `frontend/`.
