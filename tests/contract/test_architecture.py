"""Architecture / import-graph contract tests. Stage 3 ADR-6, Slice 3 spec §17.

Includes a deliberately provocative negative case (a synthetic module
with a forbidden import) to prove the checker actually catches
violations, not merely that it runs — per the spirit of Stage 3 §25's
first-milestone instruction, applied here to Slice 3's own checker.
"""

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestImportGraphChecker(unittest.TestCase):
    def test_current_repository_has_zero_violations(self):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "check_import_graph.py")],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("0 violations", result.stdout)

    def test_checker_catches_a_synthetic_forbidden_import(self):
        """Deliberately provocative test: inject a forbidden import into a
        scratch copy of the tree and confirm the checker fails on it."""
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name in (
                "domain",
                "data",
                "intelligence",
                "risk_execution",
                "research",
                "observability",
                "governance",
                "shared",
                "tools",
            ):
                src = REPO_ROOT / name
                if src.exists():
                    shutil.copytree(src, tmp_path / name)
            # Inject a forbidden import: research/ importing risk_execution/broker
            offender = tmp_path / "research" / "harness" / "_synthetic_offender.py"
            offender.write_text(
                textwrap.dedent(
                    """
                from risk_execution.broker import adapters  # forbidden: research -> risk_execution
                """
                )
            )
            result = subprocess.run(
                [sys.executable, str(tmp_path / "tools" / "check_import_graph.py")],
                cwd=tmp_path,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("VIOLATIONS", result.stdout)
            self.assertIn("research", result.stdout)

    def test_intelligence_does_not_import_broker_or_execution(self):
        for path in (REPO_ROOT / "intelligence").rglob("*.py"):
            source = path.read_text()
            self.assertNotIn("risk_execution.broker", source, msg=str(path))

    def test_intelligence_does_not_import_data_adapters_directly(self):
        for path in (REPO_ROOT / "intelligence").rglob("*.py"):
            source = path.read_text()
            self.assertNotIn("data.adapters", source, msg=str(path))
            self.assertNotIn("data.normalization", source, msg=str(path))

    def test_domain_does_not_import_intelligence_or_data(self):
        for path in (REPO_ROOT / "domain").rglob("*.py"):
            source = path.read_text()
            self.assertNotIn("import intelligence", source, msg=str(path))
            self.assertNotIn("from intelligence", source, msg=str(path))
            self.assertNotIn("from data.", source, msg=str(path))

    def test_baseline_makes_no_network_calls(self):
        for path in (REPO_ROOT / "intelligence" / "baseline").rglob("*.py"):
            source = path.read_text()
            for forbidden in ("requests", "socket", "urllib", "http.client", "aiohttp"):
                self.assertNotIn(forbidden, source, msg=f"{forbidden} found in {path}")


if __name__ == "__main__":
    unittest.main()
