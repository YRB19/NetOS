"""Import-graph / dependency-direction isolation test (ADR-6).

Two things are proven here, not one:
  1. The real repository, as it stands after Slice 2, has zero import-graph violations.
  2. The checker itself actually detects a violation when one exists — a deliberately
     provocative test (per Stage 3 §25's explicit instruction) that plants a temporary,
     disposable module containing a forbidden import inside `data/`, runs the checker against
     it, and asserts it is caught, then removes the temporary module. A checker that always
     reports "clean" is worse than no checker at all, so this is not optional.
"""

import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestImportGraphIsolation(unittest.TestCase):
    def test_real_repository_has_zero_violations(self):
        from scripts.check_import_graph import check_import_graph

        violations = check_import_graph(REPO_ROOT)
        self.assertEqual(violations, [], f"Unexpected import-graph violations: {violations}")

    def test_checker_detects_a_planted_forbidden_import(self):
        from scripts.check_import_graph import check_import_graph

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            # Mirror just enough of the real tree for the checker's relative-path logic to work.
            data_dir = tmp_root / "data"
            data_dir.mkdir()
            (data_dir / "__init__.py").write_text("")
            planted = data_dir / "_planted_violation.py"
            planted.write_text("import risk_execution\n")  # forbidden per POLICY['data']

            violations = check_import_graph(tmp_root)

        self.assertEqual(len(violations), 1)
        self.assertIn("risk_execution", violations[0])
        self.assertIn("data", violations[0])

    def test_checker_ignores_allowed_domain_and_shared_imports(self):
        from scripts.check_import_graph import check_import_graph

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            data_dir = tmp_root / "data"
            data_dir.mkdir()
            (data_dir / "__init__.py").write_text("")
            (data_dir / "_ok.py").write_text("import domain\nimport shared\n")

            violations = check_import_graph(tmp_root)

        self.assertEqual(violations, [])

    def test_checker_detects_nested_forbidden_target(self):
        """Forbidding 'risk_execution' must also forbid 'risk_execution.broker' specifically —
        this is the exact scenario the historical adapter must never be able to reach into."""
        from scripts.check_import_graph import check_import_graph

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            data_dir = tmp_root / "data"
            data_dir.mkdir()
            (data_dir / "__init__.py").write_text("")
            planted = data_dir / "_planted_nested.py"
            planted.write_text("from risk_execution.broker import adapters\n")

            violations = check_import_graph(tmp_root)

        self.assertEqual(len(violations), 1)


if __name__ == "__main__":
    unittest.main()
