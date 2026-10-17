"""Security package for AI Banking Agent (Person 4 - Finance Risk & Security).

Exports evaluate_action, the primary entry point for policy evaluation.
"""
from .policy import evaluate_action
from .rules import DEFAULT_CONFIG, PolicyConfig, SecurityReasonCode

__all__ = [
    "evaluate_action",
    "PolicyConfig",
    "SecurityReasonCode",
    "DEFAULT_CONFIG",
]
