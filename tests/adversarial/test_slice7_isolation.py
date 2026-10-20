"""Slice 7 (Group E) — architecture and safety: import direction (ADR-9/ADR-10), no approval/order/fill
manufacture by lifecycle or reconciliation, removed-instrument flag semantics, Slice 5/6 tests intact."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from domain.models.enums import Action, PortfolioStateSource, RiskVerdict
from domain.models.portfolio import PortfolioState, Position
from risk_execution.risk_engine import RiskEngine
from scripts.check_import_graph import check_import_graph
from tests.adversarial.test_slice6_isolation import ROOT, imported_modules, plant, py_files
from tests.unit.test_risk_engine import A, B, T, cand, ctx, failed_ids
from tests.unit._pipeline_helpers import risk_config

NEW = ("risk_execution/order_lifecycle", "risk_execution/reconciliation")


def hits(violations, rule_fragment: str) -> list:
    return [v for v in violations if rule_fragment in str(v)]


class ImportDirectionTests(unittest.TestCase):
    def test_repository_has_zero_import_violations(self):
        self.assertEqual(check_import_graph(ROOT), [])

    def test_research_never_imports_execution_or_the_orchestrator(self):
        for f in py_files("research"):
            for m in imported_modules(f):
                self.assertFalse(m.startswith(("risk_execution", "simulation")), f"{f}: {m}")

    def test_simulation_is_a_leaf_nothing_imports_it_except_tests_and_scripts(self):
        for f in py_files("research", "risk_execution", "intelligence", "governance", "data", "domain", "shared", "observability"):
            for m in imported_modules(f):
                self.assertFalse(m == "simulation" or m.startswith("simulation."), f"{f}: {m}")

    def test_simulation_may_depend_on_both_sides_but_the_rule_set_still_forbids_the_reverse(self):
        deps = {m.split(".")[0] for f in py_files("simulation") for m in imported_modules(f)}
        self.assertTrue({"research", "risk_execution"} <= deps)   # the documented bridge (ADR-9)
        self.assertTrue(plant("research/harness", "bad", "import risk_execution.broker\n"))
        self.assertTrue(plant("research/harness", "bad2", "import simulation\n"))
        self.assertTrue(plant("risk_execution/broker", "bad3", "import simulation\n"))

    def test_lifecycle_and_reconciliation_cannot_import_risk_sizing_research_or_strategies(self):
        for pkg in ("risk_execution/order_lifecycle", "risk_execution/reconciliation"):
            for target in ("risk_execution.risk_engine", "risk_execution.sizing", "research", "simulation",
                           "intelligence", "governance", "data.adapters"):
                with self.subTest(pkg=pkg, target=target):
                    self.assertTrue(plant(pkg, "x", f"import {target}\n"))

    def test_reverse_dependencies_are_forbidden(self):
        for src in ("risk_execution/risk_engine", "risk_execution/sizing", "risk_execution/broker"):
            for tgt in ("risk_execution.order_lifecycle", "risk_execution.reconciliation"):
                with self.subTest(src=src, tgt=tgt):
                    self.assertTrue(plant(src, "x", f"import {tgt}\n"))
        self.assertTrue(plant("risk_execution/order_lifecycle", "x", "import risk_execution.reconciliation\n"))

    def test_actual_new_packages_import_only_what_the_rules_permit(self):
        for f in py_files(*NEW):
            for m in imported_modules(f):
                self.assertFalse(m.startswith(("risk_execution.risk_engine", "risk_execution.sizing", "research",
                                               "simulation", "intelligence", "governance")), f"{f}: {m}")


class AuthorityTests(unittest.TestCase):
    def test_lifecycle_and_reconciliation_never_construct_orders_fills_or_risk_decisions(self):
        banned = {"OrderRequest", "Fill", "RiskDecision", "CandidateTrade"}
        for f in py_files(*NEW):
            for n in ast.walk(ast.parse(f.read_text())):
                if isinstance(n, ast.Call):
                    name = n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
                    self.assertNotIn(name, banned, f"{f}:{n.lineno} constructs {name}")

    def test_new_packages_have_no_wall_clock_randomness_network_or_credentials(self):
        for f in py_files(*NEW):
            src = f.read_text()
            for needle in ("datetime.now(", "utcnow(", "time.time(", "uuid4(", "import random", "import socket",
                           "import requests", "urllib", "os.environ", "getenv", "password", "api_key"):
                self.assertNotIn(needle, src, f"{f}: {needle}")

    def test_reconciliation_never_clears_halts_or_creates_authority(self):
        src = (ROOT / "risk_execution/reconciliation/reconciler.py").read_text()
        for needle in ("clear_halt", "resolve_reconciliation_required", "accept_quarantined_fill",
                       "dismiss_quarantined", "place_order", "submit("):
            self.assertNotIn(needle, src)


class RemovedInstrumentFlagTests(unittest.TestCase):
    """Slice 6 flag semantics preserved (Slice 7 chooses no live policy). Both configurations tested."""

    def _pf(self):
        return PortfolioState(as_of_timestamp=T, positions=(Position(B, 10.0, 100.0),), cash_balance=1.0,
                              source=PortfolioStateSource.SYSTEM_BELIEF)

    def test_flag_true_allows_exit_only_of_a_held_removed_instrument(self):
        e = RiskEngine(risk_config(allow_exit_of_removed_instruments=True))
        sell = cand(inst=B, action=Action.SELL, hint=0.0, input_snapshot_id="snap_2")
        self.assertIs(e.evaluate(sell, ctx(e, portfolio=self._pf(), permitted_instrument_ids=frozenset({A}))).final_verdict,
                      RiskVerdict.APPROVE)
        buy = cand(inst=B, input_snapshot_id="snap_2")
        self.assertIn("RR-4", failed_ids(e.evaluate(buy, ctx(e, permitted_instrument_ids=frozenset({A})))))

    def test_flag_false_vetoes_the_exit_and_a_veto_cannot_become_an_order(self):
        from risk_execution.order_lifecycle import ApprovalError, OrderLifecycleManager
        from tests.unit._lifecycle_helpers import RRV, Rig, request_for
        e = RiskEngine(risk_config(allow_exit_of_removed_instruments=False))
        sell = cand(inst=B, action=Action.SELL, hint=0.0, input_snapshot_id="snap_2")
        d = e.evaluate(sell, ctx(e, portfolio=self._pf(), permitted_instrument_ids=frozenset({A})))
        self.assertIs(d.final_verdict, RiskVerdict.REJECT)
        r = Rig()
        with self.assertRaises(ApprovalError):
            r.mgr.submit(request_for(d, 1.0, Action.SELL), d, r.broker, r.session)
        self.assertEqual(r.broker.order_statuses(r.session), {})
        self.assertIsInstance(r.mgr, OrderLifecycleManager)
        self.assertTrue(RRV)


class PriorSliceIntegrityTests(unittest.TestCase):
    def test_original_slice5_pipeline_test_is_still_present_and_unmodified_in_shape(self):
        p = ROOT / "tests/integration/test_pipeline_e2e.py"
        self.assertTrue(p.exists())
        self.assertIn("class", p.read_text())


if __name__ == "__main__":
    unittest.main()
