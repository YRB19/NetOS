"""Slice 6 — SimulatedBrokerAdapter. SYNTHETIC; offline; no credentials."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from domain.models.enums import Action, OrderState
from domain.models.order import InvalidOrderTransition
from domain.models.order_request import OrderRequest, OrderType
from risk_execution.broker.adapters.simulated import SimulatedBrokerAdapter
from risk_execution.broker.interface import (
    BrokerOperationNotSupported,
    BrokerRequestError,
    CredentialsNotSupported,
    order_id_for_idempotency_key,
)
from tests.unit._pipeline_helpers import broker_config

T0 = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
T1 = T0 + timedelta(days=1)
A = "INE001X00001"


def req(key="k1", side=Action.BUY, qty=100.0, otype=OrderType.MARKET, inst=A) -> OrderRequest:
    return OrderRequest(instrument_id=inst, side=side, quantity=qty, order_type=otype,
                        risk_decision_id="risk_1", idempotency_key=key)  # fmt: skip


def broker(**cfg):
    b = SimulatedBrokerAdapter(broker_config(**cfg))
    s = b.authenticate()
    b.set_simulated_time(T0)
    return b, s


def states(st):
    return [h.to_state for h in st.state_history]


class SimulatedBrokerTests(unittest.TestCase):
    def test_no_credentials_ever(self):
        b = SimulatedBrokerAdapter(broker_config())
        for cred in ("token", {"api_key": "x"}, b""):
            with self.assertRaises(CredentialsNotSupported):
                b.authenticate(cred)
        self.assertTrue(b.authenticate().simulated)

    def test_valid_request_walks_the_existing_state_machine(self):
        b, s = broker()
        st = b.place_order(s, req())
        self.assertEqual(states(st), [OrderState.APPROVED, OrderState.SUBMITTED, OrderState.ACKNOWLEDGED])
        fills = b.advance(T1, {A: Decimal("50")})
        self.assertEqual(len(fills), 1)
        st = b.get_order_status(s, st.broker_order_id)
        self.assertIs(st.state, OrderState.FILLED)
        self.assertEqual((st.filled_quantity, st.remaining_quantity), (100, 0))
        f = fills[0]
        self.assertEqual((f.fill.quantity, f.fill.price, f.state_after), (100.0, 50.0, OrderState.FILLED))
        self.assertEqual((f.adapter_id, f.risk_decision_id, f.idempotency_key), ("simulated-broker", "risk_1", "k1"))
        self.assertGreater(f.charges.total_cost, 0)

    def test_deterministic_ids_and_repeat_simulation(self):
        def run():
            b, s = broker()
            st = b.place_order(s, req())
            fills = b.advance(T1, {A: Decimal("50")})
            return st.broker_order_id, st.order_id, fills[0].fill.fill_id, b.ledger_snapshot()
        self.assertEqual(run(), run())
        self.assertEqual(run()[1], order_id_for_idempotency_key("k1"))

    def test_not_filled_before_next_bar(self):
        b, s = broker()
        b.place_order(s, req())
        self.assertEqual(b.advance(T0, {A: Decimal("50")}), ())  # same timestamp: no fill (NEXT_BAR_OPEN)

    def test_ledger_cash_and_positions(self):
        b, s = broker()
        b.place_order(s, req())
        f = b.advance(T1, {A: Decimal("50")})[0]
        led = b.ledger_snapshot()
        self.assertEqual(led["positions"], {A: 100})
        self.assertEqual(led["cash"], Decimal(1_000_000) - Decimal(5000) - f.charges.total_cost)
        self.assertEqual(b.get_positions(s)[0].quantity, 100.0)
        self.assertEqual(b.get_account_state(s).cash_balance, led["cash"])

    def test_invalid_request_object_refused_without_creating_an_order(self):
        b, s = broker()
        for bad in (None, "BUY 100", {"instrument_id": A}):
            with self.assertRaises(BrokerRequestError):
                b.place_order(s, bad)  # type: ignore[arg-type]
        self.assertEqual(b.get_fills(s), ())

    def test_unsupported_order_type_and_fractional_quantity_rejected(self):
        b, s = broker()
        lim = b.place_order(s, OrderRequest(instrument_id=A, side=Action.BUY, quantity=10.0, order_type=OrderType.LIMIT,
                                            risk_decision_id="r", idempotency_key="k2", limit_price=10.0))
        self.assertIs(lim.state, OrderState.REJECTED)
        self.assertIn("unsupported order type", lim.last_response)
        frac = b.place_order(s, req("k3", qty=10.5))
        self.assertIs(frac.state, OrderState.REJECTED)
        self.assertEqual(b.advance(T1, {A: Decimal("50")}), ())

    def test_duplicate_submission_is_idempotent(self):
        b, s = broker()
        first = b.place_order(s, req())
        again = b.place_order(s, req())
        self.assertTrue(again.duplicate)
        self.assertEqual(first.broker_order_id, again.broker_order_id)
        self.assertEqual(b.duplicate_submissions, 1)
        self.assertEqual(len(b.advance(T1, {A: Decimal("50")})), 1)
        self.assertEqual(b.ledger_snapshot()["positions"], {A: 100})  # filled once, not twice

    def test_insufficient_cash_rejects_at_fill(self):
        b, s = broker(initial_cash=Decimal("1000"))
        st = b.place_order(s, req())
        b.advance(T1, {A: Decimal("50")})
        st = b.get_order_status(s, st.broker_order_id)
        self.assertIs(st.state, OrderState.REJECTED)
        self.assertIn("insufficient cash", st.last_response)
        self.assertEqual(b.ledger_snapshot()["cash"], Decimal(1000))

    def test_sell_more_than_held_rejected(self):
        b, s = broker()
        st = b.place_order(s, req(side=Action.SELL))
        b.advance(T1, {A: Decimal("50")})
        self.assertIs(b.get_order_status(s, st.broker_order_id).state, OrderState.REJECTED)

    def test_partial_fills_are_deterministic_then_cancel_remainder(self):
        b, s = broker(max_fill_fraction_per_bar=Decimal("0.4"))
        st = b.place_order(s, req(qty=100.0))
        f1 = b.advance(T1, {A: Decimal("50")})
        self.assertEqual(f1[0].fill.quantity, 40.0)
        self.assertIs(f1[0].state_after, OrderState.PARTIALLY_FILLED)
        st = b.cancel_order(s, st.broker_order_id)
        self.assertIs(st.state, OrderState.CANCELLED)
        self.assertEqual((st.filled_quantity, st.remaining_quantity), (40, 60))
        self.assertEqual(b.advance(T1 + timedelta(days=1), {A: Decimal("50")}), ())

    def test_partial_fills_complete_over_bars(self):
        b, s = broker(max_fill_fraction_per_bar=Decimal("0.4"))
        st = b.place_order(s, req(qty=100.0))
        q = [f.fill.quantity for k in (1, 2, 3, 4) for f in b.advance(T0 + timedelta(days=k), {A: Decimal("50")})]
        self.assertEqual(q, [40.0, 40.0, 20.0])  # fixed fraction of the ORIGINAL quantity per bar
        st = b.get_order_status(s, st.broker_order_id)
        self.assertIs(st.state, OrderState.FILLED)
        self.assertEqual(states(st).count(OrderState.PARTIALLY_FILLED), 1)  # no illegal self-transition

    def test_cancel_of_unfilled_acknowledged_order_is_an_invalid_transition(self):
        b, s = broker()
        st = b.place_order(s, req())
        with self.assertRaises(InvalidOrderTransition):
            b.cancel_order(s, st.broker_order_id)
        self.assertIs(b.get_order_status(s, st.broker_order_id).state, OrderState.ACKNOWLEDGED)

    def test_reconciliation_required_orders_are_never_filled(self):
        b, s = broker()
        st = b.place_order(s, req())
        st = b.inject_ambiguous_response(st.broker_order_id, "timeout")
        self.assertIs(st.state, OrderState.RECONCILIATION_REQUIRED)
        self.assertEqual(b.advance(T1, {A: Decimal("50")}), ())
        self.assertEqual(b.ledger_snapshot()["positions"], {})
        # resolution-only transition permitted by the existing contract
        self.assertIs(b.cancel_order(s, st.broker_order_id).state, OrderState.CANCELLED)

    def test_filled_order_cannot_be_transitioned_again(self):
        b, s = broker()
        st = b.place_order(s, req())
        b.advance(T1, {A: Decimal("50")})
        with self.assertRaises(InvalidOrderTransition):
            b.inject_ambiguous_response(st.broker_order_id)

    def test_sells_execute_before_buys_in_the_same_bar(self):
        b, s = broker(initial_cash=Decimal("100000"))
        b.place_order(s, req("buy1", Action.BUY, 1900.0, inst=A))
        b.advance(T1, {A: Decimal("50")})
        t2 = T1 + timedelta(days=1)
        b.set_simulated_time(T1)
        b.place_order(s, req("buy2", Action.BUY, 1900.0, inst="INE002X00002"))
        b.place_order(s, req("sell1", Action.SELL, 1900.0, inst=A))
        fills = b.advance(t2, {A: Decimal("50"), "INE002X00002": Decimal("50")})
        self.assertEqual([f.idempotency_key for f in fills], ["sell1", "buy2"])

    def test_modify_unsupported_and_unknown_order_and_clock(self):
        b, s = broker()
        with self.assertRaises(BrokerOperationNotSupported):
            b.modify_order(s, "x", {})
        with self.assertRaises(BrokerRequestError):
            b.get_order_status(s, "nope")
        with self.assertRaises(ValueError):
            b.set_simulated_time(T0 - timedelta(days=1))
        fresh = SimulatedBrokerAdapter(broker_config())
        with self.assertRaises(BrokerRequestError):
            fresh.place_order(fresh.authenticate(), req())  # no wall-clock fallback

    def test_invalid_config_refused(self):
        for over in (dict(initial_cash=Decimal("0")), dict(max_fill_fraction_per_bar=Decimal("0")),
                     dict(max_fill_fraction_per_bar=Decimal("1.5")), dict(cost_schedule_version="")):
            with self.assertRaises(ValueError):
                SimulatedBrokerAdapter(broker_config(**over))


if __name__ == "__main__":
    unittest.main()
