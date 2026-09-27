"""Ensures the repository root is importable during test collection.

Under `pytest`, the rootdir is normally auto-detected and added to
`sys.path` via its rootdir/import-mode machinery, but this file makes that
explicit and environment-independent (e.g. when running
`python -m unittest discover` directly, which relies on cwd being on
sys.path rather than any pytest-specific mechanism). Belt-and-braces, no
behavior beyond a sys.path insert.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
