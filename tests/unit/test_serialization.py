"""object -> serialized form -> object preserves the relevant information
deterministically (Definition of Done: Serialization).

Also checks that `to_serializable` output is actually JSON-safe (a common
way a "deterministic serialization representation" claim quietly breaks:
some field survives as a non-JSON-safe Python object like a raw Enum or
datetime).
"""

import json
import unittest

from domain.models import (
    Action,
    CandidateTrade,
    DataSourceRef,
    DecisionRecord,
    DecisionRecordBuilder,
    FillType,
    Order,
    OrderState,
    PortfolioState,
    PortfolioStateSource,
    Position,
    TerminalState,
    UncertaintyBand,
)
from domain.models.order_request import Fill
from domain.models.serialization import from_serializable, order_from_serializable, to_serializable
from tests.unit._helpers import utc


class TestSerializationRoundTrip(unittest.TestCase):
    def _assert_json_safe(self, blob):
        # Must not raise — every value must be a JSON primitive.
        json.dumps(blob)

    def test_candidate_trade_round_trip(self):
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
        blob = to_serializable(ct)
        self._assert_json_safe(blob)
        ct2 = from_serializable(CandidateTrade, blob)
        self.assertEqual(ct, ct2)

    def test_candidate_trade_round_trip_with_none_optionals(self):
        ct = CandidateTrade(
            instrument_id="X",
            timestamp=utc(),
            action=Action.HOLD,
            confidence=0.5,
            rationale="r",
            input_snapshot_id="s",
            strategy_version_id="v",
        )
        blob = to_serializable(ct)
        self._assert_json_safe(blob)
        ct2 = from_serializable(CandidateTrade, blob)
        self.assertEqual(ct, ct2)
        self.assertIsNone(ct2.size_hint)
        self.assertIsNone(ct2.uncertainty_band)

    def test_position_and_portfolio_state_round_trip(self):
        pos = Position(instrument_id="X", quantity=10, avg_cost=100.0)
        ps = PortfolioState(
            as_of_timestamp=utc(),
            positions=(pos,),
            cash_balance=1000.0,
            source=PortfolioStateSource.BROKER_CONFIRMED,
        )
        blob = to_serializable(ps)
        self._assert_json_safe(blob)
        ps2 = from_serializable(PortfolioState, blob)
        self.assertEqual(ps, ps2)

    def test_fill_round_trip(self):
        fill = Fill(
            order_id="order-1", quantity=10, price=101.5, timestamp=utc(), fill_type=FillType.FULL
        )
        blob = to_serializable(fill)
        self._assert_json_safe(blob)
        fill2 = from_serializable(Fill, blob)
        self.assertEqual(fill, fill2)

    def test_decision_record_round_trip_with_nested_tuples(self):
        drb = DecisionRecordBuilder(
            instrument_id="X",
            cycle_timestamp=utc(),
            autonomy_level=1,
            risk_rule_version_id="rr-1",
            config_version_id="cfg-1",
        )
        drb.with_snapshot(
            "snap-1",
            [DataSourceRef("feed-a", "v1", utc()), DataSourceRef("feed-b", "v2", utc())],
        )
        dr = drb.finalize(TerminalState.NO_CANDIDATE)
        blob = to_serializable(dr)
        self._assert_json_safe(blob)
        dr2 = from_serializable(DecisionRecord, blob)
        self.assertEqual(dr, dr2)
        self.assertEqual(len(dr2.data_sources), 2)

    def test_order_round_trip_via_dedicated_reconstructor(self):
        order = Order(order_request_id="req-1")
        order.transition_to(OrderState.APPROVED)
        order.transition_to(OrderState.SUBMITTED)
        order.set_broker_order_id("BROKER-XYZ")
        order.transition_to(OrderState.ACKNOWLEDGED)
        order.transition_to(OrderState.FILLED)

        blob = to_serializable(order)
        self._assert_json_safe(blob)

        order2 = order_from_serializable(blob)
        self.assertEqual(order2.state, order.state)
        self.assertEqual(order2.broker_order_id, order.broker_order_id)
        self.assertEqual(order2.state_history, order.state_history)

    def test_serialized_blob_contains_type_tag(self):
        ct = CandidateTrade(
            instrument_id="X",
            timestamp=utc(),
            action=Action.HOLD,
            confidence=0.5,
            rationale="r",
            input_snapshot_id="s",
            strategy_version_id="v",
        )
        blob = to_serializable(ct)
        self.assertEqual(blob["__type__"], "CandidateTrade")


if __name__ == "__main__":
    unittest.main()
