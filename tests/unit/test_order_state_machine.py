"""Order state machine (Stage 3 §9) — every valid transition succeeds and
leaves an append-only history record; every listed invalid transition
raises `InvalidOrderTransition` and leaves state unchanged.
"""

import unittest

from domain.models import InvalidOrderTransition, Order, OrderState


class TestOrderStateMachineValidTransitions(unittest.TestCase):
    def test_full_happy_path_market_buy(self):
        order = Order(order_request_id="req-1")
        self.assertEqual(order.state, OrderState.CANDIDATE)

        order.transition_to(OrderState.APPROVED)
        self.assertEqual(order.state, OrderState.APPROVED)

        order.transition_to(OrderState.SUBMITTED)
        self.assertEqual(order.state, OrderState.SUBMITTED)

        order.transition_to(OrderState.ACKNOWLEDGED)
        self.assertEqual(order.state, OrderState.ACKNOWLEDGED)

        order.transition_to(OrderState.FILLED)
        self.assertEqual(order.state, OrderState.FILLED)
        self.assertTrue(order.is_terminal())
        self.assertEqual(len(order.state_history), 4)

    def test_partial_fill_then_complete(self):
        order = Order(order_request_id="req-1")
        order.transition_to(OrderState.APPROVED)
        order.transition_to(OrderState.SUBMITTED)
        order.transition_to(OrderState.ACKNOWLEDGED)
        order.transition_to(OrderState.PARTIALLY_FILLED)
        self.assertFalse(order.is_terminal())
        order.transition_to(OrderState.FILLED)
        self.assertTrue(order.is_terminal())

    def test_partial_fill_then_cancel_remainder(self):
        order = Order(order_request_id="req-1")
        order.transition_to(OrderState.APPROVED)
        order.transition_to(OrderState.SUBMITTED)
        order.transition_to(OrderState.ACKNOWLEDGED)
        order.transition_to(OrderState.PARTIALLY_FILLED)
        order.transition_to(OrderState.CANCELLED)
        self.assertTrue(order.is_terminal())

    def test_broker_rejects_after_submission(self):
        order = Order(order_request_id="req-1")
        order.transition_to(OrderState.APPROVED)
        order.transition_to(OrderState.SUBMITTED)
        order.transition_to(OrderState.REJECTED)
        self.assertTrue(order.is_terminal())

    def test_broker_rejects_after_acknowledgement(self):
        order = Order(order_request_id="req-1")
        order.transition_to(OrderState.APPROVED)
        order.transition_to(OrderState.SUBMITTED)
        order.transition_to(OrderState.ACKNOWLEDGED)
        order.transition_to(OrderState.REJECTED)
        self.assertTrue(order.is_terminal())

    def test_ambiguous_response_routes_to_reconciliation_required(self):
        order = Order(order_request_id="req-1")
        order.transition_to(OrderState.APPROVED)
        order.transition_to(OrderState.SUBMITTED)
        order.transition_to(OrderState.RECONCILIATION_REQUIRED)
        self.assertFalse(order.is_terminal())  # resolvable, not a true dead end

    def test_reconciliation_required_can_resolve_to_filled(self):
        order = Order(order_request_id="req-1")
        order.transition_to(OrderState.APPROVED)
        order.transition_to(OrderState.SUBMITTED)
        order.transition_to(OrderState.RECONCILIATION_REQUIRED)
        order.transition_to(OrderState.FILLED)
        self.assertTrue(order.is_terminal())

    def test_state_history_is_append_only_and_ordered(self):
        order = Order(order_request_id="req-1")
        order.transition_to(OrderState.APPROVED)
        order.transition_to(OrderState.SUBMITTED)
        history = order.state_history
        self.assertEqual(history[0].from_state, OrderState.CANDIDATE)
        self.assertEqual(history[0].to_state, OrderState.APPROVED)
        self.assertEqual(history[1].from_state, OrderState.APPROVED)
        self.assertEqual(history[1].to_state, OrderState.SUBMITTED)
        # returned tuple is a snapshot; mutating it must not be possible
        with self.assertRaises(AttributeError):
            history.append("anything")  # tuples have no .append

    def test_broker_order_id_can_be_set_once(self):
        order = Order(order_request_id="req-1")
        order.set_broker_order_id("BROKER-XYZ")
        self.assertEqual(order.broker_order_id, "BROKER-XYZ")

    def test_broker_order_id_cannot_be_silently_overwritten(self):
        order = Order(order_request_id="req-1")
        order.set_broker_order_id("BROKER-XYZ")
        with self.assertRaises(ValueError):
            order.set_broker_order_id("BROKER-DIFFERENT")


class TestOrderStateMachineInvalidTransitions(unittest.TestCase):
    """Explicitly-named invalid transitions from the implementation prompt."""

    def test_candidate_to_filled_fails(self):
        order = Order(order_request_id="req-1")
        with self.assertRaises(InvalidOrderTransition):
            order.transition_to(OrderState.FILLED)
        self.assertEqual(order.state, OrderState.CANDIDATE)  # state unchanged
        self.assertEqual(order.state_history, ())  # no history entry was recorded

    def test_candidate_to_acknowledged_fails(self):
        order = Order(order_request_id="req-1")
        with self.assertRaises(InvalidOrderTransition):
            order.transition_to(OrderState.ACKNOWLEDGED)
        self.assertEqual(order.state, OrderState.CANDIDATE)

    def test_approved_to_filled_fails(self):
        order = Order(order_request_id="req-1")
        order.transition_to(OrderState.APPROVED)
        with self.assertRaises(InvalidOrderTransition):
            order.transition_to(OrderState.FILLED)
        self.assertEqual(order.state, OrderState.APPROVED)  # state unchanged
        self.assertEqual(len(order.state_history), 1)  # only the valid transition recorded

    def test_terminal_states_accept_no_further_transitions(self):
        order = Order(order_request_id="req-1")
        order.transition_to(OrderState.APPROVED)
        order.transition_to(OrderState.SUBMITTED)
        order.transition_to(OrderState.ACKNOWLEDGED)
        order.transition_to(OrderState.FILLED)
        for target in OrderState:
            if target == order.state:
                continue
            with self.assertRaises(InvalidOrderTransition):
                order.transition_to(target)

    def test_cannot_skip_approval_straight_to_submitted(self):
        order = Order(order_request_id="req-1")
        with self.assertRaises(InvalidOrderTransition):
            order.transition_to(OrderState.SUBMITTED)

    def test_order_cannot_be_constructed_in_a_non_candidate_state(self):
        with self.assertRaises(ValueError):
            Order(order_request_id="req-1", state=OrderState.FILLED)


if __name__ == "__main__":
    unittest.main()
