"""Objects Stage 3 §2 marks immutable must actually be immutable.

Every `@dataclass(frozen=True)` domain model raises `dataclasses.FrozenInstanceError`
(a `ValueError`/`AttributeError` subtype — specifically it's a subclass of
`AttributeError` in the stdlib) on any attempted attribute assignment after
construction. This file asserts that directly, rather than trusting the
decorator was applied correctly by inspection alone.
"""

import dataclasses
import unittest

from domain.models import (
    Action,
    ActualCost,
    CandidateTrade,
    ConfigurationVersion,
    CostEstimate,
    DecisionRecordBuilder,
    FeatureSnapshot,
    Instrument,
    MarketData,
    ModelVersion,
    Plane2Type,
    RiskCheckResult,
    RiskDecision,
    RiskRuleVersion,
    RiskVerdict,
    StrategyVersion,
    TerminalState,
)
from tests.unit._helpers import utc


class TestImmutability(unittest.TestCase):
    def _assert_frozen(self, obj, field_name, new_value):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            setattr(obj, field_name, new_value)

    def test_instrument_is_frozen(self):
        i = Instrument(isin="X", symbol="Y", exchange="NSE", lot_size=1)
        self._assert_frozen(i, "symbol", "Z")

    def test_market_data_is_frozen(self):
        md = MarketData(
            instrument_id="X",
            timestamp=utc(),
            open=1,
            high=2,
            low=1,
            close=1.5,
            volume=1,
            source="s",
            ingestion_time=utc(),
            data_snapshot_version="v1",
        )
        self._assert_frozen(md, "close", 999.0)

    def test_feature_snapshot_is_frozen(self):
        fs = FeatureSnapshot(
            instrument_id="X",
            decision_timestamp=utc(),
            feature_values={"a": 1.0},
            feature_set_version="fs-1",
        )
        self._assert_frozen(fs, "instrument_id", "Y")

    def test_candidate_trade_is_frozen(self):
        ct = CandidateTrade(
            size_hint=0.5,
            instrument_id="X",
            timestamp=utc(),
            action=Action.HOLD,
            confidence=0.5,
            rationale="r",
            input_snapshot_id="s",
            strategy_version_id="v",
        )
        self._assert_frozen(ct, "confidence", 0.99)
        self._assert_frozen(ct, "rationale", "different")
        self._assert_frozen(ct, "action", Action.BUY)

    def test_cost_estimate_is_frozen(self):
        ce = CostEstimate(
            instrument_id="X",
            brokerage=1,
            stt=1,
            exchange_charges=1,
            sebi_fees=1,
            gst=1,
            stamp_duty=1,
            estimated_slippage=1,
            cost_model_version="cm-1",
        )
        self._assert_frozen(ce, "brokerage", 999)

    def test_actual_cost_is_frozen(self):
        ac = ActualCost(
            order_id="o1",
            brokerage=1,
            stt=1,
            exchange_charges=1,
            sebi_fees=1,
            gst=1,
            stamp_duty=1,
            realized_slippage=0,
            cost_model_version="cm-1",
        )
        self._assert_frozen(ac, "realized_slippage", 999)

    def test_risk_decision_is_frozen(self):
        rd = RiskDecision(
            candidate_trade_id="c1",
            checks_evaluated=(RiskCheckResult("RR-1", True, "ok"),),
            final_verdict=RiskVerdict.APPROVE,
            risk_rule_version_id="rr-1",
            approved_qty=1,
        )
        self._assert_frozen(rd, "final_verdict", RiskVerdict.REJECT)

    def test_decision_record_is_frozen(self):
        drb = DecisionRecordBuilder(
            instrument_id="X",
            cycle_timestamp=utc(),
            autonomy_level=0,
            risk_rule_version_id="rr-1",
            config_version_id="cfg-1",
        )
        drb.with_snapshot("snap-1", [])
        dr = drb.finalize(TerminalState.NO_CANDIDATE)
        self._assert_frozen(dr, "terminal_state", TerminalState.FILLED)

    def test_model_version_is_frozen(self):
        sv = StrategyVersion(plane2_type=Plane2Type.BASELINE, code_or_config_hash="abc")
        mv = ModelVersion(
            backbone_identifier="b",
            prompt_or_weight_hash="h",
            knowledge_cutoff=utc(-10),
            parent_strategy_version=sv.version_id,
        )
        self._assert_frozen(mv, "backbone_identifier", "different")

    def test_configuration_version_is_frozen(self):
        cv = ConfigurationVersion(values={"a": 1}, set_by="operator", effective_from=utc())
        self._assert_frozen(cv, "set_by", "someone-else")

    def test_configuration_version_values_mapping_is_read_only(self):
        cv = ConfigurationVersion(values={"a": 1}, set_by="operator", effective_from=utc())
        with self.assertRaises(TypeError):
            cv.values["a"] = 2  # MappingProxyType must reject item assignment

    def test_risk_rule_version_is_frozen(self):
        rrv = RiskRuleVersion(rule_set_hash="rules-v1", effective_from=utc())
        self._assert_frozen(rrv, "rule_set_hash", "different")

    def test_decision_record_builder_finalize_is_single_use(self):
        drb = DecisionRecordBuilder(
            instrument_id="X",
            cycle_timestamp=utc(),
            autonomy_level=0,
            risk_rule_version_id="rr-1",
            config_version_id="cfg-1",
        )
        drb.with_snapshot("snap-1", [])
        drb.finalize(TerminalState.NO_CANDIDATE)
        with self.assertRaises(ValueError):
            drb.finalize(TerminalState.NO_CANDIDATE)  # a builder finalizes exactly once


if __name__ == "__main__":
    unittest.main()
