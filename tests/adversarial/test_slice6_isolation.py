"""Slice 6 isolation guarantees: risk independence, sizing monopoly on OrderRequest,
no credentials/network anywhere in the execution path, RR-9 structural boundary."""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from scripts.check_import_graph import check_import_graph

ROOT = Path(__file__).resolve().parents[2]


def plant(pkg_dir: str, name: str, code: str) -> list:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cur = d
        for p in pkg_dir.split("/"):
            cur = cur / p
            cur.mkdir(exist_ok=True)
            (cur / "__init__.py").write_text("")
        (cur / f"{name}.py").write_text(code)
        return check_import_graph(d)


def py_files(*dirs: str):
    for d in dirs:
        yield from (ROOT / d).rglob("*.py")


def imported_modules(path: Path) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(ast.parse(path.read_text())):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
    return out


class ArchitectureTests(unittest.TestCase):
    def test_repository_has_zero_violations(self):
        self.assertEqual(check_import_graph(ROOT), [])

    def test_checker_catches_each_new_slice6_boundary(self):
        cases = [
            ("risk_execution/risk_engine", "intelligence.baseline.tier2_momentum", "intelligence"),
            ("risk_execution/risk_engine", "risk_execution.sizing", "risk->sizing"),
            ("risk_execution/risk_engine", "risk_execution.broker", "risk->broker"),
            ("risk_execution/risk_engine", "research.harness", "risk->research"),
            ("risk_execution/sizing", "risk_execution.risk_engine", "sizing->risk engine"),
            ("risk_execution/sizing", "risk_execution.broker", "sizing->broker"),
            ("risk_execution/sizing", "intelligence.baseline", "sizing->strategy"),
            ("risk_execution/broker", "risk_execution.risk_engine", "broker->risk"),
            ("risk_execution/broker", "risk_execution.sizing", "broker->sizing"),
            ("risk_execution/broker", "intelligence.baseline", "broker->strategy"),
            ("intelligence/baseline", "risk_execution.risk_engine", "strategy->risk"),
            ("intelligence/baseline", "risk_execution.sizing", "strategy->sizing"),
            ("intelligence/baseline", "risk_execution.broker", "strategy->broker"),
            ("intelligence/baseline", "simulation", "strategy->orchestrator"),
            ("research/harness", "risk_execution.broker", "research->broker (Slice 5 rule kept)"),
            ("simulation", "intelligence.baseline", "orchestrator->concrete strategy"),
            ("simulation", "data.adapters", "orchestrator->data adapter"),
            ("data/features", "simulation", "plane->orchestrator"),
        ]
        for pkg, imp, label in cases:
            with self.subTest(label):
                v = plant(pkg, "_planted", f"import {imp}\n")
                self.assertEqual(len(v), 1, f"{label}: expected 1 violation, got {v}")

    def test_simulation_package_is_registered_and_scanned(self):
        v = plant("simulation", "_planted", "import intelligence.llm_component\n")
        self.assertEqual(len(v), 1)


class ExecutionPathSafetyTests(unittest.TestCase):
    FORBIDDEN_MODULES = {"socket", "ssl", "http", "urllib", "requests", "httpx", "aiohttp", "websocket",
                         "websockets", "kiteconnect", "upstox_client", "fyers_apiv3", "dotenv", "keyring"}  # fmt: skip

    def test_no_network_broker_sdk_or_secret_modules_imported_in_execution_path(self):
        for f in py_files("risk_execution", "simulation", "intelligence", "data/features"):
            bad = {m for m in imported_modules(f) if m.split(".")[0] in self.FORBIDDEN_MODULES}
            self.assertFalse(bad, f"{f.relative_to(ROOT)} imports {bad}")

    def test_no_environment_access_in_execution_path(self):
        for f in py_files("risk_execution", "simulation"):
            text = f.read_text()
            self.assertNotIn("os.environ", text, f)
            self.assertNotIn("getenv", text, f)

    def test_wall_clock_and_randomness_absent_from_risk_sizing_broker(self):
        for f in py_files("risk_execution"):
            mods = imported_modules(f)
            self.assertNotIn("random", mods, f)
            self.assertNotIn("secrets", mods, f)
            text = f.read_text()
            for n in ("datetime.now(", "utcnow(", "time.time(", "uuid4("):
                self.assertNotIn(n, text, f"{f}: {n}")

    def test_only_sizing_constructs_order_requests(self):
        owners = set()
        for f in py_files("risk_execution", "simulation", "intelligence", "research", "data", "domain/models"):
            for n in ast.walk(ast.parse(f.read_text())):
                if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "OrderRequest":
                    owners.add(str(f.relative_to(ROOT)))
        self.assertEqual(owners, {"risk_execution/sizing/sizer.py"}, owners)

    def test_only_the_simulated_broker_constructs_fills(self):
        owners = set()
        # research/harness/runner.py is the Slice 5 Tier-1-only path with its own documented fill
        # model; it is unreachable from the Slice 6 pipeline and is excluded deliberately.
        for f in py_files("risk_execution", "simulation", "intelligence", "data"):
            for n in ast.walk(ast.parse(f.read_text())):
                if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "Fill":
                    owners.add(str(f.relative_to(ROOT)))
        self.assertEqual(owners, {"risk_execution/broker/adapters/simulated.py"}, owners)

    def test_strategy_modules_never_build_risk_decisions_or_portfolio_state(self):
        for f in py_files("intelligence"):
            for n in ast.walk(ast.parse(f.read_text())):
                if isinstance(n, ast.Call):
                    name = getattr(n.func, "id", getattr(n.func, "attr", ""))
                    self.assertNotIn(name, {"RiskDecision", "RiskCheckResult", "PortfolioState", "Order", "Fill"}, f)

    def test_risk_engine_has_no_writable_hooks_into_strategy_or_runner(self):
        for f in py_files("risk_execution/risk_engine"):
            mods = imported_modules(f)
            self.assertFalse({m for m in mods if m.startswith(("intelligence", "research", "simulation"))}, f)


if __name__ == "__main__":
    unittest.main()
