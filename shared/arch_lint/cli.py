"""CLI entry point for ADR-6 import-isolation enforcement.

Usage:
    python -m shared.arch_lint.cli [ROOT]

Exits 0 with no output if no violations are found.
Exits 1 and prints every violation (file, line, rule, rationale) otherwise.

This is the exact command run in CI (see .github/workflows/ci.yml) and is
safe to run locally at any time — it has no side effects and makes no
network calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

from shared.arch_lint.checker import scan_directory
from shared.arch_lint.graph import build_graph, find_cycles


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0]) if argv else Path(__file__).resolve().parents[2]

    violations = [str(v) for v in scan_directory(root)]
    violations.extend("Import cycle: " + " -> ".join(c) for c in find_cycles(build_graph(root)))
    if not violations:
        print(f"ADR-6 import-isolation check: PASSED (0 violations) — scanned {root}")
        return 0

    print(f"ADR-6 import-isolation check: VIOLATIONS ({len(violations)} issue(s))\n")
    for v in violations:
        print(str(v))
        print()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
