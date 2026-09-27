"""SF-1 (missing data) and SF-2 (stale data) fault-injection tests,
exercised through the feature/context layer and Tier-1 baseline.
Stage 3 §13, Slice 3 spec §16."""

import unittest
from datetime import UTC, datetime, timedelta

from data.features.context_builder import build_feature_snapshots
from data.features.universe import make_permitted_universe
from domain.models.enums import Action
from domain.models.market_data import MarketData
from intelligence.baseline.tier1_equal_weight import Tier1EqualWeightBuyHold

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


class TestSF1MissingData(unittest.TestCase):
    def test_withheld_field_routes_to_missing_path(self):
        as_of = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        universe = make_permitted_universe(["A", "B"], effective_from=as_of)
        md = [_md("A", as_of)]  # B's data withheld entirely
        snaps = build_feature_snapshots(md, universe, as_of)
        b = next(s for s in snaps if s.instrument_id == "B")
        self.assertFalse(b.is_complete)
        self.assertIsNone(b.reference_price)

        strategy = Tier1EqualWeightBuyHold()
        cands = strategy.generate_candidate_trades(snaps, universe, None)
        b_cand = next(c for c in cands if c.instrument_id == "B")
        self.assertEqual(b_cand.action, Action.HOLD)
        self.assertEqual(b_cand.confidence, 0.0)
        self.assertIn("missing or stale", b_cand.rationale)


class TestSF2StaleData(unittest.TestCase):
    def test_delayed_feed_treated_as_missing_not_current(self):
        as_of = datetime(2026, 1, 30, 10, 0, tzinfo=UTC)
        universe = make_permitted_universe(["A"], effective_from=as_of)
        stale_ts = as_of - timedelta(days=20)  # far older than the default 5-day threshold
        md = [_md("A", stale_ts, close=999.0)]
        snaps = build_feature_snapshots(md, universe, as_of, staleness_threshold=timedelta(days=5))
        a = snaps[0]
        self.assertFalse(a.is_complete)
        self.assertIsNone(a.reference_price)  # the stale 999.0 must NOT leak through as current

        strategy = Tier1EqualWeightBuyHold()
        cands = strategy.generate_candidate_trades(snaps, universe, None)
        self.assertEqual(cands[0].action, Action.HOLD)
        self.assertEqual(cands[0].confidence, 0.0)

    def test_fresh_data_within_threshold_is_used(self):
        as_of = datetime(2026, 1, 30, 10, 0, tzinfo=UTC)
        universe = make_permitted_universe(["A"], effective_from=as_of)
        fresh_ts = as_of - timedelta(days=2)
        md = [_md("A", fresh_ts, close=150.0)]
        snaps = build_feature_snapshots(md, universe, as_of, staleness_threshold=timedelta(days=5))
        self.assertTrue(snaps[0].is_complete)
        self.assertEqual(snaps[0].reference_price, 150.0)


if __name__ == "__main__":
    unittest.main()
