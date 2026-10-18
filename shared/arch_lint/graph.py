#!/usr/bin/env python3
"""Import-graph / dependency-direction lint. Stage 3 ADR-6, §1, §17.

Enforces plane-isolation guarantees as a build-time fact rather than a
code-review convention:

  - domain/       must never import data/, intelligence/, risk_execution/,
                  research/, observability/, governance/ (pure data shapes only)
  - intelligence/ must never import risk_execution/ or research/, and must
                  never import data/adapters or data/normalization directly
                  (only data/features' output types + domain)
  - research/     must never import risk_execution/ or governance/
                  (no write path to live execution or Plane 0, Stage 3 §11/§16)
  - no import cycles anywhere in the first-party module graph

Usage: python3 tools/check_import_graph.py
Exit code 0 = no violations. Non-zero = violations found (printed).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

FIRST_PARTY_TOP_LEVEL = {
    "domain",
    "data",
    "intelligence",
    "risk_execution",
    "observability",
    "research",
    "shared",
    "governance",
    "simulation",
}


def _iter_py_files(root: Path):
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        parts = rel.parts
        if parts[0] in ("tests", "tools", "scripts", "deploy"):
            continue
        if parts[0] not in FIRST_PARTY_TOP_LEVEL:
            continue
        yield path


def _module_name(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _extract_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                modules.append(node.module)
    return modules


def _matches_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def build_graph(root: Path) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {}
    for path in _iter_py_files(root):
        mod = _module_name(path, root)
        imports = [
            imp for imp in _extract_imports(path) if imp.split(".")[0] in FIRST_PARTY_TOP_LEVEL
        ]
        graph[mod] = imports
    return graph


def find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Detect cycles among first-party modules via DFS."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {m: WHITE for m in graph}
    cycles: list[list[str]] = []
    stack: list[str] = []

    def dfs(node: str) -> None:
        color[node] = GRAY
        stack.append(node)
        for neighbor in graph.get(node, []):
            # Resolve neighbor to the closest known graph key (module or package __init__)
            candidates = [neighbor] + [
                ".".join(neighbor.split(".")[:i]) for i in range(len(neighbor.split(".")), 0, -1)
            ]
            target = next((c for c in candidates if c in graph), None)
            if target is None:
                continue
            if color.get(target, WHITE) == WHITE:
                dfs(target)
            elif color.get(target) == GRAY:
                if target in stack:
                    idx = stack.index(target)
                    cycles.append(stack[idx:] + [target])
        stack.pop()
        color[node] = BLACK

    for node in list(graph.keys()):
        if color[node] == WHITE:
            dfs(node)
    return cycles
