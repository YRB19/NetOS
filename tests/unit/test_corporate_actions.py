import unittest
from datetime import UTC, date, datetime

from data.normalization.corporate_actions import SplitAction, apply_split_adjustment
from data.validation.market_data_validation import CandidateOHLCV


def _ts(y, m, d):
    return datetime(y, m, d, 15, 30, tzinfo=UTC)


class TestSplitAction(unittest.TestCase):
    def test_factor_for_one_for_two_split(self):
        split = SplitAction(
            instrument_id="X", effective_date=date(2024, 6, 1), ratio_from=1, ratio_to=2
        )
        self.assertAlmostEqual(split.factor, 0.5)

    def test_nonpositive_ratio_rejected(self):
        with self.assertRaises(ValueError):
            SplitAction(
                instrument_id="X", effective_date=date(2024, 6, 1), ratio_from=0, ratio_to=2
            )

    def test_empty_instrument_id_rejected(self):
        with self.assertRaises(ValueError):
            SplitAction(instrument_id="", effective_date=date(2024, 6, 1), ratio_from=1, ratio_to=2)


class TestApplySplitAdjustment(unittest.TestCase):
    def test_no_applicable_split_leaves_candidate_unchanged(self):
        c = CandidateOHLCV(open=100, high=105, low=98, close=102, volume=1000)
        result = apply_split_adjustment("X", _ts(2024, 7, 1), c, splits=())
        self.assertFalse(result.adjusted)
        self.assertEqual(result.ohlcv, c)

    def test_observation_after_effective_date_not_adjusted(self):
        c = CandidateOHLCV(open=100, high=105, low=98, close=102, volume=1000)
        split = SplitAction(
            instrument_id="X", effective_date=date(2024, 6, 1), ratio_from=1, ratio_to=2
        )
        result = apply_split_adjustment("X", _ts(2024, 7, 1), c, splits=(split,))
        self.assertFalse(result.adjusted)
        self.assertEqual(result.ohlcv, c)

    def test_observation_before_effective_date_is_adjusted(self):
        c = CandidateOHLCV(open=200, high=210, low=195, close=205, volume=1000)
        split = SplitAction(
            instrument_id="X", effective_date=date(2024, 6, 1), ratio_from=1, ratio_to=2
        )
        result = apply_split_adjustment("X", _ts(2024, 5, 1), c, splits=(split,))
        self.assertTrue(result.adjusted)
        self.assertAlmostEqual(result.ohlcv.open, 100.0)
        self.assertAlmostEqual(result.ohlcv.high, 105.0)
        self.assertAlmostEqual(result.ohlcv.low, 97.5)
        self.assertAlmostEqual(result.ohlcv.close, 102.5)
        self.assertEqual(result.ohlcv.volume, 2000)

    def test_different_instrument_split_not_applied(self):
        c = CandidateOHLCV(open=200, high=210, low=195, close=205, volume=1000)
        split = SplitAction(
            instrument_id="Y", effective_date=date(2024, 6, 1), ratio_from=1, ratio_to=2
        )
        result = apply_split_adjustment("X", _ts(2024, 5, 1), c, splits=(split,))
        self.assertFalse(result.adjusted)

    def test_multiple_splits_compound(self):
        c = CandidateOHLCV(open=400, high=410, low=390, close=402, volume=1000)
        split1 = SplitAction(
            instrument_id="X", effective_date=date(2024, 3, 1), ratio_from=1, ratio_to=2
        )
        split2 = SplitAction(
            instrument_id="X", effective_date=date(2024, 9, 1), ratio_from=1, ratio_to=2
        )
        result = apply_split_adjustment("X", _ts(2024, 1, 1), c, splits=(split1, split2))
        self.assertTrue(result.adjusted)
        # Two 1-for-2 splits compound to a 1-for-4 factor: price / 4, volume * 4
        self.assertAlmostEqual(result.ohlcv.open, 100.0)
        self.assertEqual(result.ohlcv.volume, 4000)
        self.assertEqual(len(result.applied_splits), 2)

    def test_effective_date_boundary_is_exclusive_for_same_day(self):
        # An observation ON the effective date itself is treated as post-split (not adjusted),
        # matching the ">" comparison documented in apply_split_adjustment's docstring.
        c = CandidateOHLCV(open=100, high=105, low=98, close=102, volume=1000)
        split = SplitAction(
            instrument_id="X", effective_date=date(2024, 6, 1), ratio_from=1, ratio_to=2
        )
        result = apply_split_adjustment("X", _ts(2024, 6, 1), c, splits=(split,))
        self.assertFalse(result.adjusted)


if __name__ == "__main__":
    unittest.main()
