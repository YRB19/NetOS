"""Adversarial lookahead / contamination tests for the research harness (Slice 5, spec §9, §23).
All fixtures are SYNTHETIC."""

import ast
import unittest
from pathlib import Path
from unittest import mock

from data.features.universe import make_permitted_universe
from research.contamination import guards
from research.harness.config import EvaluationPeriod, two_way_split
from research.harness.failures import FailureCategory, ResearchRunFailure
from research.harness.replay import HistoricalReplay
from research.harness.runner import ResearchHarness
from tests.unit._research_helpers import (
    ISINS,
    ThresholdStrategy,
    bar,
    config,
    day,
    make_bars,
    universe,
)  # fmt: skip

REPO_ROOT = Path(__file__).resolve().parents[2]
H = ResearchHarness()


def spike_price(spike_from: int, after: float):
    return lambda i, d: after if d >= spike_from else 100.0 * (i + 1) * 0.5  # 50,100,150 early


class LookaheadTests(unittest.TestCase):
    """Future prices would make ThresholdStrategy(500) BUY on day 0 if they leaked."""

    def _run(self, spike: bool, days=14):
        price = spike_price(6, 1000.0) if spike else (lambda i, d: 100.0 * (i + 1) * 0.5)
        data = make_bars(days=days, price=price)
        strat = ThresholdStrategy(500.0)
        cfg = config(
            split=two_way_split(day(-30), day(-1), day(0), day(13)),
            order_rejection_policy=__import__("research.harness.config", fromlist=["x"]).OrderRejectionPolicy.REJECT_AND_CONTINUE,
        )  # fmt: skip
        return H.run(cfg, strat, data, [universe()]), strat

    def test_future_spike_does_not_change_earlier_decisions(self):
        with_spike, _ = self._run(True)
        flat, _ = self._run(False)
        self.assertTrue(with_spike.succeeded, with_spike.failure)
        early_a = [d for d in with_spike.decisions if d["decision_timestamp"] < day(6)]
        early_b = [d for d in flat.decisions if d["decision_timestamp"] < day(6)]
        self.assertEqual(len(early_a), len(early_b))
        self.assertTrue(early_a)
        for a, b in zip(early_a, early_b):
            self.assertEqual(a["action"], "HOLD")
            self.assertEqual(a["snapshot_id"], b["snapshot_id"])  # identical inputs at t
            self.assertEqual(a["candidate_id"], b["candidate_id"])
            self.assertEqual(a["reference_price"], b["reference_price"])
        # the spike only matters once it is in the PAST
        self.assertFalse([t for t in with_spike.trades if t["decision_timestamp"] < day(6)])
        self.assertTrue([t for t in with_spike.trades if t["decision_timestamp"] >= day(6)])
        self.assertEqual(flat.trades, ())

    def test_strategy_never_receives_a_future_snapshot(self):
        _, strat = self._run(True)
        for s in strat.seen_snapshots:
            for ref in s.source_refs:
                self.assertLessEqual(ref.timestamp, s.decision_timestamp)

    def test_leaking_replay_is_caught_and_fails_the_run(self):
        data = make_bars(days=10)
        with mock.patch.object(
            HistoricalReplay, "visible", lambda self, as_of: list(self._records)
        ):
            r = H.run(config(), ThresholdStrategy(500.0), data, [universe()])
        self.assertEqual(r.failure.category, FailureCategory.CONTAMINATION)
        self.assertEqual(r.status.value, "FAILED")
        self.assertIsNone(r.metrics)
        self.assertFalse(r.evaluation_run.contamination_check.passed)

    def test_data_after_window_end_cannot_affect_results(self):
        full = make_bars(days=14, price=lambda i, d: 100.0 * (i + 1) + (900 if d > 9 else d))
        trunc = [m for m in full if m.timestamp <= day(9)]
        a = H.run(config(), ThresholdStrategy(0.0), full, [universe()])
        b = H.run(config(), ThresholdStrategy(0.0), trunc, [universe()])
        self.assertNotEqual(a.data_snapshot_version, b.data_snapshot_version)
        self.assertEqual(a.metrics, b.metrics)
        self.assertEqual(a.equity_curve, b.equity_curve)
        strip = lambda ts: [{k: v for k, v in t.items() if k != "order_id"} for t in ts]  # noqa: E731
        self.assertEqual(strip(a.trades), strip(b.trades))  # order ids embed run identity

    def test_future_universe_membership_is_not_visible(self):
        u0 = universe(ISINS[:2])
        u1 = make_permitted_universe(list(ISINS), day(5))  # adds ISINS[2] on day 5
        strat = ThresholdStrategy(0.0)
        r = H.run(
            config(
                order_rejection_policy=__import__(
                    "research.harness.config", fromlist=["x"]
                ).OrderRejectionPolicy.REJECT_AND_CONTINUE
            ),
            strat,
            make_bars(),
            [u1, u0],
        )
        self.assertTrue(r.succeeded, r.failure)
        early = {s.instrument_id for s in strat.seen_snapshots if s.decision_timestamp < day(5)}
        self.assertNotIn(ISINS[2], early)
        self.assertIn(ISINS[2], {s.instrument_id for s in strat.seen_snapshots})

    def test_universe_effective_in_future_guard(self):
        with self.assertRaises(ResearchRunFailure) as c:
            guards.check_universe_not_from_future(universe(effective=5), day(2))
        self.assertEqual(c.exception.category, FailureCategory.CONTAMINATION)

    def test_universe_starting_after_first_cycle_fails_rather_than_backfilling(self):
        r = H.run(config(), ThresholdStrategy(0.0), make_bars(), [universe(effective=3)])
        self.assertEqual(r.failure.category, FailureCategory.MISSING_DATA)

    def test_future_observation_guard_direct(self):
        with self.assertRaises(ResearchRunFailure):
            guards.check_observations_not_from_future([bar(ISINS[0], 5, 10.0)], day(2), day(9))
        with self.assertRaises(ResearchRunFailure):
            guards.check_observations_not_from_future([bar(ISINS[0], 5, 10.0)], day(5), day(4))

    def test_snapshot_from_future_guard_direct(self):
        from data.features.context_builder import build_feature_snapshots

        s = build_feature_snapshots(
            [bar(ISINS[0], 0, 100.0)], universe(ISINS[:1]), day(0),
            market_data_snapshot_version="v", feature_set_id=config().feature_set_id,
        )[0]  # fmt: skip
        with self.assertRaises(ResearchRunFailure):
            guards.check_snapshots_not_from_future([s], day(-1))

    def test_same_visible_history_gives_same_snapshot_ids_across_datasets(self):
        a = make_bars(days=10)
        b = make_bars(days=10) + [bar(ISINS[0], 12, 5000.0)]
        sa, sb = ThresholdStrategy(0.0), ThresholdStrategy(0.0)
        cfg = config(
            order_rejection_policy=__import__(
                "research.harness.config", fromlist=["x"]
            ).OrderRejectionPolicy.REJECT_AND_CONTINUE
        )
        H.run(cfg, sa, a, [universe()])
        H.run(cfg, sb, b, [universe()])
        self.assertEqual(
            [s.snapshot_id for s in sa.seen_snapshots], [s.snapshot_id for s in sb.seen_snapshots]
        )


class SplitContaminationTests(unittest.TestCase):
    def test_overlapping_train_test_fails(self):
        for train_end, test_start in ((day(0), day(0)), (day(3), day(1))):
            try:
                split = two_way_split(day(-30), train_end, test_start, day(9))
            except ValueError:
                continue  # SplitSpec itself refuses reversed windows
            r = H.run(config(split=split), ThresholdStrategy(0.0), make_bars(), [universe()])
            self.assertEqual(r.failure.category, FailureCategory.CONTAMINATION)
            self.assertTrue(r.contamination_report is not None)

    def test_reversed_window_is_refused_by_split_contract(self):
        with self.assertRaises(ValueError):
            two_way_split(day(-30), day(3), day(1), day(9))

    def test_oos_claim_void_if_strategy_configured_on_test_data(self):
        r = H.run(
            config(strategy_configured_through=day(2)),
            ThresholdStrategy(0.0),
            make_bars(),
            [universe()],
        )
        self.assertEqual(r.failure.category, FailureCategory.CONTAMINATION)
        ok = H.run(
            config(strategy_configured_through=day(-1) - (day(0) - day(-1)) * 0),
            ThresholdStrategy(0.0),
            make_bars(),
            [universe()],
        )  # configured through train_end -> fine but may fail on cash
        self.assertNotEqual(getattr(ok.failure, "category", None), FailureCategory.CONTAMINATION)

    def test_undeclared_configuration_is_recorded_not_assumed(self):

        r = H.run(config(), ThresholdStrategy(500.0), make_bars(), [universe()])
        self.assertTrue(r.succeeded, r.failure)
        self.assertFalse(r.contamination_report["strategy_configuration_declared"])

    def test_in_sample_configured_after_train_end_fails(self):
        cfg = config(
            evaluation_period=EvaluationPeriod.IN_SAMPLE, strategy_configured_through=day(5)
        )
        data = [bar(i, d, 100.0) for d in range(-10, -1) for i in ISINS]
        data = [bar(i, d, 100.0) for d in range(-10, -1) for i in ISINS]
        r = H.run(cfg, ThresholdStrategy(500.0), data, [universe(effective=-10)])
        self.assertEqual(r.failure.category, FailureCategory.CONTAMINATION)


class ResearchHarnessSourceIsolationTests(unittest.TestCase):
    FORBIDDEN_PREFIXES = (
        "risk_execution", "governance", "data.adapters", "observability",
        "kiteconnect", "upstox", "fyers", "smartapi", "requests", "urllib", "http", "socket",
        "httpx", "aiohttp", "websocket", "ftplib", "smtplib", "subprocess", "boto3",
    )  # fmt: skip

    def _imports(self):
        for p in (REPO_ROOT / "research").rglob("*.py"):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    for a in n.names:
                        yield p, a.name
                elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                    yield p, n.module

    def test_research_has_no_broker_network_or_live_dependencies(self):
        bad = [
            (str(p.relative_to(REPO_ROOT)), m)
            for p, m in self._imports()
            if any(m == f or m.startswith(f + ".") for f in self.FORBIDDEN_PREFIXES)
        ]
        self.assertEqual(bad, [])

    def test_import_graph_checker_reports_zero_violations(self):
        from scripts.check_import_graph import check_import_graph

        self.assertEqual(check_import_graph(REPO_ROOT), [])

    def test_no_profitability_claims_in_research_code(self):
        banned = ("guaranteed", "production-ready", "live-ready", "validated alpha")
        for p in (REPO_ROOT / "research").rglob("*.py"):
            text = p.read_text(encoding="utf-8").lower()
            for b in banned:
                self.assertNotIn(b, text, f"{p}: {b}")


if __name__ == "__main__":
    unittest.main()
