"""Tier-1 baseline strategy tests. Slice 3 spec §16 (18 items)."""

import unittest
from datetime import UTC, datetime, timedelta

from data.features.context_builder import build_feature_snapshots
from data.features.universe import make_permitted_universe
from domain.models.enums import Action
from domain.models.feature_snapshot import FeatureSnapshot
from domain.models.market_data import MarketData
from intelligence.baseline.tier1_equal_weight import STRATEGY_VERSION_ID, Tier1EqualWeightBuyHold

UTC = UTC


def _md(instrument_id, ts, close=100.0):
    return MarketData(
        data_snapshot_version="test-snapshot",
        instrument_id=instrument_id,
        timestamp=ts,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1000,
        source="NSE_BHAVCOPY",
        ingestion_time=ts + timedelta(hours=1),
    )


class TestTier1Baseline(unittest.TestCase):
    def setUp(self):
        self.as_of = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        self.strategy = Tier1EqualWeightBuyHold()

    def _universe_and_snapshots(self, instrument_ids, extra=None):
        universe = make_permitted_universe(instrument_ids, effective_from=self.as_of)
        md = [_md(i, self.as_of) for i in instrument_ids]
        target = list(instrument_ids) + list(extra or [])
        for i in extra or []:
            md.append(_md(i, self.as_of))
        snaps = build_feature_snapshots(md, universe, self.as_of, instrument_ids=target)
        return universe, snaps

    # 1. empty universe rejected
    def test_01_empty_universe_rejected(self):
        with self.assertRaises(ValueError):
            make_permitted_universe([], effective_from=self.as_of)

    # 2. single-instrument universe
    def test_02_single_instrument_universe(self):
        universe, snaps = self._universe_and_snapshots(["A"])
        cands = self.strategy.generate_candidate_trades(snaps, universe, None)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].size_hint, 1.0)

    # 3. two-instrument equal weighting
    def test_03_two_instrument_equal_weight(self):
        universe, snaps = self._universe_and_snapshots(["A", "B"])
        cands = self.strategy.generate_candidate_trades(snaps, universe, None)
        for c in cands:
            self.assertAlmostEqual(c.size_hint, 0.5)

    # 4. N-instrument equal weighting
    def test_04_n_instrument_equal_weight(self):
        ids = [f"I{n}" for n in range(7)]
        universe, snaps = self._universe_and_snapshots(ids)
        cands = self.strategy.generate_candidate_trades(snaps, universe, None)
        for c in cands:
            self.assertAlmostEqual(c.size_hint, 1.0 / 7)

    # 5. initial BUY generation
    def test_05_initial_buy_generation(self):
        universe, snaps = self._universe_and_snapshots(["A", "B"])
        cands = self.strategy.generate_candidate_trades(snaps, universe, None)
        self.assertTrue(all(c.action == Action.BUY for c in cands))

    # 6. repeated cycle with unchanged universe
    def test_06_repeated_cycle_unchanged_universe(self):
        universe, snaps = self._universe_and_snapshots(["A", "B"])
        cands1 = self.strategy.generate_candidate_trades(snaps, universe, None)
        cands2 = self.strategy.generate_candidate_trades(snaps, universe, universe)
        self.assertTrue(all(c.action == Action.BUY for c in cands1))
        self.assertTrue(all(c.action == Action.HOLD for c in cands2))

    # 7. unchanged universe does not trigger unnecessary BUY rebalancing
    def test_07_unchanged_universe_no_rebalance_buy(self):
        universe, snaps = self._universe_and_snapshots(["A", "B"])
        cands = self.strategy.generate_candidate_trades(snaps, universe, universe)
        self.assertFalse(any(c.action == Action.BUY for c in cands))

    # 8. universe addition
    def test_08_universe_addition(self):
        prev = make_permitted_universe(["A", "B", "C"], effective_from=self.as_of)
        universe, snaps = self._universe_and_snapshots(["A", "B", "C", "D"])
        cands = self.strategy.generate_candidate_trades(snaps, universe, prev)
        by_id = {c.instrument_id: c for c in cands}
        self.assertEqual(by_id["A"].action, Action.HOLD)
        self.assertEqual(by_id["B"].action, Action.HOLD)
        self.assertEqual(by_id["C"].action, Action.HOLD)
        self.assertEqual(by_id["D"].action, Action.BUY)
        # equal-weight target reflects the NEW universe size (4), for all instruments
        for c in cands:
            self.assertAlmostEqual(c.size_hint, 0.25)

    # 9. universe removal
    def test_09_universe_removal(self):
        prev = make_permitted_universe(["A", "B", "C"], effective_from=self.as_of)
        universe, snaps = self._universe_and_snapshots(["A", "B"], extra=["C"])
        cands = self.strategy.generate_candidate_trades(snaps, universe, prev)
        by_id = {c.instrument_id: c for c in cands}
        self.assertEqual(by_id["A"].action, Action.HOLD)
        self.assertEqual(by_id["B"].action, Action.HOLD)
        self.assertEqual(by_id["C"].action, Action.SELL)
        self.assertEqual(by_id["C"].size_hint, 0.0)

    # 10. deterministic output ordering
    def test_10_deterministic_output_ordering(self):
        universe, snaps = self._universe_and_snapshots(["Z", "A", "M"])
        cands = self.strategy.generate_candidate_trades(snaps, universe, None)
        ids = [c.instrument_id for c in cands]
        self.assertEqual(ids, sorted(ids))

    # 11. deterministic strategy version
    def test_11_deterministic_strategy_version(self):
        universe, snaps = self._universe_and_snapshots(["A"])
        cands = self.strategy.generate_candidate_trades(snaps, universe, None)
        self.assertEqual(cands[0].strategy_version_id, STRATEGY_VERSION_ID)
        self.assertEqual(self.strategy.strategy_version_id, STRATEGY_VERSION_ID)

    # 12. CandidateTrade provenance
    def test_12_candidate_trade_provenance(self):
        universe, snaps = self._universe_and_snapshots(["A"])
        cands = self.strategy.generate_candidate_trades(snaps, universe, None)
        self.assertEqual(cands[0].input_snapshot_id, snaps[0].snapshot_id)

    # 13. no executable quantity
    def test_13_no_executable_quantity(self):
        universe, snaps = self._universe_and_snapshots(["A", "B"])
        cands = self.strategy.generate_candidate_trades(snaps, universe, None)
        for c in cands:
            self.assertFalse(hasattr(c, "quantity"))
            self.assertLessEqual(c.size_hint, 1.0)  # a normalized fraction, never a raw share count

    # 14. no broker dependency
    def test_14_no_broker_dependency(self):
        import ast

        import intelligence.baseline.tier1_equal_weight as mod

        with open(mod.__file__) as f:
            tree = ast.parse(f.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in ("risk_execution", "risk_execution.broker"):
            self.assertFalse(
                any(m == forbidden or m.startswith(forbidden + ".") for m in imported),
                msg=f"forbidden import present: {forbidden}",
            )

    # 15. no network dependency
    def test_15_no_network_dependency(self):
        import ast

        import intelligence.baseline.tier1_equal_weight as mod

        with open(mod.__file__) as f:
            tree = ast.parse(f.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in ("requests", "socket", "urllib", "http", "aiohttp"):
            self.assertFalse(
                any(m == forbidden or m.startswith(forbidden + ".") for m in imported),
                msg=f"forbidden import present: {forbidden}",
            )

    # 16. HOLD behavior
    def test_16_hold_behavior_is_first_class(self):
        universe, snaps = self._universe_and_snapshots(["A", "B"])
        cands = self.strategy.generate_candidate_trades(snaps, universe, universe)
        self.assertTrue(all(isinstance(c.rationale, str) and c.rationale for c in cands))
        self.assertTrue(all(c.action == Action.HOLD for c in cands))

    # 17. invalid FeatureSnapshot rejection
    def test_17_invalid_feature_snapshot_rejected(self):
        universe = make_permitted_universe(["A"], effective_from=self.as_of)
        with self.assertRaises(ValueError):
            self.strategy.generate_candidate_trades(["not-a-snapshot"], universe, None)  # type: ignore

    # 18. invalid universe rejection
    def test_18_invalid_universe_rejected(self):
        with self.assertRaises(ValueError):
            self.strategy.generate_candidate_trades([], object(), None)  # type: ignore

    # Missing-data -> HOLD with confidence 0 (SF-1 wired through the strategy)
    def test_missing_data_produces_hold_zero_confidence(self):
        universe = make_permitted_universe(["A", "B"], effective_from=self.as_of)
        md = [_md("A", self.as_of)]  # B has no data
        snaps = build_feature_snapshots(md, universe, self.as_of)
        cands = self.strategy.generate_candidate_trades(snaps, universe, None)
        by_id = {c.instrument_id: c for c in cands}
        self.assertEqual(by_id["B"].action, Action.HOLD)
        self.assertEqual(by_id["B"].confidence, 0.0)
        self.assertIsNone(by_id["B"].size_hint)
        # A, being genuinely new with valid data, should still BUY
        self.assertEqual(by_id["A"].action, Action.BUY)

    def test_removed_instrument_without_snapshot_raises(self):
        prev = make_permitted_universe(["A", "B"], effective_from=self.as_of)
        universe = make_permitted_universe(["A"], effective_from=self.as_of)
        md = [_md("A", self.as_of)]
        snaps = build_feature_snapshots(md, universe, self.as_of)  # no snapshot for removed B
        with self.assertRaises(ValueError):
            self.strategy.generate_candidate_trades(snaps, universe, prev)

    def test_mismatched_decision_timestamps_rejected(self):
        universe = make_permitted_universe(["A", "B"], effective_from=self.as_of)
        other_ts = self.as_of + timedelta(days=1)
        snap_a = FeatureSnapshot(
            feature_values={},
            snapshot_id="s1",
            instrument_id="A",
            decision_timestamp=self.as_of,
            feature_set_version="tier1_context_v1",
            universe_version=universe.version,
            data_snapshot_version="v1",
            is_permitted=True,
            reference_price=100.0,
        )
        snap_b = FeatureSnapshot(
            feature_values={},
            snapshot_id="s2",
            instrument_id="B",
            decision_timestamp=other_ts,
            feature_set_version="tier1_context_v1",
            universe_version=universe.version,
            data_snapshot_version="v1",
            is_permitted=True,
            reference_price=100.0,
        )
        with self.assertRaises(ValueError):
            self.strategy.generate_candidate_trades([snap_a, snap_b], universe, None)


if __name__ == "__main__":
    unittest.main()
