"""Compatibility entry point for the cumulative architecture checker."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.arch_lint.checker import scan_directory  # noqa: E402
from shared.arch_lint.cli import main  # noqa: E402
from shared.arch_lint.graph import build_graph, find_cycles  # noqa: E402


def check_import_graph(repo_root):
    root = Path(repo_root)
    return [str(v) for v in scan_directory(root)] + [
        "Import cycle: " + " -> ".join(c) for c in find_cycles(build_graph(root))
    ]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or [str(ROOT)]))
