"""SF-1 (missing data) fault-injection test.

Stage 1 SF-1: "System must not act on an instrument for which required data is missing; must
log the gap and either hold or fall back to a defined degraded mode." At the historical
data-ingestion layer (this slice), the applicable form of this requirement is: an observation
missing a required field must be rejected before it can become a canonical MarketData record —
it must never be silently coerced into a "valid-looking" record with a fabricated or defaulted
value.
"""

import unittest
from datetime import UTC, datetime

from data.normalization.pipeline import normalize_bhavcopy_batch
from domain.models.raw_observation import RawMarketObservation

_BASE_FIELDS = {
    "SYMBOL": "HDFCBANK",
    "ISIN": "INE040A01034",
    "SERIES": "EQ",
    "DATE": "02-JAN-2024",
    "OPEN": "1600.00",
    "HIGH": "1615.00",
    "LOW": "1590.00",
    "CLOSE": "1605.00",
    "TOTTRDQTY": "3000000",
}


def _obs_missing(field_to_remove: str) -> RawMarketObservation:
    fields = dict(_BASE_FIELDS)
    del fields[field_to_remove]
    return RawMarketObservation(
        source="nse_bhavcopy_csv",
        source_row_ref="sf1_test:line 1",
        fields=fields,
        ingestion_time=datetime(2024, 1, 2, 12, 0, tzinfo=UTC),
    )


class TestSF1MissingData(unittest.TestCase):
    def test_missing_close_never_becomes_valid_market_data(self):
        obs = _obs_missing("CLOSE")
        result = normalize_bhavcopy_batch((obs,), raw_source_hash="sf1hash")
        self.assertEqual(len(result.accepted), 0)
        self.assertEqual(len(result.rejected), 1)
        self.assertEqual(result.rejected[0].reason_code, "RAW_VALIDATION_FAILED")
        self.assertTrue(any("CLOSE" in r for r in result.rejected[0].reasons))

    def test_missing_isin_never_becomes_valid_market_data(self):
        obs = _obs_missing("ISIN")
        result = normalize_bhavcopy_batch((obs,), raw_source_hash="sf1hash")
        self.assertEqual(len(result.accepted), 0)
        self.assertEqual(result.rejected[0].reason_code, "RAW_VALIDATION_FAILED")

    def test_missing_date_never_becomes_valid_market_data(self):
        obs = _obs_missing("DATE")
        result = normalize_bhavcopy_batch((obs,), raw_source_hash="sf1hash")
        self.assertEqual(len(result.accepted), 0)
        self.assertEqual(result.rejected[0].reason_code, "RAW_VALIDATION_FAILED")

    def test_missing_volume_never_becomes_valid_market_data(self):
        obs = _obs_missing("TOTTRDQTY")
        result = normalize_bhavcopy_batch((obs,), raw_source_hash="sf1hash")
        self.assertEqual(len(result.accepted), 0)
        self.assertEqual(result.rejected[0].reason_code, "RAW_VALIDATION_FAILED")

    def test_gap_is_logged_not_silently_absent(self):
        """The rejection itself must be a first-class, inspectable record — not a swallowed
        exception and not a row that simply vanishes without a trace."""
        obs = _obs_missing("OPEN")
        result = normalize_bhavcopy_batch((obs,), raw_source_hash="sf1hash")
        self.assertEqual(len(result.rejected), 1)
        rejected = result.rejected[0]
        self.assertEqual(rejected.raw_id, obs.raw_id)
        self.assertEqual(rejected.source_row_ref, obs.source_row_ref)
        self.assertGreater(len(rejected.reasons), 0)

    def test_one_bad_row_does_not_block_other_valid_rows_in_the_same_batch(self):
        good = RawMarketObservation(
            source="nse_bhavcopy_csv",
            source_row_ref="sf1_test:line 2",
            fields=dict(_BASE_FIELDS),
            ingestion_time=datetime(2024, 1, 2, 12, 0, tzinfo=UTC),
        )
        bad = _obs_missing("HIGH")
        result = normalize_bhavcopy_batch((good, bad), raw_source_hash="sf1hash")
        self.assertEqual(len(result.accepted), 1)
        self.assertEqual(len(result.rejected), 1)


if __name__ == "__main__":
    unittest.main()
