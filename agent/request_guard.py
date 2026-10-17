"""Conservative request framing check, not language understanding or authorization."""
import re


def is_direct_request(message: str, intent: str) -> bool:
    text = " ".join(message.strip().casefold().replace("’", "'").split())
    # When framing is ambiguous, ask for a fresh explicit request. These checks
    # intentionally reject some valid wording rather than treating data as orders.
    if re.search(r"\b(not|never|don't|dont|do not|cannot|can't|without|if|unless|example|hypothetical|imagine|pretend)\b", text):
        return False
    if re.search(r'["“”`]|(?<!\w)\x27[^\x27]+\x27(?!\w)|:', text):
        return False
    if re.search(r"\b(note|merchant|quoted|quote|says|said|instructions?)\b", text):
        return False
    # Gemini still chooses intent and extracts all fields. This only accepts
    # direct imperative framing with common polite request prefixes.
    prefix = r"(?:(?:please|(?:can|could|would|will) you(?: please)?|i (?:want to|would like to|wanna)|i'd like to)\s+)?"
    verbs = r"(?:transfer|send|pay|give)" if intent == "transfer" else r"cancel"
    return re.match(r"^" + prefix + verbs + r"\b\s+\S", text) is not None
