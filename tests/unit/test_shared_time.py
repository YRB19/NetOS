import unittest
from datetime import UTC, datetime, timedelta

from shared.time.clock import (
    IST,
    TimestampError,
    evaluate_freshness,
    parse_source_timestamp,
    to_ist,
    utc_now,
)


class TestParseSourceTimestamp(unittest.TestCase):
    def test_naive_without_declared_tz_raises(self):
        with self.assertRaises(TimestampError):
            parse_source_timestamp(datetime(2024, 1, 2, 15, 30))

    def test_naive_with_declared_ist_converts_to_utc(self):
        naive = datetime(2024, 1, 2, 15, 30)
        result = parse_source_timestamp(naive, assumed_source_tz=IST)
        self.assertEqual(result.tzinfo, UTC)
        self.assertEqual(result, datetime(2024, 1, 2, 10, 0, tzinfo=UTC))

    def test_aware_timestamp_tzinfo_is_authoritative(self):
        aware = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
        result = parse_source_timestamp(aware, assumed_source_tz=IST)
        self.assertEqual(result, aware)


class TestToIst(unittest.TestCase):
    def test_utc_to_ist_offset(self):
        utc_dt = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
        ist_dt = to_ist(utc_dt)
        self.assertEqual(ist_dt.hour, 15)
        self.assertEqual(ist_dt.minute, 30)

    def test_naive_input_rejected(self):
        with self.assertRaises(TimestampError):
            to_ist(datetime(2024, 1, 2, 10, 0))


class TestUtcNow(unittest.TestCase):
    def test_utc_now_is_aware(self):
        now = utc_now()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.utcoffset(), timedelta(0))


class TestEvaluateFreshness(unittest.TestCase):
    def test_fresh_within_threshold(self):
        ref = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
        obs = ref - timedelta(seconds=30)
        result = evaluate_freshness(obs, threshold_seconds=60, reference_time=ref)
        self.assertTrue(result.is_fresh)
        self.assertAlmostEqual(result.age_seconds, 30)

    def test_stale_beyond_threshold(self):
        ref = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
        obs = ref - timedelta(seconds=120)
        result = evaluate_freshness(obs, threshold_seconds=60, reference_time=ref)
        self.assertFalse(result.is_fresh)

    def test_future_observation_is_not_fresh(self):
        ref = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
        obs = ref + timedelta(seconds=10)
        result = evaluate_freshness(obs, threshold_seconds=60, reference_time=ref)
        self.assertFalse(result.is_fresh)

    def test_exactly_at_threshold_is_fresh(self):
        ref = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
        obs = ref - timedelta(seconds=60)
        result = evaluate_freshness(obs, threshold_seconds=60, reference_time=ref)
        self.assertTrue(result.is_fresh)

    def test_naive_observation_rejected(self):
        with self.assertRaises(TimestampError):
            evaluate_freshness(datetime(2024, 1, 2), threshold_seconds=60)

    def test_negative_threshold_rejected(self):
        ref = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
        with self.assertRaises(TimestampError):
            evaluate_freshness(ref, threshold_seconds=-1, reference_time=ref)


if __name__ == "__main__":
    unittest.main()
