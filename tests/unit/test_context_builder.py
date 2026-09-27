"""Feature/context formation tests. Slice 3 spec §16 (feature/context items 1-10)."""

import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

from data.features.context_builder import (
    build_feature_snapshots,
    compute_market_data_snapshot_version,
)
from data.features.feature_sets import TIER1_CONTEXT_FEATURE_SET_ID
from data.features.universe import make_permitted_universe
from domain.models.market_data import MarketData

UTC = UTC


def _md(instrument_id, ts, close=100.0, source="NSE_BHAVCOPY"):
    return MarketData(
        data_snapshot_version="test-snapshot",
        instrument_id=instrument_id,
        timestamp=ts,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1000,
        source=source,
        ingestion_time=ts + timedelta(hours=1),
    )


class TestFeatureSnapshotCreation(unittest.TestCase):
    def setUp(self):
        self.as_of = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        self.universe = make_permitted_universe(["A", "B"], effective_from=self.as_of)

    def test_1_snapshot_created_for_each_permitted_instrument(self):
        md = [_md("A", self.as_of), _md("B", self.as_of)]
        snaps = build_feature_snapshots(md, self.universe, self.as_of)
        self.assertEqual({s.instrument_id for s in snaps}, {"A", "B"})

    def test_2_snapshot_validation_rejects_naive_as_of(self):
        with self.assertRaises(ValueError):
            build_feature_snapshots([], self.universe, datetime(2026, 1, 1, 10, 0))

    def test_3_deterministic_output(self):
        md = [_md("A", self.as_of), _md("B", self.as_of)]
        snaps1 = build_feature_snapshots(md, self.universe, self.as_of)
        snaps2 = build_feature_snapshots(md, self.universe, self.as_of)
        self.assertEqual(
            [(s.snapshot_id, s.reference_price) for s in snaps1],
            [(s.snapshot_id, s.reference_price) for s in snaps2],
        )

    def test_4_exact_market_data_provenance(self):
        md = [_md("A", self.as_of, close=123.0)]
        universe = make_permitted_universe(["A"], effective_from=self.as_of)
        snaps = build_feature_snapshots(md, universe, self.as_of)
        self.assertEqual(len(snaps[0].source_refs), 1)
        self.assertEqual(snaps[0].source_refs[0].instrument_id, "A")
        self.assertEqual(snaps[0].reference_price, 123.0)

    def test_5_feature_set_version_present(self):
        md = [_md("A", self.as_of)]
        universe = make_permitted_universe(["A"], effective_from=self.as_of)
        snaps = build_feature_snapshots(md, universe, self.as_of)
        self.assertEqual(snaps[0].feature_set_id, TIER1_CONTEXT_FEATURE_SET_ID)

    def test_6_universe_version_present_and_correct(self):
        md = [_md("A", self.as_of), _md("B", self.as_of)]
        snaps = build_feature_snapshots(md, self.universe, self.as_of)
        for s in snaps:
            self.assertEqual(s.universe_version, self.universe.version)

    def test_7_permitted_universe_enforcement(self):
        md = [_md("A", self.as_of), _md("Z", self.as_of)]  # Z not permitted
        snaps = build_feature_snapshots(md, self.universe, self.as_of)
        instrument_ids = {s.instrument_id for s in snaps}
        self.assertNotIn("Z", instrument_ids)

    def test_8_missing_market_data_handled(self):
        md = [_md("A", self.as_of)]  # B has no data at all
        snaps = build_feature_snapshots(md, self.universe, self.as_of)
        b_snap = next(s for s in snaps if s.instrument_id == "B")
        self.assertFalse(b_snap.is_complete)
        self.assertIsNone(b_snap.reference_price)
        self.assertTrue(b_snap.is_permitted)

    def test_9_stale_data_handled(self):
        stale_ts = self.as_of - timedelta(days=30)
        md = [_md("A", stale_ts), _md("B", self.as_of)]
        snaps = build_feature_snapshots(
            md, self.universe, self.as_of, staleness_threshold=timedelta(days=5)
        )
        a_snap = next(s for s in snaps if s.instrument_id == "A")
        self.assertFalse(a_snap.is_complete)
        self.assertIsNone(a_snap.reference_price)

    def test_10_snapshot_is_immutable(self):
        md = [_md("A", self.as_of)]
        universe = make_permitted_universe(["A"], effective_from=self.as_of)
        snaps = build_feature_snapshots(md, universe, self.as_of)
        with self.assertRaises(FrozenInstanceError):
            snaps[0].reference_price = 999.0  # type: ignore

    def test_snapshot_version_changes_when_underlying_data_changes(self):
        md1 = [_md("A", self.as_of, close=100.0)]
        md2 = [_md("A", self.as_of, close=200.0)]
        v1 = compute_market_data_snapshot_version(md1)
        v2 = compute_market_data_snapshot_version(md2)
        self.assertNotEqual(v1, v2)

    def test_widened_instrument_ids_marks_non_permitted_correctly(self):
        md = [_md("A", self.as_of), _md("Z", self.as_of)]
        snaps = build_feature_snapshots(
            md, self.universe, self.as_of, instrument_ids=["A", "B", "Z"]
        )
        z_snap = next(s for s in snaps if s.instrument_id == "Z")
        self.assertFalse(z_snap.is_permitted)
        self.assertIsNotNone(z_snap.reference_price)  # data exists, just not permitted


if __name__ == "__main__":
    unittest.main()
