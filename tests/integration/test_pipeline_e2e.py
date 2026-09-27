"""End-to-end integration test: adapter -> validation -> normalization ->
universe -> feature/context -> Tier-1 baseline -> CandidateTrade.
Slice 3 spec §19 (data compatibility)."""

import unittest
from datetime import UTC, datetime

from data.adapters.nse_csv_adapter import parse_bhavcopy_csv
from data.features.context_builder import build_feature_snapshots
from data.features.universe import make_permitted_universe
from data.normalization.normalizer import normalize_records
from domain.models.enums import Action
from intelligence.baseline.tier1_equal_weight import Tier1EqualWeightBuyHold

UTC = UTC

SAMPLE_CSV = """SYMBOL,ISIN,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,TIMESTAMP
RELIANCE,INE002A01018,100,110,95,105,10000,01-JAN-2026
TCS,INE467B01029,200,210,195,205,5000,01-JAN-2026
INFY,INE009A01021,300,310,295,305,7000,01-JAN-2026
"""


class TestPipelineEndToEnd(unittest.TestCase):
    def setUp(self):
        self.ingestion_time = datetime(2026, 1, 1, 16, 0, tzinfo=UTC)
        self.as_of = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        raw = parse_bhavcopy_csv(SAMPLE_CSV)
        self.result = normalize_records(raw, self.ingestion_time)
        self.strategy = Tier1EqualWeightBuyHold()

    def test_full_pipeline_produces_equal_weight_buys(self):
        instrument_ids = [m.instrument_id for m in self.result.accepted]
        universe = make_permitted_universe(instrument_ids, effective_from=self.ingestion_time)
        snaps = build_feature_snapshots(self.result.accepted, universe, self.as_of)
        cands = self.strategy.generate_candidate_trades(snaps, universe, None)

        self.assertEqual(len(cands), 3)
        self.assertTrue(all(c.action == Action.BUY for c in cands))
        for c in cands:
            self.assertAlmostEqual(c.size_hint, 1.0 / 3)
            self.assertEqual(c.confidence, 1.0)
            self.assertTrue(c.rationale)

    def test_full_pipeline_does_not_use_csv_specific_fields_downstream(self):
        """The baseline and feature builder must not reference NSE-CSV-specific
        column names — a change to the adapter's raw column names must not
        require any change downstream of normalize_records()."""
        import data.features.context_builder as ctx_mod
        import intelligence.baseline.tier1_equal_weight as strategy_mod

        for mod in (strategy_mod, ctx_mod):
            with open(mod.__file__) as f:
                source = f.read()
            for nse_specific in ("TOTTRDQTY", "SYMBOL", "TIMESTAMP", "bhavcopy"):
                self.assertNotIn(nse_specific, source)


if __name__ == "__main__":
    unittest.main()
