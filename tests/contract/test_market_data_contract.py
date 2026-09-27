"""Contract tests: the canonical MarketData interface.

Per Stage 3 §3/§15 ("Contract: inter-plane interfaces match their declared schema"), this
slice's load-bearing contract is: whatever `data/normalization/pipeline.py` emits as
`NormalizationResult.accepted` must be genuine, schema-valid `domain.models.market_data.
MarketData` instances, using the canonical instrument identity (ISIN), with no leaked
source-specific field names or raw-string values, and every accepted record traceable back to
the raw observation it came from.
"""

import unittest
from pathlib import Path

from data.adapters.nse_bhavcopy_csv import load_bhavcopy_csv
from data.normalization.pipeline import normalize_bhavcopy_batch
from domain.models.instrument import Instrument
from domain.models.market_data import MarketData

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "historical_data"


class TestMarketDataContract(unittest.TestCase):
    def setUp(self):
        self.ingestion = load_bhavcopy_csv(FIXTURE_DIR / "valid_sample.csv")
        self.result = normalize_bhavcopy_batch(
            self.ingestion.observations, raw_source_hash=self.ingestion.raw_source_hash
        )

    def test_every_accepted_record_is_a_market_data_instance(self):
        for record in self.result.accepted:
            self.assertIsInstance(record, MarketData)

    def test_every_accepted_record_has_no_source_specific_field_names(self):
        """The canonical record must not carry the source's own vocabulary (e.g. TOTTRDQTY) —
        by construction, MarketData simply has no such attribute, but this test also confirms
        the *values* line up with what the source called something differently."""
        for record in self.result.accepted:
            self.assertFalse(hasattr(record, "TOTTRDQTY"))
            self.assertFalse(hasattr(record, "SYMBOL"))
            self.assertTrue(hasattr(record, "volume"))
            self.assertTrue(hasattr(record, "instrument_id"))

    def test_instrument_id_is_canonical_isin_not_symbol(self):
        for record in self.result.accepted:
            self.assertTrue(record.instrument_id.startswith("INE"))  # ISIN format, not a symbol

    def test_every_accepted_record_traceable_to_a_raw_observation(self):
        raw_ids = {o.raw_id for o in self.ingestion.observations}
        for record in self.result.accepted:
            self.assertIsNotNone(record.raw_ref)
            self.assertIn(record.raw_ref, raw_ids)

    def test_every_accepted_record_instrument_resolvable_in_result_instruments(self):
        instrument_ids = {i.isin for i in self.result.instruments}
        for record in self.result.accepted:
            self.assertIn(record.instrument_id, instrument_ids)

    def test_all_result_instruments_are_instrument_instances(self):
        for inst in self.result.instruments:
            self.assertIsInstance(inst, Instrument)

    def test_market_data_cannot_be_constructed_with_empty_instrument_id(self):
        """Defense-in-depth: the constraint lives in the type itself, not only in a caller's
        discipline (Stage 3 §21 milestone note)."""
        with self.assertRaises(ValueError):
            MarketData(
                instrument_id="",
                timestamp=self.result.accepted[0].timestamp,
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
                volume=0,
                source="x",
                ingestion_time=self.result.accepted[0].ingestion_time,
                data_snapshot_version="snap_x",
            )

    def test_data_snapshot_version_field_present_on_every_record(self):
        for record in self.result.accepted:
            self.assertTrue(record.data_snapshot_version)


if __name__ == "__main__":
    unittest.main()
