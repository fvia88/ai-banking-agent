import json
from pathlib import Path

import pytest

from finance._bootstrap import REPO_ROOT, ensure_repo_on_path

ensure_repo_on_path()

from contracts.models import Transaction  # noqa: E402

SYNTHETIC = Path(__file__).resolve().parent / "data" / "transactions_synthetic.json"
SHARED_TXNS = REPO_ROOT / "fixtures" / "transactions.json"
SHARED_CASES = REPO_ROOT / "fixtures" / "expected_cases.json"


def load(path: Path) -> list[Transaction]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("transactions", [])
    return [Transaction.model_validate(r) for r in raw]


@pytest.fixture(scope="session")
def synthetic() -> list[Transaction]:
    return load(SYNTHETIC)


@pytest.fixture(scope="session")
def shared() -> list[Transaction]:
    if not SHARED_TXNS.exists():
        pytest.skip("fixtures/transactions.json not present")
    return load(SHARED_TXNS)


@pytest.fixture(scope="session")
def t12() -> dict:
    if not SHARED_CASES.exists():
        pytest.skip("fixtures/expected_cases.json not present")
    cases = json.loads(SHARED_CASES.read_text(encoding="utf-8"))
    return next(c for c in cases if c["case_id"] == "T12")


@pytest.fixture
def tx():
    """Factory for one validated Transaction with sensible defaults."""
    counter = iter(range(1, 10_000))

    def make(amount="10.00", direction="debit", merchant="Luckin Coffee", category="Food",
             timestamp="2026-09-10T12:00:00+08:00", transaction_id=None, account_id="ACC-T",
             note=""):
        return Transaction.model_validate(dict(
            transaction_id=transaction_id or f"T-{next(counter):04d}", account_id=account_id,
            timestamp=timestamp, amount=amount, direction=direction, merchant=merchant,
            category=category, note=note))

    return make
