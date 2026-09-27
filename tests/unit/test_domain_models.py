import dataclasses
import unittest
from datetime import UTC, datetime, timezone

from domain.models.instrument import Instrument
from domain.models.market_data import MarketData
from domain.models.raw_observation import RawMarketObservation


def _dt(y, m, d, h=15, mi=30):
    return datetime(y, m, d, h, mi, tzinfo=UTC)


class TestInstrument(unittest.TestCase):
    def test_valid_instrument_constructs(self):
        inst = Instrument(isin="INE002A01018", symbol="RELIANCE", exchange="NSE", lot_size=1)
        self.assertEqual(inst.canonical_id, "INE002A01018")
        self.assertEqual(inst.working_id, "NSE:RELIANCE")

    def test_empty_isin_rejected(self):
        with self.assertRaises(ValueError):
            Instrument(isin="", symbol="RELIANCE", exchange="NSE", lot_size=1)

    def test_empty_symbol_rejected(self):
        with self.assertRaises(ValueError):
            Instrument(isin="INE002A01018", symbol="", exchange="NSE", lot_size=1)

    def test_invalid_exchange_rejected(self):
        with self.assertRaises(ValueError):
            Instrument(isin="INE002A01018", symbol="RELIANCE", exchange="MCX", lot_size=1)

    def test_nonpositive_lot_size_rejected(self):
        with self.assertRaises(ValueError):
            Instrument(isin="INE002A01018", symbol="RELIANCE", exchange="NSE", lot_size=0)

    def test_non_equity_segment_rejected(self):
        with self.assertRaises(ValueError):
            Instrument(
                isin="INE002A01018",
                symbol="RELIANCE",
                exchange="NSE",
                lot_size=1,
                segment="FUTURES",
            )

    def test_instrument_is_immutable(self):
        inst = Instrument(isin="INE002A01018", symbol="RELIANCE", exchange="NSE", lot_size=1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            inst.symbol = "TCS"  # type: ignore[misc]


class TestRawMarketObservation(unittest.TestCase):
    def test_valid_raw_observation_constructs(self):
        obs = RawMarketObservation(
            source="nse_bhavcopy_csv",
            source_row_ref="file.csv:line 2",
            fields={"SYMBOL": "RELIANCE"},
            ingestion_time=_dt(2024, 1, 2, 12, 0),
        )
        self.assertTrue(obs.raw_id.startswith("raw_"))

    def test_empty_fields_rejected(self):
        with self.assertRaises(ValueError):
            RawMarketObservation(
                source="nse_bhavcopy_csv",
                source_row_ref="file.csv:line 2",
                fields={},
                ingestion_time=_dt(2024, 1, 2, 12, 0),
            )

    def test_naive_ingestion_time_rejected(self):
        with self.assertRaises(ValueError):
            RawMarketObservation(
                source="nse_bhavcopy_csv",
                source_row_ref="file.csv:line 2",
                fields={"SYMBOL": "RELIANCE"},
                ingestion_time=datetime(2024, 1, 2, 12, 0),  # naive
            )

    def test_raw_id_deterministic_and_ignores_ingestion_time(self):
        obs1 = RawMarketObservation(
            source="s", source_row_ref="r", fields={"a": "1"}, ingestion_time=_dt(2024, 1, 1)
        )
        obs2 = RawMarketObservation(
            source="s", source_row_ref="r", fields={"a": "1"}, ingestion_time=_dt(2024, 6, 1)
        )
        self.assertEqual(obs1.raw_id, obs2.raw_id)

    def test_raw_id_changes_with_content(self):
        obs1 = RawMarketObservation(
            source="s", source_row_ref="r", fields={"a": "1"}, ingestion_time=_dt(2024, 1, 1)
        )
        obs2 = RawMarketObservation(
            source="s", source_row_ref="r", fields={"a": "2"}, ingestion_time=_dt(2024, 1, 1)
        )
        self.assertNotEqual(obs1.raw_id, obs2.raw_id)


class TestMarketData(unittest.TestCase):
    def _valid_kwargs(self, **overrides):
        kwargs = dict(
            instrument_id="INE002A01018",
            timestamp=_dt(2024, 1, 2),
            open=100.0,
            high=105.0,
            low=99.0,
            close=102.0,
            volume=1000,
            source="nse_bhavcopy_csv",
            ingestion_time=_dt(2024, 1, 2, 20, 0),
            data_snapshot_version="snap_abc",
        )
        kwargs.update(overrides)
        return kwargs

    def test_valid_market_data_constructs(self):
        md = MarketData(**self._valid_kwargs())
        self.assertEqual(md.identity_key, ("INE002A01018", _dt(2024, 1, 2), "nse_bhavcopy_csv"))

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            MarketData(**self._valid_kwargs(timestamp=datetime(2024, 1, 2)))

    def test_non_utc_timestamp_rejected(self):
        ist = timezone(timedelta_hours(5, 30))
        with self.assertRaises(ValueError):
            MarketData(**self._valid_kwargs(timestamp=datetime(2024, 1, 2, tzinfo=ist)))

    def test_zero_price_rejected(self):
        with self.assertRaises(ValueError):
            MarketData(**self._valid_kwargs(open=0.0))

    def test_negative_price_rejected(self):
        with self.assertRaises(ValueError):
            MarketData(**self._valid_kwargs(close=-1.0))

    def test_negative_volume_rejected(self):
        with self.assertRaises(ValueError):
            MarketData(**self._valid_kwargs(volume=-1))

    def test_nan_price_rejected(self):
        with self.assertRaises(ValueError):
            MarketData(**self._valid_kwargs(open=float("nan")))

    def test_infinite_price_rejected(self):
        with self.assertRaises(ValueError):
            MarketData(**self._valid_kwargs(high=float("inf")))

    def test_ohlc_inconsistency_high_too_low_rejected(self):
        with self.assertRaises(ValueError):
            MarketData(**self._valid_kwargs(high=90.0))  # below open/close/low

    def test_ohlc_inconsistency_low_too_high_rejected(self):
        with self.assertRaises(ValueError):
            MarketData(**self._valid_kwargs(low=110.0))  # above open/close/high

    def test_empty_instrument_id_rejected(self):
        with self.assertRaises(ValueError):
            MarketData(**self._valid_kwargs(instrument_id=""))

    def test_market_data_is_immutable(self):
        md = MarketData(**self._valid_kwargs())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            md.close = 999.0  # type: ignore[misc]


def timedelta_hours(h, m):
    from datetime import timedelta

    return timedelta(hours=h, minutes=m)


if __name__ == "__main__":
    unittest.main()
