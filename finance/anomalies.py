"""Explainable, deterministic spending anomaly rules.

Every finding names the transaction it is about, the rule, and the baseline it was
compared against. Messages are descriptive only and never give financial advice.
Thresholds live in AnomalyConfig and are documented in docs/finance/RULES.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from .cleaning import CleanTxn, Flag
from .money import format_money, shift_period


@dataclass(frozen=True)
class AnomalyConfig:
    history_months: int = 3
    # A1: single debit far above this category's recent median
    spike_multiple: Decimal = Decimal("3")
    spike_min_excess: Decimal = Decimal("100.00")
    spike_min_history_txns: int = 3
    # A2: large debit when the category has too little history
    large_txn_threshold: Decimal = Decimal("2000.00")
    # A3: category monthly total far above its recent monthly mean
    month_spike_multiple: Decimal = Decimal("1.5")
    month_spike_min_excess: Decimal = Decimal("200.00")
    month_spike_min_active_months: int = 2
    # A4: same account + merchant + amount within a short window
    duplicate_window_seconds: int = 600


DEFAULT_ANOMALY_CONFIG = AnomalyConfig()


def _ratio(a: Decimal, b: Decimal) -> str:
    return f"{(a / b).quantize(Decimal('0.1'))}"


def detect_spending_anomalies(
    debits: list[CleanTxn], period: str, config: AnomalyConfig = DEFAULT_ANOMALY_CONFIG
) -> list[Flag]:
    """`debits`: all valid spending debits (any month), chronologically sorted.
    History = the `history_months` calendar months immediately before `period`."""
    hist_periods = {shift_period(period, -i) for i in range(1, config.history_months + 1)}
    current = [d for d in debits if d.period == period]
    history = [d for d in debits if d.period in hist_periods]
    flags: list[Flag] = []

    def add(code: str, sev: str, msg: str, tid: str) -> None:
        flags.append(Flag(code, "spending", sev, msg, tid, period))

    # A1 / A2: single transaction vs category history
    hist_by_cat: dict[str, list[Decimal]] = {}
    for d in history:
        hist_by_cat.setdefault(d.category.key, []).append(d.amount)
    for d in current:
        base = hist_by_cat.get(d.category.key, [])
        cat = d.category.label
        if len(base) >= config.spike_min_history_txns:
            med = Decimal(median(base))
            if med > 0 and d.amount > med * config.spike_multiple \
                    and d.amount - med >= config.spike_min_excess:
                add("LARGE_VS_CATEGORY_HISTORY", "warning",
                    f"Debit of {format_money(d.amount)} CNY is {_ratio(d.amount, med)}x the median "
                    f"({format_money(med)} CNY) of {len(base)} '{cat}' debits in the previous "
                    f"{config.history_months} months.", d.transaction_id)
        elif d.amount >= config.large_txn_threshold:
            add("LARGE_TRANSACTION", "info",
                f"Debit of {format_money(d.amount)} CNY meets the "
                f"{format_money(config.large_txn_threshold)} CNY large-transaction threshold; "
                f"'{cat}' has too little history for a personal baseline.", d.transaction_id)

    # A3: category month total vs previous months' mean (empty months count as 0)
    earliest = min((d.period for d in debits), default=period)
    if earliest <= shift_period(period, -config.history_months):
        by_cat: dict[str, list[CleanTxn]] = {}
        for d in current:
            by_cat.setdefault(d.category.key, []).append(d)
        for key in sorted(by_cat):
            monthly = {p: Decimal(0) for p in hist_periods}
            for d in history:
                if d.category.key == key:
                    monthly[d.period] += d.amount
            if sum(1 for v in monthly.values() if v > 0) < config.month_spike_min_active_months:
                continue
            mean = sum(monthly.values(), Decimal(0)) / config.history_months
            txns = by_cat[key]
            total = sum((d.amount for d in txns), Decimal(0))
            if total > mean * config.month_spike_multiple \
                    and total - mean >= config.month_spike_min_excess:
                # anchor on the largest contributing debit (ties -> lowest ID)
                anchor = sorted(txns, key=lambda d: (-d.amount, d.transaction_id))[0]
                add("CATEGORY_MONTH_SPIKE", "warning",
                    f"'{txns[0].category.label}' spending this month is {format_money(total)} CNY, "
                    f"{_ratio(total, mean)}x the {config.history_months}-month average of "
                    f"{format_money(mean)} CNY; this is its largest debit.", anchor.transaction_id)

    # A4: possible duplicate charge (distinct IDs)
    seen: dict[tuple[str, str, Decimal], CleanTxn] = {}
    for d in current:
        k = (d.account_id, d.merchant_key, d.amount)
        prev = seen.get(k)
        if prev is not None and d.merchant_key and \
                (d.timestamp - prev.timestamp).total_seconds() <= config.duplicate_window_seconds:
            add("POSSIBLE_DUPLICATE_CHARGE", "warning",
                f"Same merchant, account and amount ({format_money(d.amount)} CNY) as transaction "
                f"{prev.transaction_id} within {config.duplicate_window_seconds // 60} minutes. "
                "Both are counted.", d.transaction_id)
        seen[k] = d

    return flags
