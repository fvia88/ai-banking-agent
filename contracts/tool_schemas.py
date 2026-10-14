"""Whitelisted tool arguments and shared validation; no arbitrary LLM tool execution."""
from typing import Literal
from pydantic import Field
from .models import ID, PositiveMoney, StrictModel
from .enums import ToolName


class GetBalanceArgs(StrictModel):
    account_id: ID


class AnalyzeSpendingArgs(StrictModel):
    account_id: ID
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


class ListSubscriptionsArgs(StrictModel):
    account_id: ID


class TransferArgs(StrictModel):
    source_account_id: ID
    recipient_id: ID
    amount: PositiveMoney
    currency: Literal["CNY"] = "CNY"


class CancelSubscriptionArgs(StrictModel):
    subscription_id: ID


TOOL_ARGUMENT_MODELS = {
    ToolName.GET_BALANCE: GetBalanceArgs,
    ToolName.ANALYZE_SPENDING: AnalyzeSpendingArgs,
    ToolName.LIST_SUBSCRIPTIONS: ListSubscriptionsArgs,
    ToolName.REQUEST_TRANSFER: TransferArgs,
    ToolName.REQUEST_SUBSCRIPTION_CANCEL: CancelSubscriptionArgs,
}


def validate_tool_arguments(tool: ToolName, arguments: dict):
    """Raises pydantic.ValidationError for malformed or extra fields."""
    return TOOL_ARGUMENT_MODELS[ToolName(tool)].model_validate(arguments)
