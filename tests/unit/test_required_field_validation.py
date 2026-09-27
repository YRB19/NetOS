"""Invalid/missing required fields must fail at construction time.

Covers the general "required fields fail" definition-of-done item across
representative models beyond CandidateTrade (which has its own dedicated,
more exhaustive file — test_candidate_trade_safety.py — since the prompt
calls it out specifically).
"""

import unittest

from domain.models import (
    Action,
    ActualCost,
    AutonomyLevel,
    ConfigurationVersion,
    CostEstimate,
    Instrument,
    MarketData,
    OrderRequest,
    OrderType,
    PortfolioState,
    PortfolioStateSource,
    Position,
    PromotionCandidate,
    PromotionDecision,
    RiskCheckResult,
    RiskDecision,
    RiskVerdict,
)
from tests.unit._helpers import NAIVE_DATETIME, utc


class TestRequiredFieldValidation(unittest.TestCase):
    # --- Instrument ---
    def test_instrument_rejects_empty_isin(self):
        with self.assertRaises(ValueError):
            Instrument(isin="", symbol="RELIANCE", exchange="NSE", lot_size=1)

    def test_instrument_rejects_non_positive_lot_size(self):
        with self.assertRaises(ValueError):
            Instrument(isin="INE002A01018", symbol="RELIANCE", exchange="NSE", lot_size=0)

    def test_instrument_universe_member_without_config_version_rejected(self):
        with self.assertRaises(ValueError):
            Instrument(
                isin="INE002A01018",
                symbol="RELIANCE",
                exchange="NSE",
                lot_size=1,
                universe_member=True,
                universe_config_version=None,
            )

    # --- MarketData ---
    def test_market_data_rejects_naive_timestamp(self):
        with self.assertRaises(ValueError):
            MarketData(
                instrument_id="X",
                timestamp=NAIVE_DATETIME,
                open=1,
                high=2,
                low=1,
                close=1.5,
                volume=1,
                source="s",
                ingestion_time=utc(),
                data_snapshot_version="v1",
            )

    def test_market_data_rejects_inconsistent_ohlc(self):
        with self.assertRaises(ValueError):
            MarketData(
                instrument_id="X",
                timestamp=utc(),
                open=1,
                high=2,
                low=3,  # low > high: invalid
                close=1.5,
                volume=1,
                source="s",
                ingestion_time=utc(),
                data_snapshot_version="v1",
            )

    def test_market_data_rejects_negative_volume(self):
        with self.assertRaises(ValueError):
            MarketData(
                instrument_id="X",
                timestamp=utc(),
                open=1,
                high=2,
                low=1,
                close=1.5,
                volume=-1,
                source="s",
                ingestion_time=utc(),
                data_snapshot_version="v1",
            )

    # --- CostEstimate / ActualCost ---
    def test_cost_estimate_rejects_negative_component(self):
        with self.assertRaises(ValueError):
            CostEstimate(
                instrument_id="X",
                brokerage=-1,
                stt=0,
                exchange_charges=0,
                sebi_fees=0,
                gst=0,
                stamp_duty=0,
                estimated_slippage=0,
                cost_model_version="cm-1",
            )

    def test_actual_cost_rejects_missing_cost_model_version(self):
        with self.assertRaises(ValueError):
            ActualCost(
                order_id="order-1",
                brokerage=1,
                stt=1,
                exchange_charges=1,
                sebi_fees=1,
                gst=1,
                stamp_duty=1,
                realized_slippage=0,
                cost_model_version="",
            )

    # --- RiskDecision ---
    def test_risk_decision_rejects_empty_checks(self):
        with self.assertRaises(ValueError):
            RiskDecision(
                candidate_trade_id="c1",
                checks_evaluated=(),
                final_verdict=RiskVerdict.APPROVE,
                risk_rule_version_id="rr-1",
                approved_qty=1,
            )

    def test_risk_decision_rejects_approve_with_failed_check(self):
        with self.assertRaises(ValueError):
            RiskDecision(
                candidate_trade_id="c1",
                checks_evaluated=(RiskCheckResult("RR-1", False, "failed"),),
                final_verdict=RiskVerdict.APPROVE,
                risk_rule_version_id="rr-1",
                approved_qty=1,
            )

    def test_risk_decision_rejects_reject_without_reason(self):
        with self.assertRaises(ValueError):
            RiskDecision(
                candidate_trade_id="c1",
                checks_evaluated=(RiskCheckResult("RR-1", False, "failed"),),
                final_verdict=RiskVerdict.REJECT,
                risk_rule_version_id="rr-1",
                reasons=(),
            )

    def test_risk_decision_rejects_approve_without_qty(self):
        with self.assertRaises(ValueError):
            RiskDecision(
                candidate_trade_id="c1",
                checks_evaluated=(RiskCheckResult("RR-1", True, "ok"),),
                final_verdict=RiskVerdict.APPROVE,
                risk_rule_version_id="rr-1",
                approved_qty=None,
            )

    # --- Position / PortfolioState ---
    def test_position_rejects_negative_quantity_when_long(self):
        with self.assertRaises(ValueError):
            Position(instrument_id="X", quantity=-1, avg_cost=100)

    def test_portfolio_state_rejects_negative_cash(self):
        with self.assertRaises(ValueError):
            PortfolioState(
                as_of_timestamp=utc(),
                positions=(),
                cash_balance=-1,
                source=PortfolioStateSource.SYSTEM_BELIEF,
            )

    def test_portfolio_state_rejects_duplicate_instrument_ids(self):
        p1 = Position(instrument_id="X", quantity=1, avg_cost=1)
        p2 = Position(instrument_id="X", quantity=2, avg_cost=1)
        with self.assertRaises(ValueError):
            PortfolioState(
                as_of_timestamp=utc(),
                positions=(p1, p2),
                cash_balance=100,
                source=PortfolioStateSource.SYSTEM_BELIEF,
            )

    # --- OrderRequest ---
    def test_order_request_rejects_hold_as_side(self):
        with self.assertRaises(ValueError):
            OrderRequest(
                instrument_id="X",
                side=Action.HOLD,
                quantity=1,
                order_type=OrderType.MARKET,
                risk_decision_id="rd-1",
            )

    def test_order_request_rejects_non_positive_quantity(self):
        with self.assertRaises(ValueError):
            OrderRequest(
                instrument_id="X",
                side=Action.BUY,
                quantity=0,
                order_type=OrderType.MARKET,
                risk_decision_id="rd-1",
            )

    def test_order_request_market_order_rejects_limit_price(self):
        with self.assertRaises(ValueError):
            OrderRequest(
                instrument_id="X",
                side=Action.BUY,
                quantity=1,
                order_type=OrderType.MARKET,
                risk_decision_id="rd-1",
                limit_price=100,
            )

    def test_order_request_limit_order_requires_limit_price(self):
        with self.assertRaises(ValueError):
            OrderRequest(
                instrument_id="X",
                side=Action.BUY,
                quantity=1,
                order_type=OrderType.LIMIT,
                risk_decision_id="rd-1",
            )

    # --- ConfigurationVersion ---
    def test_configuration_version_rejects_empty_set_by(self):
        with self.assertRaises(ValueError):
            ConfigurationVersion(values={}, set_by="", effective_from=utc())

    # --- PromotionCandidate ---
    def test_promotion_candidate_rejects_decision_without_reviewer(self):
        with self.assertRaises(ValueError):
            PromotionCandidate(
                experiment_id="exp-1",
                evaluation_run_id="run-1",
                decision=PromotionDecision.APPROVE,
                reviewer=None,
                decision_timestamp=utc(),
            )

    def test_promotion_candidate_rejects_reviewer_without_decision(self):
        with self.assertRaises(ValueError):
            PromotionCandidate(
                experiment_id="exp-1",
                evaluation_run_id="run-1",
                decision=None,
                reviewer="alice",
                decision_timestamp=utc(),
            )

    # --- AutonomyLevel ---
    def test_autonomy_level_rejects_out_of_range_level(self):
        with self.assertRaises(ValueError):
            AutonomyLevel(level=4, set_by="operator", effective_from=utc())

    def test_autonomy_level_rejects_empty_set_by(self):
        with self.assertRaises(ValueError):
            AutonomyLevel(level=1, set_by="", effective_from=utc())

    def test_autonomy_level_rejects_effective_to_before_effective_from(self):
        with self.assertRaises(ValueError):
            AutonomyLevel(level=1, set_by="operator", effective_from=utc(1), effective_to=utc(0))


if __name__ == "__main__":
    unittest.main()
