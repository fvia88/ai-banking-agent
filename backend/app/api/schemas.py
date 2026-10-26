"""P2-owned HTTP presentation models; P1's canonical DTOs remain unchanged."""
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from contracts.enums import ActionStatus, Tier, ToolName
from contracts.models import ID, StrictModel, ActionProposal, ChatOutput
from contracts.tool_schemas import validate_tool_arguments


class ApprovalMetadata(StrictModel):
    action_id: ID
    action_digest: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    tier: Literal[Tier.YELLOW, Tier.RED]
    status: ActionStatus


class PresentedAction(ActionProposal):
    tool: Literal[ToolName.REQUEST_TRANSFER, ToolName.REQUEST_SUBSCRIPTION_CANCEL]
    approval: ApprovalMetadata

    @model_validator(mode="after")
    def canonical_arguments_only(self):
        validate_tool_arguments(self.tool, self.arguments)
        return self


class AppChatOutput(ChatOutput):
    actions: list[PresentedAction] = Field(default_factory=list)
