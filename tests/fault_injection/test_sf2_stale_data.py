"""SF-2 (stale data) fault-injection test.

Stage 1 SF-2: "System must detect staleness against a defined freshness threshold and treat
stale data as missing (SF-1) rather than as current." This slice implements and tests the
CLASSIFICATION mechanism (data/validation/freshness.py) that a live pipeline (a future slice)
will act on; historical ingestion does not itself make a live trading decision, so this test
proves the mechanism correctly distinguishes fresh from stale, and that a stale record is never
silently reported as fresh.
"""

import unittest
from datetime import UTC, datetime, timedelta

from data.validation.freshness import (
    FreshnessClassification,
    classify_market_data_freshness,
)
from domain.models.market_data import MarketData


def _market_data(timestamp: datetime) -> MarketData:
    return MarketData(
        instrument_id="INE040A01034",
        timestamp=timestamp,
        open=1600.0,
        high=1615.0,
        low=1590.0,
        close=1605.0,
        volume=1000000,
        source="nse_bhavcopy_csv",
        ingestion_time=timestamp + timedelta(minutes=5),
        data_snapshot_version="snap_test",
    )


class TestSF2StaleData(unittest.TestCase):
    def test_record_within_threshold_classified_fresh(self):
        ref = datetime(2024, 1, 2, 10, 30, tzinfo=UTC)
        record = _market_data(ref - timedelta(minutes=10))
        result = classify_market_data_freshness(record, threshold_seconds=900, reference_time=ref)
        self.assertEqual(result.classification, FreshnessClassification.FRESH)

    def test_record_beyond_threshold_classified_stale_never_fresh(self):
        ref = datetime(2024, 1, 2, 10, 30, tzinfo=UTC)
        record = _market_data(ref - timedelta(days=400))  # a genuinely old historical record
        result = classify_market_data_freshness(record, threshold_seconds=900, reference_time=ref)
        self.assertEqual(result.classification, FreshnessClassification.STALE)
        self.assertNotEqual(result.classification, FreshnessClassification.FRESH)

    def test_stale_classification_reports_correct_age(self):
        ref = datetime(2024, 1, 2, 10, 30, tzinfo=UTC)
        record = _market_data(ref - timedelta(hours=2))
        result = classify_market_data_freshness(record, threshold_seconds=3600, reference_time=ref)
        self.assertEqual(result.classification, FreshnessClassification.STALE)
        self.assertAlmostEqual(result.age_seconds, 7200, delta=1)

    def test_threshold_is_never_hardcoded_by_this_module(self):
        """The freshness module must accept the threshold as an explicit parameter — it must
        not embed an assumed operator trading threshold (Stage 3 §5's explicit instruction)."""
        import inspect

        sig = inspect.signature(classify_market_data_freshness)
        self.assertIn("threshold_seconds", sig.parameters)
        self.assertIs(sig.parameters["threshold_seconds"].default, inspect.Parameter.empty)

    def test_boundary_exactly_at_threshold_is_fresh_not_stale(self):
        ref = datetime(2024, 1, 2, 10, 30, tzinfo=UTC)
        record = _market_data(ref - timedelta(seconds=100))
        result = classify_market_data_freshness(record, threshold_seconds=100, reference_time=ref)
        self.assertEqual(result.classification, FreshnessClassification.FRESH)


if __name__ == "__main__":
    unittest.main()
