"""End-to-end SYNTHETIC demonstration of the Slice 5 research harness (spec §34).

Everything here is synthetic plumbing verification. NOTHING in this file is evidence
of trading performance, validated alpha, or readiness for any live use.
"""

import json
import tempfile
import unittest
from decimal import Decimal

from data.features.context_builder import build_feature_snapshots, compute_market_data_snapshot_version
from domain.models.decision_record import DecisionRecord
from domain.models.enums import TerminalState
from domain.models.market_data import MarketData
from intelligence.baseline.tier1_equal_weight import Tier1EqualWeightBuyHold
from research.experiments.store import digest_of_run_dir, write_run
from research.harness.comparison import run_with_baseline
from research.harness.config import OrderRejectionPolicy
from research.harness.runner import ResearchHarness
from shared.costs import CostInputs, CostModel, TradeType, TransactionSide
from tests.unit._research_helpers import (
    ISINS, V1, V2, ThresholdStrategy, config, day, make_bars, universe,
)  # fmt: skip

H = ResearchHarness()


class SyntheticEndToEnd(unittest.TestCase):
    def setUp(self):
        self.data = make_bars()  # SYNTHETIC canonical MarketData
        self.uni = [universe()]
        self.result = H.run(config(), Tier1EqualWeightBuyHold(), self.data, self.uni)

    def test_full_chain_marketdata_to_result(self):
        r = self.result
        self.assertTrue(r.succeeded, r.failure)
        # canonical MarketData in -> FeatureSnapshot -> Tier-1 -> CandidateTrade
        day0 = [d for d in r.decisions if d["decision_timestamp"] == day(0)]
        self.assertEqual({d["action"] for d in day0}, {"BUY"})
        self.assertTrue(all(d["snapshot_id"] and d["candidate_id"] for d in day0))
        # -> simulated transaction -> CostEstimate -> portfolio update
        self.assertEqual(len(r.trades), 3)
        model = CostModel()
        for t in r.trades:
            expect = model.estimate(CostInputs(TransactionSide.BUY, TradeType.DELIVERY, t["quantity"], t["fill_price"], V2))
            self.assertEqual(t["cost_estimate"], expect)
            self.assertEqual(t["cost_estimate"].schedule_version, V2)
            ch = t["portfolio_change"]
            self.assertEqual(ch.cash_before - ch.cash_after, ch.gross_turnover + ch.cost)
        # -> research result
        self.assertEqual(r.metrics["number_of_transactions"], 3)
        self.assertEqual(r.cost_schedule_version, V2)

    def test_snapshot_matches_independent_rebuild(self):
        t0 = [d for d in self.result.decisions if d["decision_timestamp"] == day(0)][0]
        visible = [m for m in self.data if m.timestamp <= day(0)]
        snaps = build_feature_snapshots(
            visible, universe(), day(0),
            market_data_snapshot_version=compute_market_data_snapshot_version(visible),
            feature_set_id=config().feature_set_id,
        )  # fmt: skip
        self.assertIn(t0["snapshot_id"], {s.snapshot_id for s in snaps})

    def test_trade_provenance_answers_why(self):
        for t in self.result.trades:
            for k in ("decision_timestamp", "snapshot_id", "feature_set_version", "strategy_version_id",
                      "candidate_id", "execution_assumption", "cost_estimate", "portfolio_change",
                      "rationale"):  # fmt: skip
                self.assertIn(k, t)
            self.assertEqual(t["execution_assumption"], "NEXT_BAR_OPEN")
            self.assertIn("Tier-1", t["rationale"])

    def test_canonical_decision_records_for_fills(self):
        recs = self.result.decision_records
        self.assertEqual(len(recs), 3)
        for rec, tr in zip(recs, self.result.trades):
            self.assertIsInstance(rec, DecisionRecord)
            self.assertIs(rec.terminal_state, TerminalState.FILLED)
            self.assertEqual(rec.candidate_trade_id, tr["candidate_id"])
            self.assertEqual(rec.input_snapshot_id, tr["snapshot_id"])
            self.assertEqual(rec.autonomy_level, 0)
            self.assertTrue(rec.risk_rule_version_id.startswith("NOT_APPLICABLE"))

    def test_equity_reflects_costs_not_just_reports_them(self):
        r = self.result
        costs = r.metrics["total_transaction_costs"]
        self.assertGreater(costs, 0)
        last = r.equity_curve[-1]
        marks_value = last["market_value"]
        self.assertEqual(last["equity"], last["cash"] + marks_value)
        self.assertEqual(r.metrics["gross_pnl"] - r.metrics["net_pnl"], costs)

    def test_schedules_v1_v2_differ_only_by_costs(self):
        r1 = H.run(config(cost_schedule_version=V1), Tier1EqualWeightBuyHold(), self.data, self.uni)
        self.assertEqual(r1.cost_schedule_version, V1)
        self.assertEqual([t["quantity"] for t in r1.trades], [t["quantity"] for t in self.result.trades])
        self.assertNotEqual(r1.metrics["total_transaction_costs"], self.result.metrics["total_transaction_costs"])

    def test_baseline_comparison_uses_identical_inputs(self):
        cfg = config(order_rejection_policy=OrderRejectionPolicy.REJECT_AND_CONTINUE)
        s, b, cmp = run_with_baseline(H, cfg, ThresholdStrategy(0.0), Tier1EqualWeightBuyHold(), self.data, self.uni)
        self.assertIsNotNone(cmp)
        self.assertEqual(s.initial_capital, b.initial_capital)
        self.assertEqual(s.cost_schedule_version, b.cost_schedule_version)
        self.assertEqual(s.data_snapshot_version, b.data_snapshot_version)
        self.assertEqual(s.universe_schedule, b.universe_schedule)
        self.assertEqual((s.window_start, s.window_end), (b.window_start, b.window_end))
        self.assertEqual(cmp.shared_configuration["cost_schedule_version"], V2)

    def test_persisted_artifacts_reconstruct_the_run_and_are_reproducible(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            p1 = write_run(self.result, d1)
            again = H.run(config(), Tier1EqualWeightBuyHold(), make_bars(), [universe()])
            p2 = write_run(again, d2)
            self.assertEqual(digest_of_run_dir(p1), digest_of_run_dir(p2))
            rows = [json.loads(x) for x in (p1 / "trades.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["cost_estimate"]["schedule_version"], V2)
            ev = json.loads((p1 / "evaluation_run.json").read_text())
            self.assertFalse(ev["passed_pre_registered_criteria"])  # NOT ASSESSED, see result.json
            res = json.loads((p1 / "result.json").read_text())
            self.assertEqual(res["criteria_assessment"], "NOT_ASSESSED")
            self.assertEqual(res["status"], "COMPLETED")

    def test_synthetic_fixture_is_labelled_synthetic(self):
        self.assertTrue(all(m.source == "SYNTHETIC" for m in self.data))
        self.assertIn("SYNTHETIC", config().hypothesis)
        self.assertEqual(self.result.criteria_assessment, "NOT_ASSESSED")


if __name__ == "__main__":
    unittest.main()
