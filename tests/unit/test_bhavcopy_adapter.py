import tempfile
import unittest
from pathlib import Path

from data.adapters.nse_bhavcopy_csv import SourceFormatError, load_bhavcopy_csv

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "historical_data"


class TestLoadBhavcopyCsv(unittest.TestCase):
    def test_valid_fixture_loads_all_rows_as_raw_observations(self):
        result = load_bhavcopy_csv(FIXTURE_DIR / "valid_sample.csv")
        self.assertEqual(len(result.observations), 4)
        first = result.observations[0]
        self.assertEqual(first.source, "nse_bhavcopy_csv")
        self.assertEqual(first.fields["SYMBOL"], "RELIANCE")
        self.assertTrue(result.raw_source_hash)

    def test_source_row_ref_tracks_line_number(self):
        result = load_bhavcopy_csv(FIXTURE_DIR / "valid_sample.csv")
        self.assertIn("line 2", result.observations[0].source_row_ref)
        self.assertIn("line 3", result.observations[1].source_row_ref)

    def test_missing_file_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            load_bhavcopy_csv(FIXTURE_DIR / "does_not_exist.csv")

    def test_missing_required_column_raises_source_format_error(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.csv"
            bad.write_text(
                "SYMBOL,ISIN,SERIES,DATE,OPEN,HIGH,LOW,TOTTRDQTY\nX,Y,EQ,02-JAN-2024,1,2,3,100\n"
            )
            with self.assertRaises(SourceFormatError):
                load_bhavcopy_csv(bad)  # missing CLOSE column

    def test_raw_source_hash_deterministic_for_identical_file_content(self):
        result1 = load_bhavcopy_csv(FIXTURE_DIR / "valid_sample.csv")
        result2 = load_bhavcopy_csv(FIXTURE_DIR / "valid_sample.csv")
        self.assertEqual(result1.raw_source_hash, result2.raw_source_hash)

    def test_raw_ids_are_stable_across_two_loads(self):
        result1 = load_bhavcopy_csv(FIXTURE_DIR / "valid_sample.csv")
        result2 = load_bhavcopy_csv(FIXTURE_DIR / "valid_sample.csv")
        ids1 = [o.raw_id for o in result1.observations]
        ids2 = [o.raw_id for o in result2.observations]
        self.assertEqual(ids1, ids2)


if __name__ == "__main__":
    unittest.main()
