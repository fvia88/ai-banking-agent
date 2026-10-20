"""P3 public entry point: analyze_spending (spec v1.0 §6, binding signature).

Pure calculation: no DB, no HTTP, no LLM, no backend/agent imports.
Rules are documented in docs/finance/RULES.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from contracts.models import Anomaly, SpendingReport, Transaction

from .anomalies import DEFAULT_ANOMALY_CONFIG, AnomalyConfig, detect_spending_anomalies
from .categories import UNCATEGORIZED
from .cleaning import CleanResult, CleanTxn, Flag, clean_transactions
from .money import ZERO, format_money, money, period_range, validate_period


@dataclass(frozen=True)
class SpendingConfig:
    # Category labels (case-insensitive) whose debits are NOT counted as spending.
    # Default: none (see README "Open questions").
    excluded_debit_categories: frozenset[str] = field(default_factory=frozenset)
    anomalies: AnomalyConfig = DEFAULT_ANOMALY_CONFIG


DEFAULT_CONFIG = SpendingConfig()

_KIND = {"spending": 0, "data_quality": 1, "info": 2}
_SEV = {"warning": 0, "info": 1}


def _sort_key(f: Flag) -> tuple:
    return (_KIND.get(f.kind, 9), _SEV.get(f.severity, 9), f.code, f.transaction_id, f.message)


def _excluded(r: CleanTxn, cfg: SpendingConfig) -> bool:
    return r.category.key in {c.casefold() for c in cfg.excluded_debit_categories}


def _spending_debits(records: list[CleanTxn], cfg: SpendingConfig) -> list[CleanTxn]:
    return [r for r in records if r.direction == "debit" and not _excluded(r, cfg)]


def _aggregate(debits: list[CleanTxn], all_records: list[CleanTxn]) -> dict[str, Decimal]:
    """Sum by case-insensitive category key. The displayed spelling is the one on the
    earliest transaction with that key across ALL input (records are pre-sorted, so
    this is deterministic and stable from month to month)."""
    labels: dict[str, str] = {}
    for r in all_records:
        labels.setdefault(r.category.key, r.category.label)
    sums: dict[str, Decimal] = {}
    for d in debits:
        sums[d.category.key] = sums.get(d.category.key, ZERO) + d.amount
    return {labels[k]: money(v) for k, v in sorted(sums.items(), key=lambda kv: labels[kv[0]])}


def _diagnose(cleaned: CleanResult, period: str, cfg: SpendingConfig) -> list[Flag]:
    debits_all = _spending_debits(cleaned.records, cfg)
    debits = [d for d in debits_all if d.period == period]
    in_period = [r for r in cleaned.records if r.period == period]
    flags = detect_spending_anomalies(debits_all, period, cfg.anomalies)
    flags += [f for f in cleaned.flags if f.period in (None, period)]

    def note(code: str, msg: str, tid: str = "", kind: str = "info") -> None:
        flags.append(Flag(code, kind, "info", msg, tid, period))

    credits = [r for r in in_period if r.direction == "credit"]
    if credits:
        note("CREDITS_EXCLUDED", f"{len(credits)} credit inflow(s) totalling "
             f"{format_money(sum((c.amount for c in credits), ZERO))} CNY are not spending and "
             "are excluded from all totals.")
    for r in credits:
        if r.is_refund:
            note("REFUND_NOT_NETTED", f"Refund credit of {format_money(r.amount)} CNY recorded; "
                 "spending totals are gross and are not reduced by refunds.", r.transaction_id)
    for d in debits:
        if d.category.label == UNCATEGORIZED and d.category.source == "fallback":
            note("UNCATEGORIZED", "No usable category label or merchant rule; grouped as "
                 "'Uncategorized'.", d.transaction_id)
    excluded = [r for r in in_period if r.direction == "debit" and _excluded(r, cfg)]
    if excluded:
        note("EXCLUDED_DEBIT_CATEGORIES", f"{len(excluded)} debit(s) in configured excluded "
             "categories are not counted as spending.")
    if len({r.account_id for r in in_period}) > 1:
        note("MULTIPLE_ACCOUNTS", "Transactions from more than one account were aggregated.")
    if not debits:
        note("NO_SPENDING_IN_PERIOD", "No valid debit transactions were found for this period.")
    return sorted(flags, key=_sort_key)


def spending_diagnostics(
    transactions: list[Transaction], period: str, config: SpendingConfig = DEFAULT_CONFIG
) -> list[Flag]:
    """All findings for a period, including period-level notes that the contract's
    `Anomaly` (which requires a transaction_id) cannot carry. For CLI / UI detail."""
    validate_period(period)
    return _diagnose(clean_transactions(transactions), period, config)


def build_spending_report(
    transactions: list[Transaction], period: str, config: SpendingConfig = DEFAULT_CONFIG
) -> SpendingReport:
    """Configurable implementation behind analyze_spending."""
    validate_period(period)
    cleaned = clean_transactions(transactions)
    debits = [d for d in _spending_debits(cleaned.records, config) if d.period == period]
    category_totals = _aggregate(debits, cleaned.records)
    total = money(sum(category_totals.values(), ZERO))

    # Contract Anomaly = {transaction_id, reason}. Only spending anomalies and
    # data-quality problems tied to a specific transaction are reported here.
    anomalies = [
        Anomaly(transaction_id=f.transaction_id, reason=f"{f.code}: {f.message}")
        for f in _diagnose(cleaned, period, config)
        if f.transaction_id and f.kind in ("spending", "data_quality")
    ]
    return SpendingReport(period=period, currency="CNY", total_spending=total,
                          category_totals=category_totals, anomalies=anomalies)


def analyze_spending(transactions: list[Transaction], period: str) -> SpendingReport:
    """Spending report for one YYYY-MM month (Asia/Shanghai calendar).

    total_spending = exact Decimal sum of valid debits; credits (incl. refunds) are
    never spending. Raises ValueError only for a malformed `period`.
    """
    return build_spending_report(transactions, period, DEFAULT_CONFIG)


def monthly_totals(
    transactions: list[Transaction],
    start: str | None = None,
    end: str | None = None,
    config: SpendingConfig = DEFAULT_CONFIG,
) -> dict[str, Decimal]:
    """Spending per YYYY-MM, zero-filling empty months between start and end
    (defaults: first/last month with any valid transaction)."""
    for p in (start, end):
        if p is not None:
            validate_period(p)
    cleaned = clean_transactions(transactions)
    periods = sorted({r.period for r in cleaned.records})
    if not periods and (start is None or end is None):
        return {}
    lo, hi = start or periods[0], end or periods[-1]
    if lo > hi:
        raise ValueError("start period is after end period")
    totals = {p: ZERO for p in period_range(lo, hi)}
    for d in _spending_debits(cleaned.records, config):
        if d.period in totals:
            totals[d.period] += d.amount
    return {p: money(v) for p, v in totals.items()}
