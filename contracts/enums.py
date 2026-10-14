from enum import Enum


class Tier(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class ActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    PENDING_MFA = "PENDING_MFA"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ToolName(str, Enum):
    GET_BALANCE = "get_balance"
    ANALYZE_SPENDING = "analyze_spending"
    LIST_SUBSCRIPTIONS = "list_subscriptions"
    REQUEST_TRANSFER = "request_transfer"
    REQUEST_SUBSCRIPTION_CANCEL = "request_subscription_cancel"


class Direction(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class Cadence(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ANNUAL = "annual"
    UNKNOWN = "unknown"
