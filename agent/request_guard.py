"""Conservative request framing check, not language understanding or authorization."""
import re
from decimal import Decimal

_REQUEST_PREFIX = r"(?:(?:please|pls|plz|(?:can|could|cld|would|will) (?:you|u)(?: please| pls| plz)?|i (?:want to|would like to|wanna)|i'd like to)\s+)?"


def _one_typo(word: str, target: str) -> bool:
    """At most one insertion/deletion/substitution or adjacent transposition."""
    if word == target:
        return True
    if abs(len(word) - len(target)) > 1:
        return False
    if len(word) == len(target):
        different = [i for i, (a, b) in enumerate(zip(word, target)) if a != b]
        return (len(different) == 1 or
                (len(different) == 2 and different[1] == different[0] + 1
                 and word[different[0]] == target[different[1]]
                 and word[different[1]] == target[different[0]]))
    short, long = (word, target) if len(word) < len(target) else (target, word)
    return any(long[:i] + long[i + 1:] == short for i in range(len(long)))


def _request_text(message: str) -> str:
    """Normalize command positions only, for guards; never rewrite field data."""
    text = " ".join(message.strip().casefold().replace("’", "'").split())
    match = re.match(r"^" + _REQUEST_PREFIX + r"(?P<verb>[a-z]+)(?=\s|$)", text)
    if not match:
        return text
    word = match['verb']
    aliases = {'trf': 'transfer', 'xfer': 'transfer', 'snd': 'send', 'sned': 'send'}
    canonical = aliases.get(word)
    if canonical is None and len(word) >= 4:
        matches = {('analyze' if v == 'analyse' else v) for v in
                   ('transfer', 'cancel', 'analyze', 'analyse') if _one_typo(word, v)}
        if len(matches) == 1:
            canonical = matches.pop()
    if canonical:
        text = text[:match.start('verb')] + canonical + text[match.end('verb'):]
    # Only the noun position of an explicit read request is eligible. Names,
    # amounts, dates and free text elsewhere are never fuzzy-corrected.
    read = re.match(r"^" + _REQUEST_PREFIX +
                    r"(?:what is|what's|whats|show|check|get|tell me|analyze|analyse) "
                    r"(?:me )?(?:my |the )?(?P<noun>[a-z]+)\b", text)
    if read and len(read['noun']) >= 4:
        matches = {v for v in ('balance', 'spending', 'subscriptions') if _one_typo(read['noun'], v)}
        if len(matches) == 1:
            text = text[:read.start('noun')] + matches.pop() + text[read.end('noun'):]
    return text


def is_abandonment(message: str) -> bool:
    """A standalone draft-abandonment command, never an action revocation."""
    text = " ".join(message.strip().casefold().split()).rstrip('.!?').strip()
    if text in {'nvm', 'nvr mind', 'nvrmind'}:
        return True
    words = text.split()
    return ((len(words) == 2 and words[0] == 'never' and _one_typo(words[1], 'mind'))
            or (len(words) == 1 and _one_typo(text, 'nevermind')))


def is_generic_cancellation_request(message: str) -> bool:
    """A whole direct cancellation request with no supplied merchant name.

    This only starts clarification. It never selects a subscription, grants
    permission, or proposes cancelling all records.
    """
    text = _request_text(message).rstrip('.!?').strip()
    match = re.fullmatch(_REQUEST_PREFIX + r"cancel (?:(?:my|the|a) )?(?P<noun>[a-z]+)", text)
    return bool(match and is_direct_request(message, 'cancel')
                and any(_one_typo(match['noun'], noun) for noun in ('subscription', 'subscriptions')))


def is_new_banking_request(message: str) -> bool:
    """Recognize clear request framing, not keywords inside a field answer.

    This only decides whether to release a draft. The provider still extracts
    the new intent and normal proposal checks still apply. Ambiguous wording
    remains a field answer; the user can always abandon it with 'never mind'.
    """
    if is_direct_request(message, "transfer") or is_direct_request(message, "cancel"):
        return True
    text = _request_text(message)
    # Read requests must also be direct, not quoted or hypothetical instructions.
    if re.search(r'["“”`:]|\b(if|unless|not|never|example|hypothetical|imagine|pretend|merchant|note|says|said|instructions?)\b', text):
        return False
    prefix = _REQUEST_PREFIX
    reads = (r"(?:(?:what is|what's|whats|show|check|get|tell me) (?:me )?(?:my |the )?balance"
             r"|(?:analyze|analyse) (?:my |the )?spending"
             r"|(?:list|show|get) (?:me )?(?:my |the )?subscriptions)\b")
    return re.match(r"^" + prefix + reads, text) is not None


def is_direct_request(message: str, intent: str) -> bool:
    text = _request_text(message)
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
    prefix = _REQUEST_PREFIX
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
