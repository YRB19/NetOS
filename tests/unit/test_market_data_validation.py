import unittest

from data.validation.market_data_validation import CandidateOHLCV, validate_ohlcv


class TestValidateOhlcv(unittest.TestCase):
    def test_valid_candidate_passes(self):
        c = CandidateOHLCV(open=100.0, high=105.0, low=98.0, close=102.0, volume=1000)
        result = validate_ohlcv(c)
        self.assertTrue(result.ok)
        self.assertEqual(result.reasons, ())

    def test_zero_open_fails(self):
        c = CandidateOHLCV(open=0.0, high=105.0, low=98.0, close=102.0, volume=1000)
        result = validate_ohlcv(c)
        self.assertFalse(result.ok)
        self.assertTrue(any("open" in r for r in result.reasons))

    def test_negative_close_fails(self):
        c = CandidateOHLCV(open=100.0, high=105.0, low=98.0, close=-5.0, volume=1000)
        result = validate_ohlcv(c)
        self.assertFalse(result.ok)

    def test_nan_high_fails(self):
        c = CandidateOHLCV(open=100.0, high=float("nan"), low=98.0, close=102.0, volume=1000)
        result = validate_ohlcv(c)
        self.assertFalse(result.ok)
        self.assertTrue(any("NaN" in r for r in result.reasons))

    def test_infinite_low_fails(self):
        c = CandidateOHLCV(open=100.0, high=105.0, low=float("-inf"), close=102.0, volume=1000)
        result = validate_ohlcv(c)
        self.assertFalse(result.ok)

    def test_negative_volume_fails(self):
        c = CandidateOHLCV(open=100.0, high=105.0, low=98.0, close=102.0, volume=-1)
        result = validate_ohlcv(c)
        self.assertFalse(result.ok)

    def test_high_below_open_close_low_fails(self):
        c = CandidateOHLCV(open=100.0, high=90.0, low=85.0, close=95.0, volume=1000)
        result = validate_ohlcv(c)
        self.assertFalse(result.ok)
        self.assertTrue(any("high" in r for r in result.reasons))

    def test_low_above_open_close_high_fails(self):
        c = CandidateOHLCV(open=100.0, high=110.0, low=105.0, close=102.0, volume=1000)
        result = validate_ohlcv(c)
        self.assertFalse(result.ok)
        self.assertTrue(any("low" in r for r in result.reasons))

    def test_multiple_problems_all_reported(self):
        c = CandidateOHLCV(open=-1.0, high=90.0, low=85.0, close=-2.0, volume=-5)
        result = validate_ohlcv(c)
        self.assertFalse(result.ok)
        # open, close, volume should each contribute at least one reason
        self.assertGreaterEqual(len(result.reasons), 3)

    def test_zero_volume_is_valid(self):
        c = CandidateOHLCV(open=100.0, high=100.0, low=100.0, close=100.0, volume=0)
        result = validate_ohlcv(c)
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
