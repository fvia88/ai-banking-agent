"""Tests for P4 Phase A & B3 — SecurityAdapterService bridge and application-path enforcement."""
from decimal import Decimal
import json
from pathlib import Path
import pytest

from app.db.models import AccountModel, ActionApprovalModel
from app.services.actions import create_action_record
from app.services.adapters import SecurityAdapterService, agent_service, policy_service
from contracts.enums import ActionStatus, Tier, ToolName
from contracts.models import Account, ActionProposal, AgentResult, BankingContext, PolicyDecision
import security.policy
from security.rules import SecurityReasonCode

FIXTURES_ROOT = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def fixture_context() -> BankingContext:
    """Builds a BankingContext from canonical shared fixtures/accounts.json."""
    accounts = json.loads((FIXTURES_ROOT / "accounts.json").read_text(encoding="utf-8"))
    primary = Account.model_validate(accounts[0])
    return BankingContext(
        user_id=primary.user_id,
        account_id=primary.account_id,
        daily_transfer_total=Decimal("0.00"),
        account_balance=primary.balance,
        account_locked=primary.locked,
    )


def test_security_adapter_environment_and_default_selection(monkeypatch):
    """Verifies default real mode, valid case-insensitive USE_MOCK_SECURITY values, and overrides."""
    assert isinstance(policy_service, SecurityAdapterService)

    monkeypatch.delenv("USE_MOCK_SECURITY", raising=False)
    default_adapter = SecurityAdapterService()
    assert default_adapter.use_mock is False

    for false_val in ("false", "FALSE", "False", "fAlSe"):
        monkeypatch.setenv("USE_MOCK_SECURITY", false_val)
        assert SecurityAdapterService().use_mock is False

    for true_val in ("true", "TRUE", "True", "tRuE"):
        monkeypatch.setenv("USE_MOCK_SECURITY", true_val)
        assert SecurityAdapterService().use_mock is True

    # Explicit boolean constructor argument must override valid environment variable
    monkeypatch.setenv("USE_MOCK_SECURITY", "true")
    assert SecurityAdapterService(use_mock=False).use_mock is False

    monkeypatch.setenv("USE_MOCK_SECURITY", "false")
    assert SecurityAdapterService(use_mock=True).use_mock is True


@pytest.mark.parametrize(
    "invalid_env_value",
    ["treu", "flase", "yes", "no", "1", "0", "", " ", " true", "true ", " false "],
)
def test_security_adapter_rejects_invalid_env_values_and_allows_explicit_override(
    monkeypatch, invalid_env_value
):
    """Verifies invalid USE_MOCK_SECURITY values raise ValueError unless overridden by explicit bool."""
    monkeypatch.setenv("USE_MOCK_SECURITY", invalid_env_value)
    with pytest.raises(ValueError, match="Invalid USE_MOCK_SECURITY"):
        SecurityAdapterService()

    # Explicit valid boolean must override even when USE_MOCK_SECURITY is invalid
    assert SecurityAdapterService(use_mock=True).use_mock is True
    assert SecurityAdapterService(use_mock=False).use_mock is False


@pytest.mark.parametrize(
    "non_bool_value",
    ["true", "false", "", 1, 0, 2, ["true"], {"use_mock": True}],
)
def test_security_adapter_rejects_non_boolean_constructor_arguments(non_bool_value):
    """Verifies non-boolean explicit use_mock values raise ValueError."""
    with pytest.raises(ValueError, match="Invalid use_mock"):
        SecurityAdapterService(use_mock=non_bool_value)  # type: ignore[arg-type]


def test_explicit_use_mock_true_and_false_behavior(fixture_context):
    """Verifies explicit use_mock=True vs use_mock=False on a canonical transfer proposal."""
    proposal = ActionProposal(
        proposal_id="prop_bridge_t02",
        tool=ToolName.REQUEST_TRANSFER,
        arguments={
            "source_account_id": fixture_context.account_id,
            "recipient_id": "recipient_alice",
            "amount": "500.00",
            "currency": "CNY",
        },
    )

    mock_adapter = SecurityAdapterService(use_mock=True)
    real_adapter = SecurityAdapterService(use_mock=False)

    mock_decision = mock_adapter.evaluate(proposal, fixture_context)
    real_decision = real_adapter.evaluate(proposal, fixture_context)

    assert mock_decision.tier == Tier.YELLOW
    assert mock_decision.allowed_to_proceed is True
    assert mock_decision.reason_code == "TRANSFER_WITHIN_DAILY_LIMIT_CONFIRMATION_REQUIRED"

    assert real_decision.tier == Tier.YELLOW
    assert real_decision.allowed_to_proceed is True
    assert real_decision.requires_confirmation is True
    assert real_decision.requires_mfa is False
    assert real_decision.reason_code == SecurityReasonCode.TRANSFER_WITHIN_DAILY_LIMIT


def test_real_mode_invokes_security_policy_evaluate_action_spy(fixture_context, monkeypatch):
    """Proves real mode invokes security.policy.evaluate_action with exact proposal and context objects."""
    calls: list[tuple[ActionProposal, BankingContext]] = []
    original_evaluate = security.policy.evaluate_action

    def spy_evaluate_action(proposal: ActionProposal, context: BankingContext) -> PolicyDecision:
        calls.append((proposal, context))
        return original_evaluate(proposal, context)

    monkeypatch.setattr(security.policy, "evaluate_action", spy_evaluate_action)

    proposal = ActionProposal(
        proposal_id="prop_spy_01",
        tool=ToolName.GET_BALANCE,
        arguments={"account_id": fixture_context.account_id},
    )

    # Mock mode must NOT invoke security.policy.evaluate_action
    mock_decision = SecurityAdapterService(use_mock=True).evaluate(proposal, fixture_context)
    assert mock_decision.allowed_to_proceed is True
    assert len(calls) == 0

    # Real mode instance MUST invoke security.policy.evaluate_action with exact object identity
    real_decision = SecurityAdapterService(use_mock=False).evaluate(proposal, fixture_context)
    assert len(calls) == 1
    assert calls[0][0] is proposal
    assert calls[0][1] is fixture_context
    assert real_decision.tier == Tier.GREEN
    assert real_decision.allowed_to_proceed is True
    assert real_decision.reason_code == SecurityReasonCode.READ_ONLY_ACCESS

    # Module singleton policy_service in real mode (via monkeypatch, no state leakage)
    monkeypatch.setattr(policy_service, "use_mock", False)
    singleton_decision = policy_service.evaluate(proposal, fixture_context)
    assert len(calls) == 2
    assert calls[1][0] is proposal
    assert calls[1][1] is fixture_context
    assert singleton_decision == real_decision


def test_unknown_tool_rejected_in_real_mode(fixture_context):
    """
    Verifies real mode rejects unknown tools with canonical UNKNOWN_TOOL reason code,
    contrasting with MockSecurityAdapter's fallback behavior.
    """
    unknown_proposal = ActionProposal.model_construct(
        proposal_id="prop_unknown_01",
        tool="execute_raw_sql",
        arguments={"query": "DROP TABLE accounts"},
        rationale="Untrusted tool call",
    )

    # MockSecurityAdapter falls through to Rule 4 (READ_ONLY_AUTOMATIC / Tier.GREEN)
    mock_decision = SecurityAdapterService(use_mock=True).evaluate(unknown_proposal, fixture_context)
    assert mock_decision.allowed_to_proceed is True
    assert mock_decision.tier == Tier.GREEN
    assert mock_decision.reason_code == "READ_ONLY_AUTOMATIC"

    # Real policy engine fails closed (Tier.RED / UNKNOWN_TOOL)
    real_decision = SecurityAdapterService(use_mock=False).evaluate(unknown_proposal, fixture_context)
    assert real_decision.allowed_to_proceed is False
    assert real_decision.tier == Tier.RED
    assert real_decision.requires_confirmation is False
    assert real_decision.requires_mfa is False
    assert real_decision.reason_code == SecurityReasonCode.UNKNOWN_TOOL


def test_meaningful_distinction_between_mock_and_real_policy_decisions(fixture_context):
    """
    Demonstrates security enforcement differences between mock and real policy modes:
    1. Mismatched source_account_id (allowed by mock, rejected by real as SOURCE_ACCOUNT_MISMATCH).
    2. Extra unexpected tool arguments (allowed by mock, rejected by real as INVALID_TOOL_ARGUMENTS).
    """
    mock_adapter = SecurityAdapterService(use_mock=True)
    real_adapter = SecurityAdapterService(use_mock=False)

    # Case 1: Cross-account spoofing attempt (source_account_id != context.account_id)
    mismatched_account_proposal = ActionProposal(
        proposal_id="prop_mismatch_01",
        tool=ToolName.REQUEST_TRANSFER,
        arguments={
            "source_account_id": "account_002",
            "recipient_id": "recipient_alice",
            "amount": "200.00",
            "currency": "CNY",
        },
    )
    mock_mismatch = mock_adapter.evaluate(mismatched_account_proposal, fixture_context)
    real_mismatch = real_adapter.evaluate(mismatched_account_proposal, fixture_context)

    assert mock_mismatch.allowed_to_proceed is True
    assert mock_mismatch.tier == Tier.YELLOW

    assert real_mismatch.allowed_to_proceed is False
    assert real_mismatch.tier == Tier.RED
    assert real_mismatch.requires_confirmation is False
    assert real_mismatch.requires_mfa is False
    assert real_mismatch.reason_code == SecurityReasonCode.SOURCE_ACCOUNT_MISMATCH

    # Case 2: Extra injected argument violating StrictModel (extra="forbid")
    injected_arg_proposal = ActionProposal(
        proposal_id="prop_injected_01",
        tool=ToolName.REQUEST_TRANSFER,
        arguments={
            "source_account_id": fixture_context.account_id,
            "recipient_id": "recipient_alice",
            "amount": "200.00",
            "currency": "CNY",
            "bypass_mfa": True,
        },
    )
    mock_injected = mock_adapter.evaluate(injected_arg_proposal, fixture_context)
    real_injected = real_adapter.evaluate(injected_arg_proposal, fixture_context)

    assert mock_injected.allowed_to_proceed is True
    assert real_injected.allowed_to_proceed is False
    assert real_injected.tier == Tier.RED
    assert real_injected.reason_code == SecurityReasonCode.INVALID_TOOL_ARGUMENTS


def test_create_action_record_with_real_policy_preserves_reason_codes(fixture_context, monkeypatch):
    """
    Verifies create_action_record with real policy_service (use_mock=False):
    - Accepts valid canonical transfer (YELLOW <= 1000, RED > 1000) and subscription cancellation.
    - Rejects mismatched source_account_id with SOURCE_ACCOUNT_MISMATCH (whereas mock overwrites it).
    - Rejects explicit None source_account_id and extra injected fields with INVALID_TOOL_ARGUMENTS.
    - Rejects unknown tools with UNKNOWN_TOOL.
    """
    monkeypatch.setattr(policy_service, "use_mock", False)

    # 1. Valid canonical YELLOW transfer
    valid_tx = ActionProposal(
        proposal_id="prop_act_yellow",
        tool=ToolName.REQUEST_TRANSFER,
        arguments={
            "source_account_id": fixture_context.account_id,
            "recipient_id": "recipient_alice",
            "amount": "1000.00",
            "currency": "CNY",
        },
    )
    record, digest, tier = create_action_record(
        fixture_context.user_id, valid_tx, fixture_context.account_id, fixture_context
    )
    assert tier == Tier.YELLOW.value
    assert record.tier == Tier.YELLOW.value
    assert record.action_digest == digest

    # 2. Valid canonical RED transfer (1000.01 > 1000.00)
    red_tx = ActionProposal(
        proposal_id="prop_act_red",
        tool=ToolName.REQUEST_TRANSFER,
        arguments={
            "source_account_id": fixture_context.account_id,
            "recipient_id": "recipient_alice",
            "amount": "1000.01",
            "currency": "CNY",
        },
    )
    _, _, red_tier = create_action_record(
        fixture_context.user_id, red_tx, fixture_context.account_id, fixture_context
    )
    assert red_tier == Tier.RED.value

    # 3. Mismatched source_account_id rejected with SOURCE_ACCOUNT_MISMATCH before actions.py can overwrite it
    mismatch_tx = ActionProposal(
        proposal_id="prop_act_mismatch",
        tool=ToolName.REQUEST_TRANSFER,
        arguments={
            "source_account_id": "account_002",
            "recipient_id": "recipient_alice",
            "amount": "100.00",
            "currency": "CNY",
        },
    )
    with pytest.raises(ValueError, match=SecurityReasonCode.SOURCE_ACCOUNT_MISMATCH):
        create_action_record(
            fixture_context.user_id, mismatch_tx, fixture_context.account_id, fixture_context
        )

    # 4. Explicit source_account_id=None rejected with INVALID_TOOL_ARGUMENTS
    null_src_tx = ActionProposal(
        proposal_id="prop_act_null_src",
        tool=ToolName.REQUEST_TRANSFER,
        arguments={
            "source_account_id": None,
            "recipient_id": "recipient_alice",
            "amount": "100.00",
            "currency": "CNY",
        },
    )
    with pytest.raises(ValueError, match=SecurityReasonCode.INVALID_TOOL_ARGUMENTS):
        create_action_record(
            fixture_context.user_id, null_src_tx, fixture_context.account_id, fixture_context
        )

    # 5. Injected metadata / extra field rejected with INVALID_TOOL_ARGUMENTS
    injected_tx = ActionProposal(
        proposal_id="prop_act_injected",
        tool=ToolName.REQUEST_TRANSFER,
        arguments={
            "source_account_id": fixture_context.account_id,
            "recipient_id": "recipient_alice",
            "amount": "100.00",
            "currency": "CNY",
            "action_id": "act_forged",
        },
    )
    with pytest.raises(ValueError, match=SecurityReasonCode.INVALID_TOOL_ARGUMENTS):
        create_action_record(
            fixture_context.user_id, injected_tx, fixture_context.account_id, fixture_context
        )

    # 6. Unknown tool rejected with UNKNOWN_TOOL
    unknown_prop = ActionProposal.model_construct(
        proposal_id="prop_act_unk",
        tool="delete_all_users",
        arguments={},
    )
    with pytest.raises(ValueError, match=SecurityReasonCode.UNKNOWN_TOOL):
        create_action_record(
            fixture_context.user_id, unknown_prop, fixture_context.account_id, fixture_context
        )


def test_http_chat_differential_proof_mock_allows_vs_real_policy_rejects(
    client, db_session, monkeypatch
):
    """
    Differential HTTP proof through POST /api/v1/chat on unmodified chat.py/actions.py:
    - A proposal with mismatched source_account_id ('acc_victim_999') or an injected extra
      argument ('bypass_mfa': True) is ACCEPTED (PENDING_CONFIRMATION) when policy_service.use_mock=True.
    - The exact same proposal is REJECTED (status=REJECTED, zero DB rows) when
      policy_service.use_mock=False, with a spy confirming security.policy.evaluate_action ran.
    """
    calls: list[tuple[ActionProposal, BankingContext]] = []
    original_evaluate = security.policy.evaluate_action

    def spy_evaluate(proposal: ActionProposal, context: BankingContext) -> PolicyDecision:
        calls.append((proposal, context))
        return original_evaluate(proposal, context)

    monkeypatch.setattr(security.policy, "evaluate_action", spy_evaluate)

    spoofed_proposal = ActionProposal(
        proposal_id="prop_http_spoof",
        tool=ToolName.REQUEST_TRANSFER,
        arguments={
            "source_account_id": "acc_victim_999",
            "recipient_id": "usr_bob_01",
            "amount": "100.00",
            "currency": "CNY",
        },
        rationale="Cross-account transfer attempt",
    )
    monkeypatch.setattr(
        agent_service,
        "process",
        lambda *args, **kwargs: AgentResult(
            reply="Drafted transfer.",
            proposals=[spoofed_proposal.model_copy(deep=True)],
            needs_clarification=False,
        ),
    )

    # 1. With mock policy (use_mock=True), /api/v1/chat allows the spoofed source_account_id
    monkeypatch.setattr(policy_service, "use_mock", True)
    mock_resp = client.post(
        "/api/v1/chat",
        json={"conversation_id": "c_diff_mock", "message": "Transfer 100 to Bob"},
        headers={"X-Demo-User-Id": "usr_demo_01"},
    )
    assert mock_resp.status_code == 200
    assert mock_resp.json()["status"] == ActionStatus.PENDING_CONFIRMATION.value
    assert len(calls) == 0

    # 2. With real P4 policy (use_mock=False), /api/v1/chat rejects the exact same proposal
    monkeypatch.setattr(policy_service, "use_mock", False)
    real_resp = client.post(
        "/api/v1/chat",
        json={"conversation_id": "c_diff_real", "message": "Transfer 100 to Bob"},
        headers={"X-Demo-User-Id": "usr_demo_01"},
    )
    assert real_resp.status_code == 200
    assert real_resp.json()["status"] == ActionStatus.REJECTED.value
    assert real_resp.json()["actions"] == []
    assert len(calls) == 1
    assert calls[0][0].proposal_id == "prop_http_spoof"
    assert calls[0][1].account_id == "acc_cny_001"
    assert (
        db_session.query(ActionApprovalModel)
        .filter_by(proposal_id="prop_http_spoof")
        .count()
        == 1  # Only the 1 row from mock mode exists; real mode created 0 rows
    )


def test_http_chat_real_p1_agent_with_real_p4_policy_end_to_end(
    client, db_session, monkeypatch
):
    """
    End-to-end HTTP verification with BOTH P1 real agent (AGENT_PROVIDER=mock)
    and P4 real security policy (policy_service.use_mock=False).
    """
    calls: list[PolicyDecision] = []
    original_evaluate = security.policy.evaluate_action

    def spy_evaluate(proposal: ActionProposal, context: BankingContext) -> PolicyDecision:
        decision = original_evaluate(proposal, context)
        calls.append(decision)
        return decision

    monkeypatch.setattr(security.policy, "evaluate_action", spy_evaluate)
    monkeypatch.setattr(agent_service, "use_mock", False)
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    monkeypatch.setattr(policy_service, "use_mock", False)

    chat_res = client.post(
        "/api/v1/chat",
        json={"conversation_id": "c_p1_p4_e2e", "message": "Transfer 500 to Bob"},
        headers={"X-Demo-User-Id": "usr_demo_01"},
    )
    assert chat_res.status_code == 200
    chat_body = chat_res.json()
    assert chat_body["status"] == ActionStatus.PENDING_CONFIRMATION.value
    assert len(calls) == 1
    assert calls[0].tier == Tier.YELLOW
    assert calls[0].reason_code == SecurityReasonCode.TRANSFER_WITHIN_DAILY_LIMIT

    action = chat_body["actions"][0]
    action_id = action["arguments"]["action_id"]
    digest = action["arguments"]["action_digest"]

    confirm_res = client.post(
        f"/api/v1/actions/{action_id}/confirm",
        json={
            "confirmation_id": "conf_p1_p4_01",
            "action_digest": digest,
            "idempotency_key": "idemp_p1_p4_01",
        },
        headers={"X-Demo-User-Id": "usr_demo_01"},
    )
    assert confirm_res.status_code == 200
    assert confirm_res.json()["status"] == ActionStatus.COMPLETED.value

    acc = db_session.query(AccountModel).filter_by(account_id="acc_cny_001").first()
    db_session.refresh(acc)
    assert acc.balance == Decimal("14750.00")
