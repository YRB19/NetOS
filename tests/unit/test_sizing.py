"""Slice 6 — deterministic sizing. SYNTHETIC; example parameters only."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from domain.models.enums import Action, PortfolioStateSource, RiskVerdict
from domain.models.portfolio import PortfolioState, Position
from domain.models.risk_decision import RiskCheckResult, RiskDecision
from domain.models.trade import CandidateTrade
from risk_execution.sizing import SizingInputs, SizingOutcome, size_order
from tests.unit._pipeline_helpers import sizing_config

T = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
A = "INE001X00001"
CID = str(UUID(int=7))


def cand(action=Action.BUY, hint=0.3) -> CandidateTrade:
    return CandidateTrade(candidate_id=CID, instrument_id=A, timestamp=T, action=action, size_hint=hint,
                          confidence=0.9, uncertainty_band=None, rationale="r", input_snapshot_id="snap",
                          strategy_version_id="strat@1", model_version_id=None)


def rd(verdict=RiskVerdict.APPROVE, ceiling=10_000.0, cid=CID, passed=True) -> RiskDecision:
    chk = (RiskCheckResult("RR-1", passed, "x"),)
    if verdict is RiskVerdict.APPROVE:
        return RiskDecision(cid, chk, verdict, "rules@1", ceiling, (), "risk_1")
    return RiskDecision(cid, (RiskCheckResult("RR-1", False, "x"),), verdict, "rules@1", None, ("RR-1: x",), "risk_1")


def inputs(held=0, cash=1_000_000.0, equity="1000000", price="100", **kw) -> SizingInputs:
    pos = (Position(A, float(held), 90.0),) if held else ()
    pf = PortfolioState(as_of_timestamp=T, positions=pos, cash_balance=cash, source=PortfolioStateSource.SYSTEM_BELIEF)
    return SizingInputs(pf, Decimal(equity) if equity is not None else None,
                        Decimal(price) if price is not None else None, research_run_id="run_1", **kw)


class SizingTests(unittest.TestCase):
    cfg = sizing_config()

    def test_buy_quantity_from_target_weight_floor_rounded(self):
        d = size_order(cand(hint=0.3), rd(), inputs(), self.cfg)
        self.assertIs(d.outcome, SizingOutcome.ORDER)
        self.assertEqual(d.quantity, 2970)  # floor(0.3 * 1,000,000 * 0.99 / 100)
        self.assertEqual(d.order_request.quantity, 2970.0)
        self.assertEqual(d.order_request.risk_decision_id, "risk_1")
        self.assertEqual(d.estimated_residual_cash, Decimal(1_000_000) - 297_000)

    def test_rounding_is_floor_not_nearest(self):
        d = size_order(cand(hint=0.3), rd(), inputs(price="333"), self.cfg)  # 297000/333 = 891.89
        self.assertEqual(d.quantity, 891)

    def test_buy_tops_up_existing_position_only_by_the_gap(self):
        d = size_order(cand(hint=0.3), rd(), inputs(held=2900), self.cfg)
        self.assertEqual(d.quantity, 70)

    def test_buy_at_or_above_target_is_no_trade(self):
        for held in (2970, 5000):
            self.assertIs(size_order(cand(), rd(), inputs(held=held), self.cfg).outcome, SizingOutcome.NO_TRADE)

    def test_quantity_never_exceeds_risk_ceiling(self):
        d = size_order(cand(hint=0.3), rd(ceiling=500.0), inputs(), self.cfg)
        self.assertEqual(d.quantity, 500)

    def test_zero_and_insufficient_cash(self):
        self.assertIs(size_order(cand(), rd(), inputs(cash=0.0), self.cfg).outcome, SizingOutcome.NO_TRADE)
        d = size_order(cand(), rd(), inputs(cash=10_050.0), self.cfg)
        self.assertEqual(d.quantity, 100)  # affordable shares only
        self.assertIsNone(size_order(cand(), rd(), inputs(cash=50.0), self.cfg).order_request)

    def test_pending_orders_are_netted(self):
        d = size_order(cand(), rd(), inputs(pending_buy_qty=2970), self.cfg)
        self.assertIs(d.outcome, SizingOutcome.NO_TRADE)

    def test_pending_sales_proceeds_fund_buys(self):
        d = size_order(cand(), rd(), inputs(held=3000, cash=0.0, pending_sell_qty=3000), self.cfg)
        self.assertEqual(d.quantity, 2970)  # proceeds of the pending sale (300,000) fund the buy

    def test_min_trade_notional(self):
        cfg = sizing_config(min_trade_notional=Decimal("500000"))
        self.assertIs(size_order(cand(), rd(), inputs(), cfg).outcome, SizingOutcome.NO_TRADE)

    def test_zero_hint_buy_is_no_trade(self):
        self.assertIs(size_order(cand(hint=0.0), rd(), inputs(), self.cfg).outcome, SizingOutcome.NO_TRADE)

    def test_invalid_size_hints_rejected(self):
        for h in (float("nan"), float("inf"), -0.1, 1.5):
            c = cand()
            object.__setattr__(c, "size_hint", h)
            self.assertIs(size_order(c, rd(), inputs(), self.cfg).outcome, SizingOutcome.REJECTED_INVALID_INPUT, msg=str(h))
        c = cand()
        object.__setattr__(c, "size_hint", None)
        self.assertIs(size_order(c, rd(), inputs(), self.cfg).outcome, SizingOutcome.REJECTED_INVALID_INPUT)

    def test_invalid_prices_and_equity_and_missing_state(self):
        for price in ("0", "-5", None, "NaN", "Infinity"):
            self.assertIs(size_order(cand(), rd(), inputs(price=price), self.cfg).outcome,
                          SizingOutcome.REJECTED_INVALID_INPUT, msg=str(price))
        for eq in ("0", "-1", None):
            self.assertIs(size_order(cand(), rd(), inputs(equity=eq), self.cfg).outcome, SizingOutcome.REJECTED_INVALID_INPUT)
        self.assertIs(size_order(cand(), rd(), SizingInputs(None, Decimal(1), Decimal(1)), self.cfg).outcome,
                      SizingOutcome.REJECTED_INVALID_INPUT)

    def test_sell_full_exit_and_partial(self):
        full = size_order(cand(Action.SELL, 0.0), rd(ceiling=1000.0), inputs(held=1000), self.cfg)
        self.assertEqual((full.outcome, full.quantity, full.side), (SizingOutcome.ORDER, 1000, Action.SELL))
        part = size_order(cand(Action.SELL, 0.1), rd(ceiling=5000.0), inputs(held=5000), self.cfg)
        self.assertEqual(part.quantity, 5000 - 990)  # keep floor(0.1*1e6*0.99/100)=990
        self.assertIs(size_order(cand(Action.SELL, 0.0), rd(ceiling=1.0), inputs(held=1000), self.cfg).quantity, 1)

    def test_sell_never_exceeds_holding_or_goes_negative(self):
        d = size_order(cand(Action.SELL, 0.0), rd(ceiling=99999.0), inputs(held=300, pending_sell_qty=100), self.cfg)
        self.assertEqual(d.quantity, 200)
        none = size_order(cand(Action.SELL, 0.0), rd(), inputs(held=0), self.cfg)
        self.assertIs(none.outcome, SizingOutcome.NO_TRADE)
        self.assertEqual(none.quantity, 0)

    def test_hold_requests_no_order(self):
        c = cand(Action.HOLD, None)
        self.assertIs(size_order(c, rd(), inputs(), self.cfg).outcome, SizingOutcome.NO_TRADE)

    def test_no_negative_or_fractional_quantity_ever(self):
        for h in (0.0, 0.01, 0.3, 1.0):
            for held in (0, 10, 7777):
                for a in (Action.BUY, Action.SELL):
                    d = size_order(cand(a, h), rd(ceiling=3000.0), inputs(held=held), self.cfg)
                    self.assertIsInstance(d.quantity, int)
                    self.assertGreaterEqual(d.quantity, 0)
                    if d.order_request:
                        self.assertEqual(d.order_request.quantity, float(int(d.order_request.quantity)))
                        self.assertLessEqual(d.quantity, 3000)

    def test_vetoed_candidate_never_becomes_an_order(self):
        d = size_order(cand(), rd(RiskVerdict.REJECT), inputs(), self.cfg)
        self.assertIs(d.outcome, SizingOutcome.REFUSED_NOT_APPROVED)
        self.assertIsNone(d.order_request)
        self.assertEqual(d.quantity, 0)

    def test_approval_for_a_different_candidate_or_forged_approve_is_refused(self):
        other = rd(cid=str(UUID(int=99)))
        self.assertIs(size_order(cand(), other, inputs(), self.cfg).outcome, SizingOutcome.REFUSED_NOT_APPROVED)
        with self.assertRaises(ValueError):  # the domain type already refuses APPROVE-with-failed-check
            rd(passed=False)
        for junk in (None, "APPROVE", True, object()):
            self.assertIs(size_order(cand(), junk, inputs(), self.cfg).outcome, SizingOutcome.REFUSED_NOT_APPROVED)

    def test_invalid_config_refused(self):
        bad = sizing_config(cash_buffer=Decimal("1"))
        self.assertIs(size_order(cand(), rd(), inputs(), bad).outcome, SizingOutcome.REJECTED_INVALID_INPUT)

    def test_deterministic_repeat(self):
        self.assertEqual(size_order(cand(), rd(), inputs(), self.cfg), size_order(cand(), rd(), inputs(), self.cfg))


if __name__ == "__main__":
    unittest.main()
