# Shared contracts v1.0.0

These are the **single source of truth** for all five teammates. Do not edit without team agreement and a version bump. Import from `contracts.models`, `contracts.enums`, `contracts.tool_schemas`, and `contracts.api_schemas`.

## Public module signatures

- P1 `agent.service.process_message(chat: ChatInput, tool_catalog: list[dict], tool_results: list[dict] | None = None) -> AgentResult`
- P3 `finance.analytics.analyze_spending(transactions: list[Transaction], period: str) -> SpendingReport`
- P4 `security.policy.evaluate_action(proposal: ActionProposal, context: BankingContext) -> PolicyDecision`
- P5 `subscriptions.detector.detect_subscriptions(transactions: list[Transaction]) -> SubscriptionReport`
- P5 `subscriptions.eligibility.assess_cancellation(subscription: SubscriptionCandidate) -> CancellationAssessment`

P2 owns integration and persistence. Agent proposals are **not** permission to execute. Backend must authenticate, validate arguments with `validate_tool_arguments`, check account/recipient ownership, invoke policy, create server-issued action ID and exact-payload-bound approval, enforce MFA when required, and execute atomically/idempotently with audit logging. `PolicyDecision.allowed_to_proceed=True` is NOT final execution authorization.

## Data rules

- JSON monetary values are **strings** with two decimal places; Python models parse them into `Decimal`. JSON serialization of `Decimal` emits strings. Never use floating-point math for money.
- IDs are opaque. Timestamps are ISO 8601 and timezone-aware.
- All data in `fixtures/` is synthetic. Currency is CNY for v1.
- The API request `ChatInput` has **no `user_id`**. User context is server-derived.
- `ActionProposal.arguments` is deliberately generic, but MUST be validated against `tool_schemas.py` before use.
- Backend approval states: PROPOSED → PENDING_CONFIRMATION → (PENDING_MFA for red) → COMPLETED, or REJECTED/FAILED/CANCELLED. Read-only actions may complete without confirmation.
- A detected recurring payment is not proof of an active subscription. No real cancellation API is implemented.

## Contract-first test

From repository root: `python -m pip install -r requirements-contracts.txt` then `python -m pytest tests/test_contracts.py -q`.

## Endpoints (P2)

- `GET /api/v1/health`
- `GET /api/v1/accounts`
- `GET /api/v1/transactions?period=YYYY-MM`
- `POST /api/v1/chat` (ChatInput → ChatOutput)
- `POST /api/v1/actions/{action_id}/confirm` (ConfirmActionRequest → ExecutionResult)
- `POST /api/v1/actions/{action_id}/verify` (VerifyActionRequest → ExecutionResult)
- `GET /api/v1/subscriptions` (SubscriptionReport)
- `GET /api/v1/audit` (AuditResponse)

## Compatibility note

This executable v1.0.0 package is more precise than the earlier Word draft. If a field/signature differs, **this package takes precedence**. In particular `assess_cancellation` returns `CancellationAssessment`, and money is a `Decimal` in Python (string in JSON).
