"""Read-only synthetic CLI helpers, not production analytics or execution."""
# mock_tools.py reads fixtures, it provides fake account/recipient context and banking results
import json
from pathlib import Path
from decimal import Decimal
from contracts.tool_schemas import TOOL_ARGUMENT_MODELS, validate_tool_arguments

ROOT = Path(__file__).resolve().parents[1] / "fixtures"


def load(name):
    return json.loads((ROOT / f"{name}.json").read_text(encoding="utf-8"))


def demo_catalog():
    context = {"account_ids": ["account_001"], "account_locked": False,
               "recipients": load("recipients"), "subscriptions": load("subscriptions")}
    return [{"name": tool.value, "parameters": model.model_json_schema(),
             "context": dict(context)} for tool, model in TOOL_ARGUMENT_MODELS.items()]


def read_result(chat, proposal):
    tool = proposal.tool.value
    args = validate_tool_arguments(proposal.tool, proposal.arguments).model_dump(mode="json")
    if tool == "get_balance":
        data = next(a for a in load("accounts") if a["account_id"] == args["account_id"])
    elif tool == "analyze_spending":
        rows = [t for t in load("transactions") if t["account_id"] == args["account_id"]
                and t["timestamp"].startswith(args["period"]) and t["direction"] == "debit"]
        categories = {}
        for row in rows:
            categories[row["category"]] = categories.get(row["category"], Decimal(0)) + Decimal(row["amount"])
        data = dict(period=args["period"], total_spending=f"{sum(categories.values(), Decimal(0)):.2f}",
                    category_totals={k: f"{v:.2f}" for k, v in categories.items()})
    elif tool == "list_subscriptions":
        # No detector is impersonated here; P5 supplies real candidate reports later.
        data = {"candidates": []}
    else:
        raise ValueError("Mock tools never execute state-changing actions")
    return dict(conversation_id=chat.conversation_id, proposal_id=proposal.proposal_id,
                tool=tool, arguments=args, status="success", data=data)
