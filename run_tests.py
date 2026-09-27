"""Run the cumulative pytest suite (including unittest-compatible tests)."""

import sys
from pathlib import Path

import pytest

if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    raise SystemExit(pytest.main(sys.argv[1:] or [str(root / "tests")]))
