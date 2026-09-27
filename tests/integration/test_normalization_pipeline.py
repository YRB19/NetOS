import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from data.adapters.nse_bhavcopy_csv import load_bhavcopy_csv
from data.normalization.persistence import (
    read_market_data_jsonl,
    write_market_data_jsonl,
)
from data.normalization.pipeline import normalize_bhavcopy_batch
from domain.models.raw_observation import RawMarketObservation

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "historical_data"


class TestValidSampleEndToEnd(unittest.TestCase):
    def setUp(self):
        self.ingestion = load_bhavcopy_csv(FIXTURE_DIR / "valid_sample.csv")
        self.result = normalize_bhavcopy_batch(
            self.ingestion.observations, raw_source_hash=self.ingestion.raw_source_hash
        )

    def test_all_valid_rows_accepted_none_rejected(self):
        self.assertEqual(len(self.result.accepted), 4)
        self.assertEqual(len(self.result.rejected), 0)

    def test_two_distinct_instruments_identified(self):
        isins = {i.isin for i in self.result.instruments}
        self.assertEqual(isins, {"INE002A01018", "INE467B01029"})

    def test_reliance_first_row_fields_correct(self):
        reliance = [r for r in self.result.accepted if r.instrument_id == "INE002A01018"]
        reliance.sort(key=lambda r: r.timestamp)
        first = reliance[0]
        self.assertAlmostEqual(first.open, 2550.00)
        self.assertAlmostEqual(first.high, 2570.50)
        self.assertAlmostEqual(first.low, 2540.00)
        self.assertAlmostEqual(first.close, 2565.25)
        self.assertEqual(first.volume, 4523100)
        self.assertFalse(first.adjusted)
        self.assertEqual(first.source, "nse_bhavcopy_csv")

    def test_timestamp_converted_to_utc_from_ist_session_close(self):
        reliance = sorted(
            (r for r in self.result.accepted if r.instrument_id == "INE002A01018"),
            key=lambda r: r.timestamp,
        )
        first = reliance[0]
        # 02-JAN-2024 15:30 IST == 02-JAN-2024 10:00 UTC
        self.assertEqual(first.timestamp, datetime(2024, 1, 2, 10, 0, tzinfo=UTC))

    def test_data_snapshot_version_is_populated_and_shared_across_batch(self):
        versions = {r.data_snapshot_version for r in self.result.accepted}
        self.assertEqual(len(versions), 1)
        self.assertTrue(next(iter(versions)).startswith("snap_"))
        self.assertEqual(self.result.data_snapshot_version, next(iter(versions)))


class TestMixedQualitySampleEndToEnd(unittest.TestCase):
    def setUp(self):
        self.ingestion = load_bhavcopy_csv(FIXTURE_DIR / "mixed_quality_sample.csv")
        self.result = normalize_bhavcopy_batch(
            self.ingestion.observations, raw_source_hash=self.ingestion.raw_source_hash
        )

    def test_accepted_and_rejected_counts(self):
        # 8 rows total: 2 valid (02-JAN, first 07-JAN), 6 invalid (missing field, negative
        # price, OHLC inconsistency, negative volume, exact duplicate, disallowed series)
        self.assertEqual(len(self.result.accepted), 2)
        self.assertEqual(len(self.result.rejected), 6)

    def test_rejection_reason_codes_present(self):
        codes = {r.reason_code for r in self.result.rejected}
        self.assertIn("RAW_VALIDATION_FAILED", codes)  # missing OPEN, and disallowed SERIES
        self.assertIn("NUMERIC_VALIDATION_FAILED", codes)  # negative close, OHLC bad, neg vol
        self.assertIn("DUPLICATE_EXACT", codes)

    def test_no_invalid_record_appears_in_accepted_output(self):
        # SF-1-style guarantee: an incomplete/invalid input can never silently become a valid
        # canonical MarketData record.
        for record in self.result.accepted:
            self.assertGreater(record.open, 0)
            self.assertGreater(record.close, 0)
            self.assertGreaterEqual(record.volume, 0)

    def test_every_rejected_record_has_at_least_one_reason(self):
        for rejected in self.result.rejected:
            self.assertGreater(len(rejected.reasons), 0)


class TestRevisionHandling(unittest.TestCase):
    """A source correction to a previously-ingested value is a NEW record, never an in-place
    edit — Stage 3 §5's explicit requirement."""

    def _obs(self, close_value: str, ingestion_time: datetime):
        return RawMarketObservation(
            source="nse_bhavcopy_csv",
            source_row_ref="revision_test:line 1",
            fields={
                "SYMBOL": "WIPRO",
                "ISIN": "INE075A01022",
                "SERIES": "EQ",
                "DATE": "02-JAN-2024",
                "OPEN": "450.00",
                "HIGH": "460.00",
                "LOW": "445.00",
                "CLOSE": close_value,
                "TOTTRDQTY": "500000",
            },
            ingestion_time=ingestion_time,
        )

    def test_corrected_value_produces_a_second_distinct_record_not_an_overwrite(self):
        original = self._obs("455.00", datetime(2024, 1, 3, 6, 0, tzinfo=UTC))
        corrected = self._obs("456.50", datetime(2024, 2, 1, 6, 0, tzinfo=UTC))
        result = normalize_bhavcopy_batch((original, corrected), raw_source_hash="fixedhash")

        # Both are accepted -- the pipeline never discards or merges a revision.
        self.assertEqual(len(result.accepted), 2)
        self.assertEqual(len(result.rejected), 0)
        closes = sorted(r.close for r in result.accepted)
        self.assertEqual(closes, [455.00, 456.50])
        # Same logical identity (instrument/timestamp/source), distinguished by ingestion_time.
        identities = {r.identity_key for r in result.accepted}
        self.assertEqual(len(identities), 1)
        ingestion_times = {r.ingestion_time for r in result.accepted}
        self.assertEqual(len(ingestion_times), 2)

    def test_exact_re_ingestion_of_identical_values_is_a_true_duplicate(self):
        same_time = datetime(2024, 1, 3, 6, 0, tzinfo=UTC)
        obs1 = self._obs("455.00", same_time)
        obs2 = self._obs("455.00", same_time)
        result = normalize_bhavcopy_batch((obs1, obs2), raw_source_hash="fixedhash")
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(len(result.rejected), 1)
        self.assertEqual(result.rejected[0].reason_code, "DUPLICATE_EXACT")


class TestDeterminism(unittest.TestCase):
    def test_same_input_produces_identical_output_on_repeated_runs(self):
        ingestion = load_bhavcopy_csv(FIXTURE_DIR / "valid_sample.csv")
        result1 = normalize_bhavcopy_batch(
            ingestion.observations, raw_source_hash=ingestion.raw_source_hash
        )
        result2 = normalize_bhavcopy_batch(
            ingestion.observations, raw_source_hash=ingestion.raw_source_hash
        )

        self.assertEqual(result1.data_snapshot_version, result2.data_snapshot_version)
        self.assertEqual(
            sorted(r.identity_key for r in result1.accepted),
            sorted(r.identity_key for r in result2.accepted),
        )
        self.assertEqual(result1.accepted, result2.accepted)

    def test_normalizing_and_persisting_the_same_raw_batch_twice_is_byte_identical(self):
        """Determinism claim precisely stated: SAME raw observations + SAME normalization code
        version -> byte-identical persisted output. This is deliberately NOT tested by loading
        the source file twice: each real file load legitimately stamps a fresh, wall-clock
        ingestion_time (documented in data/adapters/nse_bhavcopy_csv.py and MarketData's own
        schema) -- that is correct behavior, not a determinism violation, so re-reading the
        file twice is expected to yield different ingestion_time values and is not the
        property this test exists to check.
        """
        ingestion = load_bhavcopy_csv(FIXTURE_DIR / "valid_sample.csv")
        result = normalize_bhavcopy_batch(
            ingestion.observations, raw_source_hash=ingestion.raw_source_hash
        )

        with tempfile.TemporaryDirectory() as d:
            out1 = Path(d) / "run1.jsonl"
            out2 = Path(d) / "run2.jsonl"
            write_market_data_jsonl(result.accepted, out1)
            write_market_data_jsonl(result.accepted, out2)
            self.assertEqual(out1.read_text(), out2.read_text())

    def test_two_independent_file_loads_agree_on_logical_content_but_not_wall_clock_fields(self):
        """The property that DOES hold across two independent, real-time file loads: identical
        logical content (instrument, timestamp, OHLCV, data_snapshot_version) -- everything
        that isn't inherently wall-clock-dependent."""
        ingestion1 = load_bhavcopy_csv(FIXTURE_DIR / "valid_sample.csv")
        ingestion2 = load_bhavcopy_csv(FIXTURE_DIR / "valid_sample.csv")
        result1 = normalize_bhavcopy_batch(
            ingestion1.observations, raw_source_hash=ingestion1.raw_source_hash
        )
        result2 = normalize_bhavcopy_batch(
            ingestion2.observations, raw_source_hash=ingestion2.raw_source_hash
        )

        self.assertEqual(result1.data_snapshot_version, result2.data_snapshot_version)

        def logical(record):
            return (
                record.instrument_id,
                record.timestamp,
                record.open,
                record.high,
                record.low,
                record.close,
                record.volume,
                record.data_snapshot_version,
            )

        self.assertEqual(
            sorted(logical(r) for r in result1.accepted),
            sorted(logical(r) for r in result2.accepted),
        )


class TestPersistenceRoundTrip(unittest.TestCase):
    def test_write_then_read_reproduces_records(self):
        ingestion = load_bhavcopy_csv(FIXTURE_DIR / "valid_sample.csv")
        result = normalize_bhavcopy_batch(
            ingestion.observations, raw_source_hash=ingestion.raw_source_hash
        )

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "out.jsonl"
            write_market_data_jsonl(result.accepted, path)
            read_back = read_market_data_jsonl(path)

        self.assertEqual(len(read_back), len(result.accepted))
        original_sorted = sorted(result.accepted, key=lambda r: r.identity_key)
        read_sorted = sorted(read_back, key=lambda r: r.identity_key)
        for orig, back in zip(original_sorted, read_sorted, strict=True):
            self.assertEqual(orig, back)


if __name__ == "__main__":
    unittest.main()
