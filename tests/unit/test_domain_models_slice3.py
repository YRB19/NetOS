"""Unit tests for core domain models (Slice 1 continuity restoration)."""

import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

from domain.models.enums import Action
from domain.models.instrument import Instrument
from domain.models.market_data import MarketData
from domain.models.trade import CandidateTrade

UTC = UTC


class TestInstrument(unittest.TestCase):
    def test_valid_instrument(self):
        i = Instrument(isin="INE002A01018", symbol="RELIANCE", exchange="NSE")
        self.assertEqual(i.instrument_id, "INE002A01018")

    def test_empty_isin_rejected(self):
        with self.assertRaises(ValueError):
            Instrument(isin="", symbol="RELIANCE", exchange="NSE")

    def test_non_equity_segment_rejected(self):
        with self.assertRaises(ValueError):
            Instrument(isin="INE002A01018", symbol="RELIANCE", exchange="NSE", segment="FUTURES")

    def test_immutable(self):
        i = Instrument(isin="INE002A01018", symbol="RELIANCE", exchange="NSE")
        with self.assertRaises(FrozenInstanceError):
            i.symbol = "TCS"  # type: ignore


class TestMarketData(unittest.TestCase):
    def _valid_kwargs(self):
        return dict(
            instrument_id="INE002A01018",
            timestamp=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=1000,
            source="NSE_BHAVCOPY",
            data_snapshot_version="test-snapshot",
            ingestion_time=datetime(2026, 1, 1, 16, 0, tzinfo=UTC),
        )

    def test_valid(self):
        md = MarketData(**self._valid_kwargs())
        self.assertEqual(md.close, 105.0)

    def test_naive_timestamp_rejected(self):
        kwargs = self._valid_kwargs()
        kwargs["timestamp"] = datetime(2026, 1, 1, 10, 0)
        with self.assertRaises(ValueError):
            MarketData(**kwargs)

    def test_negative_price_rejected(self):
        kwargs = self._valid_kwargs()
        kwargs["close"] = -1.0
        with self.assertRaises(ValueError):
            MarketData(**kwargs)

    def test_low_exceeds_high_rejected(self):
        kwargs = self._valid_kwargs()
        kwargs["low"] = 200.0
        with self.assertRaises(ValueError):
            MarketData(**kwargs)

    def test_open_outside_range_rejected(self):
        kwargs = self._valid_kwargs()
        kwargs["open"] = 1000.0
        with self.assertRaises(ValueError):
            MarketData(**kwargs)


class TestCandidateTrade(unittest.TestCase):
    def _valid_kwargs(self):
        return dict(
            candidate_id=str(uuid4()),
            instrument_id="INE002A01018",
            timestamp=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            action=Action.BUY,
            size_hint=0.5,
            confidence=1.0,
            uncertainty_band=None,
            rationale="test rationale",
            input_snapshot_id="snap-1",
            strategy_version_id="tier1_v1",
        )

    def test_valid(self):
        c = CandidateTrade(**self._valid_kwargs())
        self.assertEqual(c.action, Action.BUY)

    def test_empty_rationale_rejected(self):
        kwargs = self._valid_kwargs()
        kwargs["rationale"] = ""
        with self.assertRaises(ValueError):
            CandidateTrade(**kwargs)

    def test_whitespace_only_rationale_rejected(self):
        kwargs = self._valid_kwargs()
        kwargs["rationale"] = "   "
        with self.assertRaises(ValueError):
            CandidateTrade(**kwargs)

    def test_confidence_out_of_range_rejected(self):
        kwargs = self._valid_kwargs()
        kwargs["confidence"] = 1.5
        with self.assertRaises(ValueError):
            CandidateTrade(**kwargs)

    def test_missing_size_hint_on_buy_rejected(self):
        kwargs = self._valid_kwargs()
        kwargs["size_hint"] = None
        with self.assertRaises(ValueError):
            CandidateTrade(**kwargs)

    def test_hold_may_omit_size_hint(self):
        kwargs = self._valid_kwargs()
        kwargs["action"] = Action.HOLD
        kwargs["size_hint"] = None
        c = CandidateTrade(**kwargs)
        self.assertIsNone(c.size_hint)

    def test_missing_snapshot_id_rejected(self):
        kwargs = self._valid_kwargs()
        kwargs["input_snapshot_id"] = ""
        with self.assertRaises(ValueError):
            CandidateTrade(**kwargs)


if __name__ == "__main__":
    unittest.main()
