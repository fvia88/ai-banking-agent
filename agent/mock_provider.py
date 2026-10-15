"""Bounded English command parser for reproducible offline demos."""
import re
from .provider import Intent


class MockProvider:
    def extract(self, message: str) -> str:
        text = message.strip().lower()
        result = Intent(intent="unknown")
        if re.search(r"\b(then|after|and transfer|and cancel)\b", text):
            return result.model_dump_json()
        if text.startswith(("transfer", "send")):
            result.intent = "transfer"
            amount = re.search(r"(?<!\w)[+-]?\d+(?:\.\d+)?", text)
            # find the first number in the text, optionally signed and optionally decimal.
            result.amount = amount.group() if amount else None
            recipient = re.search(r"\bto\s+(.+?)[.!?]?$", text) #find word "to" n capture whtever comes aft it until end of string 
            result.recipient = recipient.group(1).strip() if recipient else None
        elif text.startswith("cancel "):
            result.intent = "cancel"
            result.subscription = re.sub(r"\s+subscription[.!?]?$", "", text[7:]).strip() 
            
            
        elif "balance" in text:
            result.intent = "balance"
        elif "spending" in text or "spend" in text:
            result.intent = "spending"
            period = re.search(r"\b\d{4}-\d{2}\b", text) # looks for a date shaped like yyyy-mm
            result.period = period.group() if period else None
        elif "subscription" in text or "recurring" in text:
            result.intent = "subscriptions"
        return result.model_dump_json()
