"""ADR-6: Import-graph / dependency-direction enforcement — the checker.

This is a small, dependency-free, deterministic static analyzer. It parses
every `.py` file under a given root using Python's own `ast` module (no
import execution, no side effects, safe to run against untrusted or
half-written code), determines which top-level package each file belongs
to (its "owning package"), extracts every module it imports, and reports
any import that violates a rule in `rules.py`.

Design choices, and why:

- **AST-based, not import-based.** We never `import` the scanned modules.
  A checker that worked by importing code could itself be a vector for
  exactly the kind of accidental coupling it's meant to prevent (e.g. an
  import error, a network call at import time). Static parsing has none
  of that risk and is fully deterministic.
- **No third-party dependency.** This is a small, single-purpose tool;
  pulling in a general import-linting library would be a dependency this
  project doesn't need yet (Stage 3 §22's "dependency-sprawl discipline").
- **Pure function core (`scan_directory`) + thin CLI wrapper.** The core
  logic takes a root path and returns data (a list of `Violation`), so it
  can be exercised directly and deterministically in tests, including
  against temporary directories that are NOT part of the real repository
  — this is what lets the mandatory "illegal dependency test" prove the
  checker works without ever introducing a real violation into the
  codebase it protects.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from shared.arch_lint.rules import rules_for_owning_package

# Directories that are never scanned: they aren't production plane code,
# or (for .git/venv/build artifacts) aren't Python source at all.
EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "build",
        "dist",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
    }
)

# Top-level directories that are recognized "planes" for ownership purposes.
# A file outside of these (e.g. a root-level conftest.py, or scripts/) has
# no owning package and is not subject to plane-isolation rules — it may
# still be covered by other checks (lint, tests) but ADR-6 is specifically
# about inter-plane boundaries.
KNOWN_TOP_LEVEL_PACKAGES = frozenset(
    {
        "governance",
        "data",
        "domain",
        "intelligence",
        "risk_execution",
        "observability",
        "research",
        "shared",
        "simulation",
    }
)


@dataclass(frozen=True)
class Violation:
    file: Path
    line: int
    owning_package: str
    imported_module: str
    rule_source_package: str
    rule_forbidden_prefix: str
    rationale: str

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return (
            f"{self.file}:{self.line}: package '{self.owning_package}' imports "
            f"forbidden module '{self.imported_module}' "
            f"(rule: {self.rule_source_package} -X-> {self.rule_forbidden_prefix})\n"
            f"    rationale: {self.rationale}"
        )


def _owning_package(file_path: Path, root: Path) -> str | None:
    """Return the dotted top-level-plane package a file belongs to, or None."""
    try:
        rel = file_path.relative_to(root)
    except ValueError:
        return None
    parts = rel.parts
    if not parts:
        return None
    top = parts[0]
    if top not in KNOWN_TOP_LEVEL_PACKAGES:
        return None
    # Build the dotted owning package from directory parts only (exclude the
    # filename itself, e.g. governance/config/loader.py -> "governance.config").
    dir_parts = parts[:-1] if file_path.suffix == ".py" else parts
    return ".".join(dir_parts) if dir_parts else top


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        yield path


def _extract_imports(tree: ast.Module) -> list[tuple[str, int]]:
    """Return a list of (dotted_module_name, line_number) for every import."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # Relative import (e.g. `from . import x`). These stay within
                # the same package by construction and cannot cross a
                # top-level plane boundary, so they are not a concern for
                # this checker.
                continue
            if node.module:
                found.append((node.module, node.lineno))
    return found


def scan_file(file_path: Path, root: Path) -> list[Violation]:
    owning_package = _owning_package(file_path, root)
    if owning_package is None:
        return []
    applicable_rules = rules_for_owning_package(owning_package)
    if not applicable_rules:
        return []

    source = file_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:  # pragma: no cover - defensive
        raise SyntaxError(f"Could not parse {file_path}: {exc}") from exc

    violations: list[Violation] = []
    for imported_module, line in _extract_imports(tree):
        for rule in applicable_rules:
            if rule.forbids(imported_module):
                violations.append(
                    Violation(
                        file=file_path,
                        line=line,
                        owning_package=owning_package,
                        imported_module=imported_module,
                        rule_source_package=rule.source_package,
                        rule_forbidden_prefix=rule.forbidden_prefix,
                        rationale=rule.rationale,
                    )
                )
    return violations


def scan_directory(root: Path) -> list[Violation]:
    """Scan every .py file under `root` and return all ADR-6 violations found.

    `root` is treated as the repository root for the purpose of determining
    package ownership (i.e. `root / "research" / "x.py"` owns package
    "research"). This makes the function fully testable against an
    arbitrary temporary directory laid out the same way, independent of
    where the real repository happens to live.
    """
    root = root.resolve()
    violations: list[Violation] = []
    for file_path in _iter_python_files(root):
        violations.extend(scan_file(file_path, root))
    return violations
