"""Slice 6 — end-to-end strategy -> risk -> sizing -> simulated broker -> portfolio.

SYNTHETIC data and EXAMPLE limits. These are infrastructure tests, not evidence of
profitability, alpha, regulatory approval or live-execution behaviour.
"""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from data.features.builders import ContextFeatureBuilder
from domain.models.enums import OrderState, RiskVerdict, TerminalState
from intelligence.baseline.tier1_equal_weight import Tier1EqualWeightBuyHold
from research.experiments.store import ArtifactConflict
from research.harness.config import OrderRejectionPolicy
from research.harness.failures import FailureCategory, RunStatus
from risk_execution.broker.adapters.simulated import SimulatedBrokerAdapter
from risk_execution.risk_engine.config import KillSwitchState
from simulation import PipelineHarness
from simulation.artifacts import write_pipeline_run
from tests.unit._pipeline_helpers import (
    ISINS, TEST_START, broker_config, config, pipeline, risk_config, sizing_config, tier2, universe, weekly_bars,
)  # fmt: skip

from tests.unit._pipeline_helpers import JournaledHarness  # noqa: E402

PH = JournaledHarness


def run_t2(pc_over=None, fraction=0.3, bars=None, cfg=None, **kw):
    strat, b = tier2(fraction)
    pc = pipeline(b, **(pc_over or {}))
    return PH().run(cfg or config(), strat, bars or weekly_bars(), [universe()], pc, **kw), strat


class SuccessPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res, cls.strat = run_t2()
        cls.rr = cls.res.run

    def test_run_completes_with_orders_and_fills(self):
        self.assertIs(self.rr.status, RunStatus.COMPLETED, self.rr.failure)
        self.assertGreater(len(self.rr.trades), 0)
        self.assertGreater(self.res.summary["orders_submitted"], 0)
        self.assertEqual(self.res.summary["risk_vetoes"], 0)

    def test_first_rebalance_buys_exactly_the_top_selection_at_next_bar(self):
        first = self.rr.trades[0]
        buys = {t["instrument_id"] for t in self.rr.trades if t["decision_timestamp"] == first["decision_timestamp"]}
        self.assertEqual(buys, set(ISINS[-3:]))
        for t in self.rr.trades:
            self.assertGreater(t["fill_timestamp"], t["decision_timestamp"])
            self.assertEqual(t["execution_assumption"], "NEXT_BAR_OPEN")

    def test_every_fill_traces_back_to_an_approved_risk_decision_and_strategy_version(self):
        risk = {r["risk_decision_id"]: r for r in self.res.risk_decisions}
        sizing = {s["risk_decision_id"]: s for s in self.res.sizing_decisions}
        orders = {o["order_id"]: o for o in self.res.orders}
        for t in self.rr.trades:
            r = risk[t["risk_decision_id"]]
            self.assertEqual(r["verdict"], RiskVerdict.APPROVE.value)
            self.assertLessEqual(t["quantity"], r["approved_qty_ceiling"])
            self.assertEqual(sizing[t["risk_decision_id"]]["outcome"], "ORDER")
            self.assertEqual(t["strategy_version_id"], self.strat.strategy_version_id)
            self.assertEqual(orders[t["order_id"]]["final_state"], OrderState.FILLED.value)
            self.assertEqual(r["risk_rule_version_id"], risk_config().risk_rule_version().version_id)

    def test_order_state_history_uses_the_existing_lifecycle(self):
        for o in self.res.orders:
            self.assertEqual([h["to"] for h in o["state_history"]], ["APPROVED", "SUBMITTED", "ACKNOWLEDGED", "FILLED"])

    def test_portfolio_and_broker_ledgers_reconcile_every_cycle(self):
        self.assertTrue(self.res.reconciliations)
        self.assertTrue(all(r["ok"] for r in self.res.reconciliations))
        last = self.rr.equity_curve[-1]
        self.assertGreater(Decimal(str(last["cumulative_costs"])), 0)
        self.assertLess(Decimal(str(last["cash"])), Decimal(1_000_000))

    def test_decision_records_reconstruct_the_chain(self):
        filled = [d for d in self.rr.decision_records if d.terminal_state is TerminalState.FILLED]
        self.assertEqual(len(filled), len(self.res.orders))
        for d in filled:
            self.assertTrue(d.risk_decision_id and d.order_id and d.order_request_id and d.fills)
            self.assertEqual(d.strategy_version_id, self.strat.strategy_version_id)
            self.assertEqual(d.risk_rule_version_id, risk_config().risk_rule_version().version_id)
            self.assertEqual(d.autonomy_level, 0)

    def test_candidates_never_carry_quantities(self):
        for tr in self.rr.decisions:
            self.assertNotIn("quantity", tr.get("candidate", {}))

    def test_deterministic_across_repeat_runs(self):
        again, _ = run_t2()
        self.assertEqual(again.run.experiment_id, self.rr.experiment_id)
        self.assertEqual(again.run.run_id, self.rr.run_id)
        self.assertEqual(again.run.deterministic_summary(), self.rr.deterministic_summary())
        self.assertEqual(again.orders, self.res.orders)
        self.assertEqual(again.risk_decisions, self.res.risk_decisions)
        self.assertEqual(again.sizing_decisions, self.res.sizing_decisions)

    def test_artifacts_written_idempotently_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            p1 = write_pipeline_run(self.res, d)
            p2 = write_pipeline_run(self.res, d)
            self.assertEqual(p1, p2)
            for f in ("risk_decisions", "sizing_decisions", "orders", "broker_fills", "reconciliation"):
                self.assertTrue((p1 / "pipeline" / f"{f}.jsonl").exists())
            (p1 / "pipeline" / "orders.jsonl").write_text("tampered")
            with self.assertRaises(ArtifactConflict):
                write_pipeline_run(self.res, d)


class IdentityTests(unittest.TestCase):
    def test_every_configuration_group_is_part_of_experiment_identity(self):
        base, _ = run_t2()
        variants = [
            run_t2(dict(risk=risk_config(max_position_fraction=Decimal("0.5"))))[0],
            run_t2(dict(sizing=sizing_config(cash_buffer=Decimal("0.02"))))[0],
            run_t2(dict(broker=broker_config(max_fill_fraction_per_bar=Decimal("0.5"))))[0],
            run_t2(fraction=0.2)[0],
            run_t2(dict(account_scope="other"), )[0],
        ]
        ids = {v.run.experiment_id for v in variants} | {base.run.experiment_id}
        self.assertEqual(len(ids), 6)
        # fingerprint = comparison ENVIRONMENT (risk/sizing/broker/scope); the strategy fraction is not part of it
        fps = {v.run.comparison_fingerprint for v in variants} | {base.run.comparison_fingerprint}
        self.assertEqual(len(fps), 5)
        self.assertEqual(variants[3].run.comparison_fingerprint, base.run.comparison_fingerprint)

    def test_strategy_cannot_mutate_risk_configuration(self):
        pc = pipeline()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            pc.risk.max_leverage = Decimal("99")  # type: ignore[misc]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            pc.sizing.cash_buffer = Decimal("0")  # type: ignore[misc]


class VetoPathTests(unittest.TestCase):
    def test_fully_invested_strategy_at_a_leverage_cap_of_exactly_1_sees_drift_vetoes(self):
        """Documented interaction (docs/risk-engine.md): equal-weight hints summing to 1.0 against a
        gross/leverage cap of exactly 1.0 leave zero headroom, so a top-up BUY after price drift is
        vetoed by RR-1/RR-2. The run completes; no extra order is created."""
        tight = risk_config(max_gross_exposure_fraction=Decimal("1.0"), max_leverage=Decimal("1.0"))
        res, _ = run_t2(dict(risk=tight))
        self.assertIs(res.run.status, RunStatus.COMPLETED, res.run.failure)
        vetoes = [r for r in res.risk_decisions if r["verdict"] == "REJECT"]
        self.assertGreater(len(vetoes), 0)
        self.assertTrue(all({c["check_id"] for c in r["checks"] if not c["passed"]} <= {"RR-1", "RR-2"} for r in vetoes))
        self.assertTrue(all(o["final_state"] == "FILLED" for o in res.orders))

    def test_risk_veto_means_no_sizing_no_order_no_fill(self):
        res, _ = run_t2(dict(risk=risk_config(max_position_fraction=Decimal("0.2"))))  # 1/3 target > 0.2
        r = res.run
        self.assertIs(r.status, RunStatus.COMPLETED)
        self.assertGreater(res.summary["risk_vetoes"], 0)
        self.assertEqual((len(res.sizing_decisions), len(res.orders), len(res.broker_fills), len(r.trades)), (0, 0, 0, 0))
        self.assertTrue(all(x["verdict"] == "REJECT" for x in res.risk_decisions))
        self.assertTrue(all(any(c["check_id"] == "RR-1" and not c["passed"] for c in x["checks"]) for x in res.risk_decisions))
        self.assertEqual(Decimal(str(r.equity_curve[-1]["cash"])), Decimal(1_000_000))
        vetoed = [d for d in r.decision_records if d.terminal_state is TerminalState.REJECTED_AT_RISK]
        self.assertEqual(len(vetoed), res.summary["risk_vetoes"])
        self.assertTrue(all(d.risk_decision_id and d.order_id is None and not d.fills for d in vetoed))

    def test_vetoed_candidate_cannot_reach_sizing_or_broker(self):
        with mock.patch("simulation.runner.size_order", side_effect=AssertionError("sizing reached after veto")) as sz, \
             mock.patch.object(SimulatedBrokerAdapter, "place_order", side_effect=AssertionError("broker reached")) as pl:
            res, _ = run_t2(dict(kill_switch=KillSwitchState.ACTIVE))
        self.assertIs(res.run.status, RunStatus.COMPLETED, res.run.failure)
        sz.assert_not_called()
        pl.assert_not_called()
        self.assertGreater(res.summary["risk_vetoes"], 0)

    def test_kill_switch_unknown_or_active_vetoes_everything_with_rr8(self):
        for ks in (KillSwitchState.ACTIVE, KillSwitchState.UNKNOWN):
            res, _ = run_t2(dict(kill_switch=ks))
            self.assertEqual(len(res.orders), 0)
            self.assertTrue(all(any(c["check_id"] == "RR-8" and not c["passed"] for c in r["checks"]) for r in res.risk_decisions))

    def test_order_rate_limit_vetoes_excess_orders(self):
        res, _ = run_t2(dict(risk=risk_config(max_orders_per_window=2)))
        per_cycle: dict = {}
        for o in res.orders:
            per_cycle[o["decision_timestamp"]] = per_cycle.get(o["decision_timestamp"], 0) + 1
        self.assertTrue(per_cycle and max(per_cycle.values()) <= 2)  # limit is per (24h) window
        rr5 = [r for r in res.risk_decisions if r["verdict"] == "REJECT" and any(c["check_id"] == "RR-5" and not c["passed"] for c in r["checks"])]
        self.assertEqual(len(rr5), 1)

    def test_drawdown_halt_latches_and_blocks_new_buys(self):
        crash = TEST_START + timedelta(days=45)
        bars = [dataclasses.replace(b, open=b.open * 0.3, high=b.high * 0.3, low=b.low * 0.3, close=b.close * 0.3)
                if b.timestamp >= crash else b for b in weekly_bars()]
        res, _ = run_t2(bars=bars)
        self.assertIs(res.run.status, RunStatus.COMPLETED, res.run.failure)
        self.assertTrue(res.run.equity_curve[-1]["drawdown_halt_latched"])
        rr3 = [r for r in res.risk_decisions if any(c["check_id"] == "RR-3" and not c["passed"] for c in r["checks"])]
        self.assertTrue(rr3)
        halted_from = min(r["decision_timestamp"] for r in rr3)
        self.assertFalse([t for t in res.run.trades if t["side"] == "BUY" and t["decision_timestamp"] >= halted_from])

    def test_invalid_risk_config_fails_closed_at_run_level(self):
        res, _ = run_t2(dict(risk=risk_config(max_drawdown_fraction=Decimal("0"))))
        self.assertIs(res.run.status, RunStatus.FAILED)
        self.assertIs(res.run.failure.category, FailureCategory.INVALID_CONFIGURATION)
        self.assertEqual(len(res.orders), 0)

    def test_capital_and_schedule_mismatch_between_research_and_broker_fail(self):
        for over in (dict(broker=broker_config(initial_cash=Decimal("999"))),
                     dict(broker=broker_config(cost_schedule_version="india-equity-v1-unverified"))):
            res, _ = run_t2(over)
            self.assertIs(res.run.status, RunStatus.FAILED)
            self.assertIs(res.run.failure.category, FailureCategory.INVALID_CONFIGURATION)

    def test_kill_switch_must_be_an_explicit_state(self):
        res, _ = run_t2(dict(kill_switch="INACTIVE"))  # a bare string is not a KillSwitchState
        self.assertIs(res.run.status, RunStatus.FAILED)


class BrokerFaultTests(unittest.TestCase):
    def test_fault_injector_hook_marks_a_partially_filled_order_ambiguous_and_the_run_fails_closed(self):
        done = {"n": 0}

        def inject(broker, t):  # runs right after advance(): target an order that is only partly filled
            for bid, bo in broker._orders.items():
                if bo.order.state is OrderState.PARTIALLY_FILLED and not done["n"]:
                    done["n"] += 1
                    broker.inject_ambiguous_response(bid, "ack lost")

        res, _ = run_t2(dict(broker=broker_config(max_fill_fraction_per_bar=Decimal("0.4"))),
                        broker_fault_injector=inject)
        self.assertEqual(done["n"], 1)
        self.assertIs(res.run.status, RunStatus.FAILED)
        self.assertIs(res.run.failure.category, FailureCategory.RECONCILIATION_REQUIRED)
        self.assertTrue(any(o["final_state"] == "RECONCILIATION_REQUIRED" and 0 < o["filled_quantity"] < o["quantity"]
                            for o in res.orders))

    def test_ambiguous_order_before_fill_is_never_filled_and_run_fails(self):
        calls = {"n": 0}
        strat, b = tier2(0.3)
        orig = SimulatedBrokerAdapter.place_order

        def place_and_poison(self, session, request):
            st = orig(self, session, request)
            calls["n"] += 1
            if calls["n"] == 1 and not st.duplicate:
                self.inject_ambiguous_response(st.broker_order_id, "timeout")
            return self.get_order_status(session, st.broker_order_id)

        with mock.patch.object(SimulatedBrokerAdapter, "place_order", place_and_poison):
            res = PH().run(config(), strat, weekly_bars(), [universe()], pipeline(b))
        self.assertIs(res.run.status, RunStatus.FAILED)
        self.assertIs(res.run.failure.category, FailureCategory.RECONCILIATION_REQUIRED)
        poisoned = [o for o in res.orders if o["final_state"] == "RECONCILIATION_REQUIRED"]
        self.assertEqual(len(poisoned), 1)
        self.assertEqual(poisoned[0]["filled_quantity"], 0)
        self.assertTrue(any(d.terminal_state is TerminalState.RECONCILIATION_REQUIRED for d in res.run.decision_records))

    def test_broker_rejection_fails_run_by_default_or_continues_by_policy(self):
        u1 = [universe(ISINS[:1])]
        bars = weekly_bars(ISINS[:1])
        cyc = sorted(b.timestamp for b in bars if b.timestamp >= TEST_START)
        spike = cyc[1]
        bars = [dataclasses.replace(b, open=b.open * 1.5, high=b.high * 1.5, low=b.low * 1.5, close=b.close * 1.5)
                if b.timestamp == spike else b for b in bars]
        pc = lambda: pipeline(ContextFeatureBuilder(), sizing=sizing_config(cash_buffer=Decimal("0")),  # noqa: E731
                              risk=risk_config(max_position_fraction=Decimal("1.0")))
        strat = Tier1EqualWeightBuyHold()
        failed = PH().run(config(), strat, bars, u1, pc())
        self.assertIs(failed.run.status, RunStatus.FAILED)
        self.assertIs(failed.run.failure.category, FailureCategory.BROKER_REJECTED)
        cont = PH().run(config(order_rejection_policy=OrderRejectionPolicy.REJECT_AND_CONTINUE), strat, bars, u1, pc())
        self.assertIs(cont.run.status, RunStatus.COMPLETED, cont.run.failure)
        self.assertEqual(cont.run.metrics["rejected_orders"], 1)
        self.assertTrue(any(d.terminal_state is TerminalState.REJECTED_BY_BROKER for d in cont.run.decision_records))


class Tier1CompatibilityTests(unittest.TestCase):
    def test_tier1_still_runs_through_the_same_pipeline(self):
        res = PH().run(config(), Tier1EqualWeightBuyHold(), weekly_bars(), [universe()], pipeline(ContextFeatureBuilder()))
        self.assertIs(res.run.status, RunStatus.COMPLETED, res.run.failure)
        self.assertEqual(len(res.run.trades), 10)  # 1/10 equal-weight buys of every instrument
        self.assertTrue(all(t["strategy_version_id"] == "tier1_equal_weight_buy_hold_v1" for t in res.run.trades))
        self.assertTrue(all(r["ok"] for r in res.reconciliations))

    def test_tier1_and_tier2_are_independently_comparable_only_within_same_pipeline(self):
        a = PH().run(config(), Tier1EqualWeightBuyHold(), weekly_bars(), [universe()], pipeline(ContextFeatureBuilder()))
        b, _ = run_t2()
        self.assertNotEqual(a.run.strategy_version_id, b.run.strategy_version_id)
        self.assertNotEqual(a.run.experiment_id, b.run.experiment_id)


if __name__ == "__main__":
    unittest.main()
