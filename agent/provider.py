"""Private provider output, separate from the canonical public DTOs."""
import os
from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: Literal["balance", "spending", "subscriptions", "transfer", "cancel", "unknown"]
    amount: str | None = None
    recipient: str | None = None
    period: str | None = None
    subscription: str | None = None


class ProviderError(Exception):
    """Safe provider failure; never expose SDK error payloads."""

    def __init__(self, message, *, category="provider_error", http_code=None):
        super().__init__(message)
        self.category = category
        self.http_code = http_code


class Provider(Protocol):
    def extract(self, message: str) -> str: ...


def get_provider() -> Provider:
    name = os.getenv("AGENT_PROVIDER", "mock").lower()
    if name == "mock":
        from .mock_provider import MockProvider
        return MockProvider()
    if name == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider()
    raise ProviderError("Unsupported provider")
