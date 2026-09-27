import unittest
from datetime import UTC, datetime

from data.validation.raw_validation import validate_raw_bhavcopy_observation
from domain.models.raw_observation import RawMarketObservation


def _obs(fields):
    return RawMarketObservation(
        source="nse_bhavcopy_csv",
        source_row_ref="test.csv:line 2",
        fields=fields,
        ingestion_time=datetime(2024, 1, 2, 12, 0, tzinfo=UTC),
    )


_VALID_FIELDS = {
    "SYMBOL": "RELIANCE",
    "ISIN": "INE002A01018",
    "SERIES": "EQ",
    "DATE": "02-JAN-2024",
    "OPEN": "2550.00",
    "HIGH": "2570.50",
    "LOW": "2540.00",
    "CLOSE": "2565.25",
    "TOTTRDQTY": "4523100",
}


class TestValidateRawBhavcopyObservation(unittest.TestCase):
    def test_valid_row_passes(self):
        result = validate_raw_bhavcopy_observation(_obs(dict(_VALID_FIELDS)))
        self.assertTrue(result.ok)
        self.assertEqual(result.reasons, ())

    def test_missing_open_fails(self):
        fields = dict(_VALID_FIELDS)
        fields["OPEN"] = ""
        result = validate_raw_bhavcopy_observation(_obs(fields))
        self.assertFalse(result.ok)
        self.assertTrue(any("OPEN" in r for r in result.reasons))

    def test_missing_isin_fails(self):
        fields = dict(_VALID_FIELDS)
        del fields["ISIN"]
        result = validate_raw_bhavcopy_observation(_obs(fields))
        self.assertFalse(result.ok)
        self.assertTrue(any("ISIN" in r for r in result.reasons))

    def test_whitespace_only_field_treated_as_missing(self):
        fields = dict(_VALID_FIELDS)
        fields["CLOSE"] = "   "
        result = validate_raw_bhavcopy_observation(_obs(fields))
        self.assertFalse(result.ok)
        self.assertTrue(any("CLOSE" in r for r in result.reasons))

    def test_disallowed_series_fails(self):
        fields = dict(_VALID_FIELDS)
        fields["SERIES"] = "BE"
        result = validate_raw_bhavcopy_observation(_obs(fields))
        self.assertFalse(result.ok)
        self.assertTrue(any("SERIES" in r for r in result.reasons))

    def test_lowercase_eq_series_normalized_and_accepted(self):
        fields = dict(_VALID_FIELDS)
        fields["SERIES"] = "eq"
        result = validate_raw_bhavcopy_observation(_obs(fields))
        self.assertTrue(result.ok)

    def test_multiple_missing_fields_all_reported(self):
        fields = dict(_VALID_FIELDS)
        fields["OPEN"] = ""
        fields["CLOSE"] = ""
        result = validate_raw_bhavcopy_observation(_obs(fields))
        self.assertFalse(result.ok)
        self.assertEqual(len(result.reasons), 2)


if __name__ == "__main__":
    unittest.main()
