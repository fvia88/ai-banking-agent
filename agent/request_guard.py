"""Conservative request framing check, not language understanding or authorization."""
import re
from decimal import Decimal


def is_new_banking_request(message: str) -> bool:
    """Recognize clear request framing, not keywords inside a field answer.

    This only decides whether to release a draft. The provider still extracts
    the new intent and normal proposal checks still apply. Ambiguous wording
    remains a field answer; the user can always abandon it with 'never mind'.
    """
    if is_direct_request(message, "transfer") or is_direct_request(message, "cancel"):
        return True
    text = " ".join(message.strip().casefold().replace("’", "'").split())
    # Read requests must also be direct, not quoted or hypothetical instructions.
    if re.search(r'["“”`:]|\b(if|unless|not|never|example|hypothetical|imagine|pretend|merchant|note|says|said|instructions?)\b', text):
        return False
    prefix = r"(?:(?:please|(?:can|could|cld|would|will) (?:you|u)(?: please)?)\s+)?"
    reads = (r"(?:(?:what is|what's|whats|show|check|get|tell me) (?:me )?(?:my |the )?balance"
             r"|(?:analyze|analyse) (?:my |the )?spending"
             r"|(?:list|show|get) (?:me )?(?:my |the )?subscriptions)\b")
    return re.match(r"^" + prefix + reads, text) is not None


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
    prefix = r"(?:(?:please|(?:can|could|cld|would|will) (?:you|u)(?: please)?|i (?:want to|would like to|wanna)|i'd like to)\s+)?"
    verbs = r"(?:transfer|send|pay|give)" if intent == "transfer" else r"cancel"
    return re.match(r"^" + prefix + verbs + r"\b\s+\S", text) is not None


def stated_word_amounts(message: str) -> list[Decimal]:
    """Ground bounded English whole-CNY amounts, without trusting LLM arithmetic.

    Accept zero through 999 followed by yuan/CNY. Unsupported number phrases
    remain ungrounded; do not match a valid suffix inside a larger number.
    Numeric amounts continue to be checked by the service as before.
    """
    small = dict(zip(
        'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(),
        range(20),
    ))
    tens = dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(), range(20, 100, 10)))
    vocabulary = '|'.join([*small, *tens, 'hundred', 'thousand', 'million',
                           'billion', 'and', 'point', 'minus', 'negative'])
    pattern = r'\b((?:' + vocabulary + r')(?:(?:\s+|-)(?:' + vocabulary + r'))*)\s+(?:yuan|cny)\b'

    def under_hundred(words):
        if len(words) == 1:
            return small.get(words[0], tens.get(words[0]))
        if len(words) == 2 and words[0] in tens and words[1] in small and 1 <= small[words[1]] <= 9:
            return tens[words[0]] + small[words[1]]
        return None

    amounts = []
    for match in re.finditer(pattern, message.casefold()):
        # A signed prefix must not turn into a positive amount.
        if message[:match.start()].rstrip().endswith(('-', '+')):
            continue
        words = match.group(1).replace('-', ' ').split()
        value = under_hundred(words)
        if len(words) >= 2 and words[0] in small and 1 <= small[words[0]] <= 9 and words[1] == 'hundred':
            tail = words[2:]
            if tail[:1] == ['and']:
                tail = tail[1:]
                if not tail:
                    continue
            remainder = under_hundred(tail) if tail else 0
            if remainder is not None:
                value = small[words[0]] * 100 + remainder
        if value is not None:
            amounts.append(Decimal(value))
    return amounts
