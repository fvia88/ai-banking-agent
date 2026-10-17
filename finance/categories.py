"""Deterministic spending categorization.

Rules (first match wins, see docs/finance/RULES.md):
 1. A provided `category` that carries information is kept AS WRITTEN (cleaned of
    control characters, whitespace collapsed). This matches fixtures T12, which
    expects the team's own labels ("Food", "Subscriptions", "Other").
    Labels that differ only by letter case are merged into one bucket.
 2. A missing/unknown label ("", "unknown", "uncategorized", "n/a", ...) falls back
    to ordered merchant keyword rules.
 3. Otherwise -> "Uncategorized".
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

UNCATEGORIZED = "Uncategorized"
MAX_LABEL_LEN = 64

# Labels that carry no information -> merchant rules. ("Other" IS information: T12
# expects it to stay "Other".)
UNKNOWN_LABELS = frozenset({"", "unknown", "uncategorized", "uncategorised", "none", "null",
                            "n/a", "na", "-", "未知", "未分类"})

# Ordered merchant keyword rules (first match wins). Output names follow the
# fixture's Title Case vocabulary. ASCII keywords match on word boundaries.
MERCHANT_RULES: tuple[tuple[str, str], ...] = (
    # subscriptions / streaming
    ("netflix", "Subscriptions"), ("spotify", "Subscriptions"), ("iqiyi", "Subscriptions"),
    ("爱奇艺", "Subscriptions"), ("腾讯视频", "Subscriptions"), ("tencent video", "Subscriptions"),
    ("youku", "Subscriptions"), ("优酷", "Subscriptions"), ("bilibili", "Subscriptions"),
    ("qq music", "Subscriptions"), ("qq音乐", "Subscriptions"), ("icloud", "Subscriptions"),
    ("网易云音乐", "Subscriptions"), ("streambox", "Subscriptions"), ("cloudmusic", "Subscriptions"),
    # travel (before generic transport)
    ("12306", "Travel"), ("ctrip", "Travel"), ("携程", "Travel"), ("trip.com", "Travel"),
    ("airline", "Travel"), ("航空", "Travel"), ("hotel", "Travel"), ("酒店", "Travel"),
    # transport
    ("didi", "Transport"), ("滴滴", "Transport"), ("metro", "Transport"), ("地铁", "Transport"),
    ("taxi", "Transport"), ("出租车", "Transport"), ("深圳通", "Transport"),
    ("sinopec", "Transport"), ("中石化", "Transport"), ("中石油", "Transport"),
    # food (groceries + dining)
    ("hema", "Food"), ("盒马", "Food"), ("walmart", "Food"), ("沃尔玛", "Food"),
    ("grocery", "Food"), ("supermarket", "Food"), ("超市", "Food"), ("7-eleven", "Food"),
    ("便利店", "Food"), ("starbucks", "Food"), ("星巴克", "Food"), ("luckin", "Food"),
    ("瑞幸", "Food"), ("meituan", "Food"), ("美团", "Food"), ("ele.me", "Food"),
    ("饿了么", "Food"), ("mcdonald", "Food"), ("麦当劳", "Food"), ("kfc", "Food"),
    ("肯德基", "Food"), ("restaurant", "Food"), ("餐厅", "Food"), ("cafe", "Food"),
    # shopping
    ("taobao", "Shopping"), ("淘宝", "Shopping"), ("tmall", "Shopping"), ("天猫", "Shopping"),
    ("jd.com", "Shopping"), ("京东", "Shopping"), ("pinduoduo", "Shopping"),
    ("拼多多", "Shopping"), ("uniqlo", "Shopping"), ("electronics", "Shopping"),
    # utilities
    ("state grid", "Utilities"), ("国家电网", "Utilities"), ("china mobile", "Utilities"),
    ("中国移动", "Utilities"), ("china unicom", "Utilities"), ("中国联通", "Utilities"),
    ("china telecom", "Utilities"), ("中国电信", "Utilities"), ("燃气", "Utilities"),
    # housing
    ("rent", "Housing"), ("房租", "Housing"), ("物业", "Housing"),
    # health
    ("hospital", "Health"), ("医院", "Health"), ("pharmacy", "Health"), ("药房", "Health"),
    ("clinic", "Health"), ("诊所", "Health"),
    # education
    ("tuition", "Education"), ("学费", "Education"), ("bookstore", "Education"),
    ("书店", "Education"),
    # entertainment
    ("cinema", "Entertainment"), ("电影", "Entertainment"), ("steam", "Entertainment"),
    # cash / fees
    ("atm", "Cash"), ("取现", "Cash"), ("service fee", "Fees"), ("手续费", "Fees"),
)

CategorySource = Literal["provided", "merchant_rule", "fallback"]

_WS = re.compile(r"\s+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏ -‮⁦-⁩]")


@dataclass(frozen=True)
class CategoryResult:
    label: str  # display label used as the category_totals key
    key: str  # case-insensitive grouping key
    source: CategorySource


def clean_text(value: object, limit: int = MAX_LABEL_LEN) -> str:
    """NFKC, strip control/bidi characters, collapse whitespace, cap length."""
    if not isinstance(value, str):
        return ""
    text = _WS.sub(" ", _CONTROL.sub(" ", unicodedata.normalize("NFKC", value))).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _rule(keyword: str) -> re.Pattern[str]:
    if keyword.isascii():  # "rent" must not match "Parent"
        return re.compile(r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])")
    return re.compile(re.escape(keyword))


_COMPILED_RULES = tuple((_rule(k), c) for k, c in MERCHANT_RULES)


def categorize(category: object, merchant: object) -> CategoryResult:
    label = clean_text(category)
    if label.casefold() not in UNKNOWN_LABELS:
        return CategoryResult(label, label.casefold(), "provided")
    m = clean_text(merchant, limit=256).casefold()
    if m:
        for pattern, cat in _COMPILED_RULES:
            if pattern.search(m):
                return CategoryResult(cat, cat.casefold(), "merchant_rule")
    return CategoryResult(UNCATEGORIZED, UNCATEGORIZED.casefold(), "fallback")
