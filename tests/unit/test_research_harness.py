"""Unit tests for the Slice 5 research harness. All fixtures are SYNTHETIC."""

import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from intelligence.baseline.tier1_equal_weight import Tier1EqualWeightBuyHold
from research.experiments.store import (
    ArtifactConflict,
    digest_of_run_dir,
    list_runs,
    read_run_summary,
    write_run,
)
from research.harness.comparison import ComparisonError, compare_runs, run_with_baseline
from research.harness.config import EvaluationPeriod, OrderRejectionPolicy
from research.harness.execution import translate_candidate
from research.harness.failures import FailureCategory, ResearchRunFailure, RunStatus
from research.harness.metrics import compute_metrics
from research.harness.portfolio import ResearchPortfolio
from research.harness.replay import HistoricalReplay
from research.harness.runner import ResearchHarness
from tests.unit._research_helpers import (
    BASE, ISINS, V1, V2, ThresholdStrategy, bar, config, day, make_bars, universe,
)  # fmt: skip

H = ResearchHarness()
T1 = Tier1EqualWeightBuyHold


def run(cfg=None, strat=None, data=None, uni=None, **kw):
    return H.run(cfg or config(), strat or T1(), data or make_bars(), uni or [universe()], **kw)


class IdentityTests(unittest.TestCase):
    def test_same_config_same_identity_regardless_of_created_at(self):
        a = run(created_at=day(100))
        b = run(created_at=day(200))
        self.assertEqual((a.run_id, a.experiment_id), (b.run_id, b.experiment_id))
        self.assertEqual(a.deterministic_summary(), b.deterministic_summary())

    def test_identity_changes_with_each_meaningful_input(self):
        base = run()
        variants = {
            "capital": run(config(initial_capital="2000000")),
            "schedule": run(config(cost_schedule_version=V1)),
            "strategy": run(strat=ThresholdStrategy(0.0)),
            "data": run(data=make_bars(days=9)),
            "universe": run(uni=[universe(ISINS[:2])]),
            "window": run(config(split=config().split.__class__(
                day(-30), day(-1), day(-1), day(-1), day(0), day(8)))),
        }  # fmt: skip
        for name, r in variants.items():
            self.assertNotEqual(r.experiment_id, base.experiment_id, name)
        ids = {r.experiment_id for r in variants.values()} | {base.experiment_id}
        self.assertEqual(len(ids), len(variants) + 1)

    def test_run_id_is_not_random(self):
        self.assertTrue(run().run_id.startswith("run_"))
        self.assertEqual(run().run_id, run().run_id)

    def test_uses_existing_domain_contracts(self):
        from domain.models.research_artifacts import EvaluationRun, Experiment

        r = run()
        self.assertIsInstance(r.experiment, Experiment)
        self.assertIsInstance(r.evaluation_run, EvaluationRun)
        self.assertEqual(r.experiment.experiment_id, r.experiment_id)
        self.assertEqual(r.evaluation_run.run_id, r.run_id)
        self.assertEqual(r.criteria_assessment, "NOT_ASSESSED")


class PortfolioTests(unittest.TestCase):
    def test_costs_reduce_cash_and_equity(self):
        p = ResearchPortfolio(Decimal("10000"))
        p.buy("X", 10, Decimal("100"), Decimal("5"))
        self.assertEqual(p.cash, Decimal("8995"))
        self.assertEqual(p.equity({"X": Decimal("100")}), Decimal("9995"))  # cost visible in equity
        self.assertEqual(p.cumulative_costs, Decimal("5"))

    def test_sell_realizes_pnl_and_pays_costs(self):
        p = ResearchPortfolio(Decimal("10000"))
        p.buy("X", 10, Decimal("100"), Decimal("0"))
        ch = p.sell("X", 4, Decimal("110"), Decimal("2"))
        self.assertEqual(ch.realized_pnl_gross, Decimal("40"))
        self.assertEqual(p.cash, Decimal("9438"))
        self.assertEqual(p.quantity("X"), 6)

    def test_insufficient_cash_fails_closed(self):
        p = ResearchPortfolio(Decimal("1000"))
        with self.assertRaises(ResearchRunFailure) as c:
            p.buy("X", 10, Decimal("100"), Decimal("1"))  # needs 1001
        self.assertEqual(c.exception.category, FailureCategory.INSUFFICIENT_CASH)
        self.assertEqual(p.cash, Decimal("1000"))

    def test_costs_alone_can_make_buy_unaffordable(self):
        p = ResearchPortfolio(Decimal("1000"))
        with self.assertRaises(ResearchRunFailure):
            p.buy("X", 10, Decimal("100"), Decimal("0.01"))

    def test_overselling_rejected(self):
        p = ResearchPortfolio(Decimal("1000"))
        p.buy("X", 2, Decimal("10"), Decimal("0"))
        with self.assertRaises(ResearchRunFailure) as c:
            p.sell("X", 3, Decimal("10"), Decimal("0"))
        self.assertEqual(c.exception.category, FailureCategory.INSUFFICIENT_POSITION)
        self.assertEqual(p.quantity("X"), 2)

    def test_non_integer_and_bad_inputs_rejected(self):
        p = ResearchPortfolio(Decimal("1000"))
        for q, pr, co in [(1.5, Decimal("1"), Decimal("0")), (0, Decimal("1"), Decimal("0")),
                          (1, Decimal("-1"), Decimal("0")), (1, Decimal("1"), Decimal("-1")),
                          (True, Decimal("1"), Decimal("0"))]:  # fmt: skip
            with self.assertRaises(ResearchRunFailure):
                p.buy("X", q, pr, co)

    def test_invalid_initial_capital(self):
        for bad in (Decimal("0"), Decimal("-5"), 100, Decimal("NaN")):
            with self.assertRaises(ResearchRunFailure):
                ResearchPortfolio(bad)

    def test_missing_mark_raises(self):
        p = ResearchPortfolio(Decimal("1000"))
        p.buy("X", 1, Decimal("10"), Decimal("0"))
        with self.assertRaises(ResearchRunFailure):
            p.equity({})


class TranslationTests(unittest.TestCase):
    def _snap(self, price=100.0):
        from data.features.context_builder import build_feature_snapshots
        from tests.unit._research_helpers import universe as u

        bars = [bar(ISINS[0], 0, price)]
        return build_feature_snapshots(
            bars, u(ISINS[:1]), day(0), market_data_snapshot_version="v",
            feature_set_id=config().feature_set_id,
        )[0]  # fmt: skip

    def test_integer_floor_and_residual_cash(self):
        from tests.unit._research_helpers import _cand
        from domain.models.enums import Action

        s = self._snap(333.0)
        c = _cand(s, Action.BUY, 1.0, "v")
        t = translate_candidate(c, s, 0, Decimal("100000"), Decimal("0"))
        self.assertEqual(t.quantity, 300)  # floor(100000/333) = 300; 100 rupees+ stays cash
        self.assertIsInstance(t.quantity, int)

    def test_buffer_reduces_quantity(self):
        from tests.unit._research_helpers import _cand
        from domain.models.enums import Action

        s = self._snap(100.0)
        c = _cand(s, Action.BUY, 1.0, "v")
        self.assertEqual(translate_candidate(c, s, 0, Decimal("10000"), Decimal("0.01")).quantity, 99)

    def test_hold_and_full_exit_and_nothing_held(self):
        from tests.unit._research_helpers import _cand
        from domain.models.enums import Action

        s = self._snap()
        self.assertEqual(translate_candidate(_cand(s, Action.HOLD, None, "v"), s, 5,
                                             Decimal("1000"), Decimal("0")).outcome, "HOLD")  # fmt: skip
        sell = _cand(s, Action.SELL, 0.0, "v")
        self.assertEqual(translate_candidate(sell, s, 7, Decimal("1000"), Decimal("0")).quantity, 7)
        self.assertEqual(translate_candidate(sell, s, 0, Decimal("1000"), Decimal("0")).outcome, "NO_TRADE")

    def test_buy_when_target_already_met_is_no_trade(self):
        from tests.unit._research_helpers import _cand
        from domain.models.enums import Action

        s = self._snap(100.0)
        c = _cand(s, Action.BUY, 0.5, "v")
        self.assertEqual(translate_candidate(c, s, 50, Decimal("10000"), Decimal("0")).outcome, "NO_TRADE")


class ReplayTests(unittest.TestCase):
    def test_visible_excludes_future(self):
        r = HistoricalReplay(make_bars())
        self.assertTrue(all(x.timestamp <= day(3) for x in r.visible(day(3))))
        self.assertEqual(len(r.visible(day(3))), 4 * 3)

    def test_chronological_order_is_deterministic(self):
        data = make_bars()
        a = HistoricalReplay(list(reversed(data))).visible(day(9))
        b = HistoricalReplay(data).visible(day(9))
        self.assertEqual(a, b)

    def test_non_trading_day_has_no_cycle(self):
        data = [d for d in make_bars() if d.timestamp.day not in (3, 4)]  # day(2), day(3) gap
        ts = HistoricalReplay(data).decision_timestamps(day(0), day(9))
        self.assertNotIn(day(2), ts)
        self.assertEqual(len(ts), 8)

    def test_duplicate_timestamp_fails_even_across_sources(self):
        data = make_bars() + [bar(ISINS[0], 2, 999.0, source="OTHER")]
        with self.assertRaises(ResearchRunFailure) as c:
            HistoricalReplay(data)
        self.assertEqual(c.exception.category, FailureCategory.DUPLICATE_DATA)

    def test_non_marketdata_rejected(self):
        with self.assertRaises(ResearchRunFailure) as c:
            HistoricalReplay(make_bars() + [{"close": 1}])
        self.assertEqual(c.exception.category, FailureCategory.INVALID_DATA)

    def test_empty_and_missing_instruments(self):
        with self.assertRaises(ResearchRunFailure):
            HistoricalReplay([])
        r = HistoricalReplay(make_bars(ISINS[:2]))
        with self.assertRaises(ResearchRunFailure) as c:
            r.require_instruments(ISINS)
        self.assertEqual(c.exception.category, FailureCategory.MISSING_DATA)


class TradingAccountingTests(unittest.TestCase):
    def test_tier1_fills_at_next_open_with_costs_in_cash(self):
        r = run()
        self.assertTrue(r.succeeded, r.failure)
        self.assertEqual(len(r.trades), 3)
        for t in r.trades:
            self.assertEqual(t["fill_timestamp"], day(1))  # next bar, not the decision bar
            self.assertEqual(t["decision_timestamp"], day(0))
            i = ISINS.index(t["instrument_id"])
            self.assertEqual(t["fill_price"], Decimal(str(100.0 * (i + 1) + 1 - 0.5)))
        spent = sum(t["fill_price"] * t["quantity"] + t["cost_estimate"].total_cost for t in r.trades)
        self.assertEqual(r.equity_curve[-1]["cash"], Decimal("1000000") - spent)
        self.assertEqual(r.metrics["total_transaction_costs"],
                         sum(t["cost_estimate"].total_cost for t in r.trades).quantize(Decimal("0.01")))  # fmt: skip

    def test_gross_equals_net_plus_costs(self):
        m = run().metrics
        self.assertEqual(m["gross_pnl"], m["net_pnl"] + m["total_transaction_costs"])
        self.assertEqual(m["final_equity"], m["initial_capital"] + m["net_pnl"])

    def test_metrics_basis_is_net(self):
        self.assertIn("NET_OF_TRANSACTION_COSTS", run().metrics["basis"])

    def test_integer_quantities_only(self):
        for t in run().trades:
            self.assertIsInstance(t["quantity"], int)

    def test_final_cycle_orders_are_unexecuted_not_failures(self):
        data = make_bars(days=1)
        cfg = config(split=config().split.__class__(day(-30), day(-1), day(-1), day(-1), day(0), day(0)))
        r = run(cfg, data=data)
        self.assertTrue(r.succeeded, r.failure)
        self.assertEqual(len(r.trades), 0)
        self.assertEqual(r.metrics["unexecuted_orders"], 3)
        self.assertEqual(r.metrics["final_equity"], Decimal("1000000.00"))

    def test_universe_removal_sells_and_realizes_pnl(self):
        u0, u1 = universe(), universe(ISINS[:2], effective=5)
        r = run(uni=[u0, u1])
        self.assertTrue(r.succeeded, r.failure)
        sells = [t for t in r.trades if t["side"] == "SELL"]
        self.assertEqual([t["instrument_id"] for t in sells], [ISINS[2]])
        self.assertEqual(sells[0]["decision_timestamp"], day(5))
        self.assertEqual(sells[0]["fill_timestamp"], day(6))
        self.assertGreater(r.metrics["realized_pnl_gross"], 0)
        self.assertEqual([p["instrument_id"] for p in r.final_positions], list(ISINS[:2]))

    def test_carry_forward_marks_opt_in(self):
        data = make_bars(skip={(ISINS[0], 4)})
        self.assertEqual(run(data=data).failure.category, FailureCategory.MISSING_DATA)
        r = run(config(carry_forward_marks=True), data=data)
        self.assertTrue(r.succeeded, r.failure)
        self.assertIn(ISINS[0], r.equity_curve[4]["carried_marks"])


class ScheduleSelectionTests(unittest.TestCase):
    def test_v1_and_v2_both_selectable_and_recorded(self):
        r1, r2 = run(config(cost_schedule_version=V1)), run(config(cost_schedule_version=V2))
        self.assertEqual((r1.cost_schedule_version, r2.cost_schedule_version), (V1, V2))
        self.assertTrue(r1.succeeded and r2.succeeded)
        self.assertNotEqual(r1.metrics["total_transaction_costs"], r2.metrics["total_transaction_costs"])
        self.assertEqual(r1.config["cost_schedule_version"], V1)

    def test_unknown_schedule_fails_with_artifact(self):
        r = run(config(cost_schedule_version="india-equity-v99"))
        self.assertEqual(r.status, RunStatus.FAILED)
        self.assertEqual(r.failure.category, FailureCategory.INVALID_CONFIGURATION)

    def test_future_schedule_needs_acknowledgement(self):
        early = config().split.__class__
        split = early(day(-400), day(-200), day(-199), day(-199), day(-198), day(-190))
        data = []
        from datetime import timedelta as td

        for d in range(-198, -189):
            for i, isin in enumerate(ISINS):
                data.append(bar(isin, d, 100.0 * (i + 1)))
        cfg = config(split=split)  # v2 is effective 2026-03-01; window is in 2025
        u = [universe(effective=-400)]
        r = run(cfg, data=data, uni=u)
        self.assertEqual(r.failure.category, FailureCategory.CONTAMINATION)
        ok = run(config(split=split, acknowledge_future_cost_schedule=True), data=data, uni=u)
        self.assertTrue(ok.succeeded, ok.failure)
        self.assertTrue(ok.contamination_report["future_cost_schedule_acknowledged"])
        v1 = run(config(split=split, cost_schedule_version=V1), data=data, uni=u)
        self.assertTrue(v1.succeeded, v1.failure)  # v1 has no effective date


class ComparisonTests(unittest.TestCase):
    def test_apples_to_apples(self):
        s, b, cmp = run_with_baseline(
            H, config(order_rejection_policy=OrderRejectionPolicy.REJECT_AND_CONTINUE),
            ThresholdStrategy(0.0), T1(), make_bars(), [universe()])
        self.assertIsNotNone(cmp)
        self.assertEqual(s.comparison_fingerprint, b.comparison_fingerprint)
        self.assertEqual(cmp.differences["final_equity"], s.metrics["final_equity"] - b.metrics["final_equity"])
        self.assertIn("NET_OF_TRANSACTION_COSTS", cmp.basis)
        self.assertEqual(cmp.to_dict()["statistical_significance"], "NOT_ASSESSED")
        self.assertEqual(s.baseline_strategy_version_ids, (T1.strategy_version_id,))

    def test_mismatched_capital_schedule_or_data_refused(self):
        a, b = run(), run(config(initial_capital="500000"))
        with self.assertRaises(ComparisonError):
            compare_runs(a, b)
        with self.assertRaises(ComparisonError):
            compare_runs(a, run(config(cost_schedule_version=V1)))
        with self.assertRaises(ComparisonError):
            compare_runs(a, run(data=make_bars(days=9)))

    def test_failed_run_not_comparable(self):
        bad = run(config(initial_capital="0"))
        with self.assertRaises(ComparisonError):
            compare_runs(run(), bad)

    def test_strategy_text_does_not_break_comparability(self):
        a = run(config(hypothesis="one hypothesis"))
        b = run(config(hypothesis="another hypothesis"))
        self.assertEqual(a.comparison_fingerprint, b.comparison_fingerprint)


class PersistenceTests(unittest.TestCase):
    def test_round_trip_and_reproducible_bytes(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            a = write_run(run(created_at=day(50)), d1)
            b = write_run(run(created_at=day(99)), d2)
            self.assertEqual(digest_of_run_dir(a), digest_of_run_dir(b))
            for name in ("experiment.json", "result.json", "trades.jsonl", "decisions.jsonl",
                         "equity_curve.jsonl", "decision_records.jsonl", "evaluation_run.json"):  # fmt: skip
                self.assertEqual((a / name).read_bytes(), (b / name).read_bytes(), name)
            self.assertNotEqual((a / "meta.json").read_bytes(), (b / "meta.json").read_bytes())
            self.assertEqual(list_runs(d1), [a.name])
            self.assertEqual(read_run_summary(d1, a.name)["status"], "COMPLETED")

    def test_failed_run_persisted_with_failure_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(config(initial_capital="-1"))
            p = write_run(r, d)
            self.assertTrue((p / "failure.json").exists())
            summary = read_run_summary(d, r.run_id)
            self.assertEqual(summary["status"], "FAILED")
            self.assertEqual(summary["failure"]["category"], "INVALID_CONFIGURATION")
            self.assertIsNone(summary["metrics"])

    def test_identical_rewrite_ok_but_conflicting_overwrite_refused(self):
        with tempfile.TemporaryDirectory() as d:
            r = run()
            write_run(r, d)
            write_run(r, d)  # idempotent
            from dataclasses import replace

            tampered = replace(r, metrics={**r.metrics, "net_pnl": Decimal("1")})
            with self.assertRaises(ArtifactConflict):
                write_run(tampered, d)

    def test_artifacts_record_required_fields(self):
        import json

        with tempfile.TemporaryDirectory() as d:
            p = write_run(run(), d)
            e = json.loads((p / "experiment.json").read_text())
            for k in ("strategy_version_id", "feature_set_version", "cost_schedule_version",
                      "data_snapshot_version", "universe_schedule", "window_start", "window_end",
                      "initial_capital", "config"):  # fmt: skip
                self.assertIn(k, e)
            self.assertEqual(e["cost_schedule_version"], V2)


class MetricsTests(unittest.TestCase):
    def test_compute_metrics_identity(self):
        p = ResearchPortfolio(Decimal("1000"))
        p.buy("X", 5, Decimal("100"), Decimal("3"))
        m = compute_metrics(p, {"X": Decimal("110")}, rejected_orders=0, unexecuted_orders=0, decision_cycles=1)
        self.assertEqual(m["net_pnl"], Decimal("47.00"))
        self.assertEqual(m["gross_pnl"], Decimal("50.00"))
        self.assertEqual(m["number_of_transactions"], 1)


if __name__ == "__main__":
    unittest.main()
