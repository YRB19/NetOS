"""Every Stage 3 §2 domain object can be validly constructed.

This is the "positive" half of the domain-model test suite: for each
object, build one clearly-valid instance. Required-field / invalid-input
rejection is tested separately (test_required_field_validation.py,
test_candidate_trade_safety.py) so each file has a single, clear purpose.
"""

import unittest

from domain.models import (
    Action,
    ActualCost,
    AutonomyLevel,
    CandidateTrade,
    ConfigurationVersion,
    ContaminationCheckResult,
    CostEstimate,
    DataSourceRef,
    DecisionRecordBuilder,
    EvaluationRun,
    Experiment,
    FeatureSnapshot,
    Fill,
    FillType,
    Instrument,
    MarketData,
    ModelVersion,
    Order,
    OrderRequest,
    OrderState,
    OrderType,
    Plane2Type,
    PortfolioState,
    PortfolioStateSource,
    Position,
    PromotionCandidate,
    RiskCheckResult,
    RiskDecision,
    RiskRuleVersion,
    RiskVerdict,
    Segment,
    SplitSpec,
    StrategyVersion,
    TerminalState,
    UncertaintyBand,
)
from tests.unit._helpers import utc


class TestValidConstruction(unittest.TestCase):
    def test_instrument(self):
        i = Instrument(isin="INE002A01018", symbol="RELIANCE", exchange="NSE", lot_size=1)
        self.assertEqual(i.segment, Segment.EQUITY)
        self.assertEqual(i.working_id, "NSE:RELIANCE")

    def test_instrument_universe_membership_requires_config_version(self):
        i = Instrument(
            isin="INE002A01018",
            symbol="RELIANCE",
            exchange="NSE",
            lot_size=1,
            universe_member=True,
            universe_config_version="cfg-v1",
        )
        self.assertTrue(i.universe_member)

    def test_market_data(self):
        md = MarketData(
            instrument_id="INE002A01018",
            timestamp=utc(),
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=10_000,
            source="test-feed",
            ingestion_time=utc(),
            data_snapshot_version="ds-1",
        )
        self.assertEqual(md.identity_key, ("INE002A01018", utc(), "test-feed"))

    def test_feature_snapshot(self):
        fs = FeatureSnapshot(
            instrument_id="INE002A01018",
            decision_timestamp=utc(),
            feature_values={"mom_12_1": 0.05},
            feature_set_version="fs-1",
        )
        self.assertEqual(fs.value("mom_12_1"), 0.05)
        self.assertIsNone(fs.value("does_not_exist"))

    def test_candidate_trade(self):
        ct = CandidateTrade(
            instrument_id="INE002A01018",
            timestamp=utc(),
            action=Action.BUY,
            confidence=0.72,
            rationale="momentum positive",
            input_snapshot_id="snap-1",
            strategy_version_id="strat-1",
            size_hint=0.8,
            uncertainty_band=UncertaintyBand.LOW,
        )
        self.assertEqual(ct.action, Action.BUY)

    def test_cost_estimate_and_actual_cost(self):
        ce = CostEstimate(
            instrument_id="INE002A01018",
            brokerage=20,
            stt=5,
            exchange_charges=1,
            sebi_fees=0.1,
            gst=3.6,
            stamp_duty=1.5,
            estimated_slippage=2,
            cost_model_version="cm-1",
        )
        self.assertAlmostEqual(ce.total(), 33.2)

        ac = ActualCost(
            order_id="order-1",
            brokerage=20,
            stt=5,
            exchange_charges=1,
            sebi_fees=0.1,
            gst=3.6,
            stamp_duty=1.5,
            realized_slippage=-1.5,  # a favorable fill is allowed to be negative
            cost_model_version="cm-1",
        )
        self.assertAlmostEqual(ac.total(), 29.7)

    def test_risk_decision_approve(self):
        rd = RiskDecision(
            candidate_trade_id="cand-1",
            checks_evaluated=(RiskCheckResult("RR-1", True, "within limit"),),
            final_verdict=RiskVerdict.APPROVE,
            risk_rule_version_id="rr-1",
            approved_qty=10,
        )
        self.assertEqual(rd.final_verdict, RiskVerdict.APPROVE)

    def test_risk_decision_reject(self):
        rd = RiskDecision(
            candidate_trade_id="cand-1",
            checks_evaluated=(RiskCheckResult("RR-1", False, "exceeds exposure limit"),),
            final_verdict=RiskVerdict.REJECT,
            risk_rule_version_id="rr-1",
            reasons=("RR-1 exceeded",),
        )
        self.assertEqual(rd.final_verdict, RiskVerdict.REJECT)

    def test_position_and_portfolio_state(self):
        pos = Position(instrument_id="INE002A01018", quantity=10, avg_cost=100.0)
        ps = PortfolioState(
            as_of_timestamp=utc(),
            positions=(pos,),
            cash_balance=1000.0,
            source=PortfolioStateSource.BROKER_CONFIRMED,
        )
        self.assertEqual(ps.position_for("INE002A01018"), pos)
        self.assertIsNone(ps.position_for("nope"))

    def test_order_request(self):
        orq = OrderRequest(
            instrument_id="INE002A01018",
            side=Action.BUY,
            quantity=10,
            order_type=OrderType.MARKET,
            risk_decision_id="rd-1",
        )
        self.assertEqual(orq.side, Action.BUY)

    def test_order_request_limit(self):
        orq = OrderRequest(
            instrument_id="INE002A01018",
            side=Action.SELL,
            quantity=5,
            order_type=OrderType.LIMIT,
            risk_decision_id="rd-1",
            limit_price=101.5,
        )
        self.assertEqual(orq.limit_price, 101.5)

    def test_order_and_fill(self):
        order = Order(order_request_id="req-1")
        order.transition_to(OrderState.APPROVED)
        order.transition_to(OrderState.SUBMITTED)
        order.transition_to(OrderState.ACKNOWLEDGED)
        order.transition_to(OrderState.FILLED)
        fill = Fill(
            order_id=order.order_id,
            quantity=10,
            price=101.5,
            timestamp=utc(),
            fill_type=FillType.FULL,
        )
        self.assertEqual(fill.fill_type, FillType.FULL)
        self.assertTrue(order.is_terminal())

    def test_decision_record_builder_hold_cycle(self):
        drb = DecisionRecordBuilder(
            instrument_id="INE002A01018",
            cycle_timestamp=utc(),
            autonomy_level=1,
            risk_rule_version_id="rr-1",
            config_version_id="cfg-1",
        )
        drb.with_snapshot("snap-1", [DataSourceRef("feed-a", "v1", utc())])
        dr = drb.finalize(TerminalState.NO_CANDIDATE)
        self.assertTrue(dr.is_finalized())
        self.assertIsNone(dr.candidate_trade_id)

    def test_strategy_version_and_model_version(self):
        sv = StrategyVersion(plane2_type=Plane2Type.BASELINE, code_or_config_hash="abc123")
        mv = ModelVersion(
            backbone_identifier="test-backbone",
            prompt_or_weight_hash="hash-1",
            knowledge_cutoff=utc(-30),
            parent_strategy_version=sv.version_id,
        )
        self.assertEqual(mv.parent_strategy_version, sv.version_id)

    def test_configuration_version_and_risk_rule_version(self):
        cv = ConfigurationVersion(
            values={"max_exposure_pct": 5}, set_by="operator", effective_from=utc()
        )
        self.assertEqual(cv.values["max_exposure_pct"], 5)
        rrv = RiskRuleVersion(rule_set_hash="rules-v1", effective_from=utc())
        self.assertTrue(rrv.version_id)

    def test_experiment_and_evaluation_run(self):
        split = SplitSpec(
            train_start=utc(-1000),
            train_end=utc(-400),
            validation_start=utc(-399),
            validation_end=utc(-200),
            test_start=utc(-199),
            test_end=utc(0),
        )
        exp = Experiment(
            hypothesis="momentum beats buy-and-hold after costs",
            candidate_strategy_version="strat-candidate",
            baseline_strategy_versions=("strat-baseline",),
            evaluation_window=split,
            pre_registered_criteria="must beat baseline net-of-cost Sharpe",
        )
        ccr = ContaminationCheckResult(passed=True, detail="no training-data overlap")
        run = EvaluationRun(
            experiment_id=exp.experiment_id,
            data_version="ds-1",
            split=split,
            contamination_check=ccr,
            pbo_cscv_correction_applied=True,
            regime_segmented_results={"rising": {"sharpe": 1.1}},
            passed_pre_registered_criteria=True,
        )
        self.assertEqual(run.experiment_id, exp.experiment_id)

    def test_promotion_candidate_undecided(self):
        pc = PromotionCandidate(experiment_id="exp-1", evaluation_run_id="run-1")
        self.assertFalse(pc.is_decided())

    def test_autonomy_level(self):
        al = AutonomyLevel(level=1, set_by="operator", effective_from=utc())
        self.assertEqual(al.name, "Supervised")
        self.assertTrue(al.is_current())
        closed = al.closed(effective_to=utc(1))
        self.assertFalse(closed.is_current())
        # closing must not mutate the original record (append-only discipline)
        self.assertTrue(al.is_current())


if __name__ == "__main__":
    unittest.main()
