"""Make the repo root importable so `contracts` resolves when running the CLI or
tests from any working directory. Production code imports `contracts.models`
directly and never redefines shared DTOs."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def ensure_repo_on_path() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
