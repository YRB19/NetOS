"""Tests for the NSE CSV adapter and normalization pipeline (Slice 2 reconstruction)."""

import unittest
from datetime import UTC, datetime

from data.adapters.nse_csv_adapter import parse_bhavcopy_csv, parse_bhavcopy_rows
from data.normalization.normalizer import normalize_records
from data.validation.validators import is_stale, validate_raw_record

UTC = UTC

SAMPLE_CSV = """SYMBOL,ISIN,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,TIMESTAMP
RELIANCE,INE002A01018,100,110,95,105,10000,01-JAN-2026
TCS,INE467B01029,200,210,195,205,5000,01-JAN-2026
"""


class TestAdapter(unittest.TestCase):
    def test_parses_two_rows(self):
        rows = parse_bhavcopy_csv(SAMPLE_CSV)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["symbol"], "RELIANCE")
        self.assertEqual(rows[0]["isin"], "INE002A01018")
        self.assertEqual(rows[0]["source"], "NSE_BHAVCOPY")

    def test_parse_rows_variant(self):
        rows = parse_bhavcopy_rows(
            [
                {
                    "SYMBOL": "X",
                    "ISIN": "INE1",
                    "OPEN": "1",
                    "HIGH": "2",
                    "LOW": "0.5",
                    "CLOSE": "1.5",
                    "TOTTRDQTY": "10",
                    "TIMESTAMP": "01-JAN-2026",
                }
            ]
        )
        self.assertEqual(rows[0]["symbol"], "X")


class TestValidation(unittest.TestCase):
    def test_valid_record_no_errors(self):
        record = {
            "isin": "I1",
            "symbol": "X",
            "exchange": "NSE",
            "date": "01-JAN-2026",
            "open": "10",
            "high": "12",
            "low": "9",
            "close": "11",
            "volume": "100",
            "source": "S",
        }
        self.assertEqual(validate_raw_record(record), [])

    def test_missing_field_detected(self):
        record = {"isin": "I1", "symbol": "X"}
        errors = validate_raw_record(record)
        self.assertTrue(any("missing required field" in e for e in errors))

    def test_negative_volume_detected(self):
        record = {
            "isin": "I1",
            "symbol": "X",
            "exchange": "NSE",
            "date": "01-JAN-2026",
            "open": "10",
            "high": "12",
            "low": "9",
            "close": "11",
            "volume": "-1",
            "source": "S",
        }
        errors = validate_raw_record(record)
        self.assertTrue(any("volume" in e for e in errors))

    def test_is_stale(self):
        obs = datetime(2026, 1, 1, tzinfo=UTC)
        as_of = datetime(2026, 1, 10, tzinfo=UTC)
        from datetime import timedelta

        self.assertTrue(is_stale(obs, as_of, timedelta(days=5)))
        self.assertFalse(is_stale(obs, as_of, timedelta(days=15)))

    def test_is_stale_requires_tz_aware(self):
        with self.assertRaises(ValueError):
            from datetime import timedelta

            is_stale(datetime(2026, 1, 1), datetime(2026, 1, 2, tzinfo=UTC), timedelta(days=1))


class TestNormalization(unittest.TestCase):
    def test_valid_rows_normalize_to_market_data(self):
        rows = parse_bhavcopy_csv(SAMPLE_CSV)
        result = normalize_records(rows, ingestion_time=datetime(2026, 1, 1, 16, 0, tzinfo=UTC))
        self.assertEqual(len(result.accepted), 2)
        self.assertEqual(len(result.rejected), 0)
        self.assertEqual(len(result.instruments), 2)

    def test_invalid_row_rejected_not_dropped_silently(self):
        rows = parse_bhavcopy_csv(SAMPLE_CSV)
        rows.append(
            {
                "symbol": "BAD",
                "isin": "INEBAD",
                "exchange": "NSE",
                "source": "NSE_BHAVCOPY",
                "date": "01-JAN-2026",
                "open": "-5",
                "high": "1",
                "low": "1",
                "close": "1",
                "volume": "1",
            }
        )
        result = normalize_records(rows, ingestion_time=datetime(2026, 1, 1, 16, 0, tzinfo=UTC))
        self.assertEqual(len(result.accepted), 2)
        self.assertEqual(len(result.rejected), 1)
        raw, errors = result.rejected[0]
        self.assertEqual(raw["isin"], "INEBAD")
        self.assertTrue(errors)

    def test_ingestion_time_must_be_utc(self):
        rows = parse_bhavcopy_csv(SAMPLE_CSV)
        with self.assertRaises(ValueError):
            normalize_records(rows, ingestion_time=datetime(2026, 1, 1, 16, 0))

    def test_deterministic_normalization(self):
        rows = parse_bhavcopy_csv(SAMPLE_CSV)
        r1 = normalize_records(rows, ingestion_time=datetime(2026, 1, 1, 16, 0, tzinfo=UTC))
        r2 = normalize_records(rows, ingestion_time=datetime(2026, 1, 1, 16, 0, tzinfo=UTC))
        self.assertEqual(
            [(m.instrument_id, m.close, m.timestamp) for m in r1.accepted],
            [(m.instrument_id, m.close, m.timestamp) for m in r2.accepted],
        )


if __name__ == "__main__":
    unittest.main()
