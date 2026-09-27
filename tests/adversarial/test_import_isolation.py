"""ADR-6: the architectural isolation test (mandatory, per the
implementation prompt's "ARCHITECTURAL ISOLATION TEST" section).

Two things are proven here, deliberately kept separate:

1. `test_checker_detects_illegal_import` — builds a temporary, throwaway
   directory tree (NOT the real repository) containing a stub module that
   illegally imports `risk_execution.broker` from a `research` package,
   and asserts `scan_directory` catches it. This is what proves the
   checker actually works, without ever introducing a real violation into
   the codebase it protects (the Definition of Done explicitly requires
   "No forbidden imports exist in the real codebase").

2. `test_real_repository_has_zero_violations` — runs the exact same
   checker against the actual repository root and asserts zero violations.
   This is the check that would fail the build (and does fail it, via the
   CLI in CI) if a forbidden import were ever added for real.

Both tests call `shared.arch_lint.checker.scan_directory` directly rather
than shelling out to the CLI, so failures point straight at a Python
traceback/assertion rather than parsed subprocess output.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shared.arch_lint.checker import scan_directory

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestArchitecturalIsolationCheckerDetectsViolations(unittest.TestCase):
    def test_checker_detects_illegal_research_to_risk_execution_broker_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # Minimal stand-in for the real risk_execution.broker package —
            # the checker only needs the import graph, not real broker code.
            (root / "risk_execution" / "broker").mkdir(parents=True)
            (root / "risk_execution" / "__init__.py").write_text("")
            (root / "risk_execution" / "broker" / "__init__.py").write_text("")
            (root / "risk_execution" / "broker" / "adapter.py").write_text(
                "class BrokerAdapter:\n    pass\n"
            )

            # The deliberately illegal stub module, per the implementation
            # prompt: research/forbidden_import_example.py importing from
            # risk_execution.broker.
            (root / "research").mkdir(parents=True)
            (root / "research" / "__init__.py").write_text("")
            (root / "research" / "forbidden_import_example.py").write_text(
                "from risk_execution.broker.adapter import BrokerAdapter\n\n"
                "def do_something_it_should_never_be_able_to_do():\n"
                "    return BrokerAdapter()\n"
            )

            violations = scan_directory(root)

        self.assertTrue(
            violations,
            "The isolation checker FAILED to detect a deliberately illegal "
            "research -> risk_execution.broker import. This means ADR-6 "
            "enforcement is not working.",
        )
        matching = [
            v
            for v in violations
            if v.owning_package == "research" and v.imported_module.startswith("risk_execution")
        ]
        self.assertTrue(
            matching,
            f"Expected a violation attributing the illegal import to package "
            f"'research' importing 'risk_execution.*'; got: {violations}",
        )

    def test_checker_detects_illegal_intelligence_to_data_adapters_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "adapters").mkdir(parents=True)
            (root / "data" / "__init__.py").write_text("")
            (root / "data" / "adapters" / "__init__.py").write_text("")
            (root / "data" / "adapters" / "feed.py").write_text("class Feed:\n    pass\n")

            (root / "intelligence").mkdir(parents=True)
            (root / "intelligence" / "__init__.py").write_text("")
            (root / "intelligence" / "forbidden.py").write_text("import data.adapters.feed\n")

            violations = scan_directory(root)

        self.assertTrue(violations)
        self.assertTrue(
            any(
                v.owning_package == "intelligence" and v.imported_module.startswith("data.adapters")
                for v in violations
            )
        )

    def test_checker_does_not_flag_a_legal_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "research").mkdir(parents=True)
            (root / "research" / "__init__.py").write_text("")
            (root / "research" / "harmless.py").write_text(
                "import datetime\nimport json\n\n"
                "def compute():\n    return datetime.datetime.now().isoformat()\n"
            )
            violations = scan_directory(root)
        self.assertEqual(violations, [])


class TestRealRepositoryHasZeroViolations(unittest.TestCase):
    """This is the test that would fail the real build if ADR-6 were ever

    violated for real — it scans the actual repository, not a fixture.
    """

    def test_real_repository_has_zero_violations(self):
        violations = scan_directory(REPO_ROOT)
        self.assertEqual(
            violations,
            [],
            "The real codebase contains ADR-6 import-isolation violations:\n"
            + "\n".join(str(v) for v in violations),
        )


if __name__ == "__main__":
    unittest.main()
