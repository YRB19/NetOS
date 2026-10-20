"""Slice 7 — order lifecycle: state machine, idempotency, failure recovery. SYNTHETIC / offline."""

from __future__ import annotations

import json
import unittest
from decimal import Decimal

from domain.models.enums import Action, FillType, OrderState, RiskVerdict
from domain.models.order_request import OrderType
from risk_execution.order_lifecycle import (
    ApprovalError,
    BrokerEvent,
    EventKind,
    EventStatus,
    ExecutionHalted,
    OrderLifecycleManager,
    SubmissionStatus,
    SubmitOutcome,
    UnresolvedSubmission,
)
from shared.versioning.identifiers import new_id
from tests.unit._lifecycle_helpers import (
    A,
    RRV,
    Rig,
    T0,
    day,
    decision,
    fill_event,
    request_for,
    synthetic_fill,
)

S = OrderState


class GroupA_StateMachine(unittest.TestCase):
    def test_happy_path_ack_then_fill(self):
        r = Rig()
        req, _rd, sub = r.submit()
        self.assertIs(sub.outcome, SubmitOutcome.ACCEPTED)
        self.assertIs(sub.record.order.state, S.ACKNOWLEDGED)
        for ev in r.fill_events(r.advance(1)):
            self.assertIs(r.mgr.apply_event(ev).status, EventStatus.APPLIED)
        rec = r.mgr.record(req.idempotency_key)
        self.assertIs(rec.order.state, S.FILLED)
        self.assertEqual((rec.filled_qty, rec.consideration), (100, Decimal(100) * Decimal("50")))
        self.assertFalse(r.mgr.halted)

    def test_partial_fills_accumulate_then_complete(self):
        r = Rig(max_fill_fraction_per_bar=Decimal("0.4"))
        req, _, _ = r.submit()
        states = []
        for n in (1, 2, 3):
            for ev in r.fill_events(r.advance(n)):
                r.mgr.apply_event(ev)
            states.append(r.mgr.record(req.idempotency_key).order.state)
        self.assertEqual(states, [S.PARTIALLY_FILLED, S.PARTIALLY_FILLED, S.FILLED])
        rec = r.mgr.record(req.idempotency_key)
        self.assertEqual((rec.filled_qty, len(rec.applied_fills)), (100, 3))

    def test_partial_then_cancel_preserves_fills_and_provenance(self):
        r = Rig(max_fill_fraction_per_bar=Decimal("0.4"))
        req, _, sub = r.submit()
        for ev in r.fill_events(r.advance(1)):
            r.mgr.apply_event(ev)
        bid = sub.record.order.broker_order_id
        r.broker.cancel_order(r.session, bid)
        res = r.mgr.apply_event(BrokerEvent(EventKind.CANCEL_CONFIRMED, bid, req.idempotency_key))
        self.assertIs(res.status, EventStatus.APPLIED)
        rec = r.mgr.record(req.idempotency_key)
        self.assertIs(rec.order.state, S.CANCELLED)
        self.assertEqual(rec.filled_qty, 40)
        self.assertEqual([h.to_state for h in rec.order.state_history][-2:], [S.PARTIALLY_FILLED, S.CANCELLED])

    def test_cancel_request_is_not_evidence_of_cancellation(self):
        r = Rig(max_fill_fraction_per_bar=Decimal("0.4"))
        req, _, _ = r.submit()
        for ev in r.fill_events(r.advance(1)):
            r.mgr.apply_event(ev)
        rec = r.mgr.request_cancel(req.idempotency_key, r.broker, r.session)
        self.assertTrue(rec.cancel_requested)
        self.assertIs(rec.order.state, S.PARTIALLY_FILLED)  # only a CANCEL_CONFIRMED event changes state

    def test_failed_cancel_request_proves_nothing(self):
        r = Rig()
        req, _, _ = r.submit()
        rec = r.mgr.request_cancel(req.idempotency_key, r.broker, r.session)  # unfilled ACK: broker refuses
        self.assertIs(rec.order.state, S.ACKNOWLEDGED)
        self.assertTrue(any(e["status"] == "UNCONFIRMED" for e in rec.event_log))

    def test_fill_after_cancel_request_but_before_confirmation_is_applied(self):
        r = Rig()
        req, _, _ = r.submit()
        r.mgr.request_cancel(req.idempotency_key, r.broker, r.session)
        for ev in r.fill_events(r.advance(1)):
            self.assertIs(r.mgr.apply_event(ev).status, EventStatus.APPLIED)
        self.assertIs(r.mgr.record(req.idempotency_key).order.state, S.FILLED)

    def test_late_fill_after_recorded_cancellation_is_quarantined_not_accounted(self):
        r = Rig(max_fill_fraction_per_bar=Decimal("0.4"))
        req, _, sub = r.submit()
        for ev in r.fill_events(r.advance(1)):
            r.mgr.apply_event(ev)
        r.mgr.apply_event(BrokerEvent(EventKind.CANCEL_CONFIRMED, sub.record.order.broker_order_id, req.idempotency_key))
        late = fill_event(req.idempotency_key, synthetic_fill(req.idempotency_key, 10, 50))
        res = r.mgr.apply_event(late)
        rec = r.mgr.record(req.idempotency_key)
        self.assertIs(res.status, EventStatus.QUARANTINED)
        self.assertIs(rec.order.state, S.CANCELLED)       # terminal state not reopened
        self.assertEqual(rec.filled_qty, 40)               # accounting unchanged
        self.assertTrue(r.mgr.halted)
        self.assertEqual(len(rec.quarantined), 1)

    def test_cancel_confirmed_on_unfilled_order_escalates_because_contract_has_no_edge(self):
        r = Rig()
        req, _, sub = r.submit()
        res = r.mgr.apply_event(BrokerEvent(EventKind.CANCEL_CONFIRMED, sub.record.order.broker_order_id, req.idempotency_key))
        self.assertIs(res.status, EventStatus.QUARANTINED)
        self.assertIs(r.mgr.record(req.idempotency_key).order.state, S.RECONCILIATION_REQUIRED)
        self.assertTrue(r.mgr.halted)

    def test_cancel_confirmed_on_filled_order_is_a_conflict(self):
        r = Rig()
        req, _, sub = r.submit()
        for ev in r.fill_events(r.advance(1)):
            r.mgr.apply_event(ev)
        res = r.mgr.apply_event(BrokerEvent(EventKind.CANCEL_CONFIRMED, sub.record.order.broker_order_id, req.idempotency_key))
        self.assertIs(res.status, EventStatus.QUARANTINED)
        self.assertIs(r.mgr.record(req.idempotency_key).order.state, S.FILLED)
        self.assertEqual(r.mgr.record(req.idempotency_key).filled_qty, 100)

    def test_broker_rejection_is_distinct_from_local_failure_and_keeps_reason(self):
        r = Rig()
        rd = decision()
        from domain.models.order_request import OrderRequest
        # LIMIT orders are rejected by the simulator (broker-side rejection)
        req = OrderRequest(A, Action.BUY, 10.0, OrderType.LIMIT, rd.risk_decision_id, 50.0)
        sub = r.mgr.submit(req, rd, r.broker, r.session)
        self.assertIs(sub.outcome, SubmitOutcome.REJECTED_BY_BROKER)
        rec = sub.record
        self.assertIs(rec.order.state, S.REJECTED)
        self.assertIs(rec.submission, SubmissionStatus.REJECTED_BY_BROKER)
        self.assertIn("LIMIT", rec.failure)

    def test_local_adapter_refusal_is_a_distinct_local_failure_and_never_resent(self):
        r = Rig()
        rd = decision()
        req = request_for(rd, 10.0)
        r.broker.set_simulated_time(T0)
        # a session the broker refuses structurally -> BrokerRequestError (no order created)
        from risk_execution.broker.interface import BrokerSession
        bad = BrokerSession("x", "y", False)
        sub = r.mgr.submit(req, rd, r.broker, bad)
        self.assertIs(sub.outcome, SubmitOutcome.LOCAL_FAILURE)
        self.assertIs(sub.record.order.state, S.APPROVED)           # never SUBMITTED
        self.assertEqual(r.broker.order_statuses(r.session), {})
        again = r.mgr.submit(req, rd, r.broker, r.session)
        self.assertIs(again.outcome, SubmitOutcome.DUPLICATE_NOT_RESENT)
        self.assertEqual(r.broker.order_statuses(r.session), {})

    def test_terminal_state_is_not_reopened_by_repeated_events(self):
        r = Rig()
        req, _, _ = r.submit()
        evs = r.fill_events(r.advance(1))
        r.mgr.apply_event(evs[0])
        for _ in range(3):
            self.assertIs(r.mgr.apply_event(evs[0]).status, EventStatus.DUPLICATE_IGNORED)
        self.assertEqual(r.mgr.record(req.idempotency_key).filled_qty, 100)

    def test_reject_after_fills_is_contradictory_and_preserves_fills(self):
        r = Rig(max_fill_fraction_per_bar=Decimal("0.4"))
        req, _, sub = r.submit()
        for ev in r.fill_events(r.advance(1)):
            r.mgr.apply_event(ev)
        res = r.mgr.apply_event(BrokerEvent(EventKind.REJECTED, sub.record.order.broker_order_id, req.idempotency_key))
        rec = r.mgr.record(req.idempotency_key)
        self.assertIs(res.status, EventStatus.QUARANTINED)
        self.assertIs(rec.order.state, S.RECONCILIATION_REQUIRED)
        self.assertEqual(rec.filled_qty, 40)

    def test_invalid_transitions_never_change_ledgers(self):
        r = Rig()
        req, _, sub = r.submit()
        for ev in r.fill_events(r.advance(1)):
            r.mgr.apply_event(ev)
        before = r.mgr.record(req.idempotency_key).filled_qty
        r.mgr.apply_event(BrokerEvent(EventKind.REJECTED, sub.record.order.broker_order_id, req.idempotency_key))
        self.assertEqual(r.mgr.record(req.idempotency_key).filled_qty, before)
        self.assertIs(r.mgr.record(req.idempotency_key).order.state, S.FILLED)


class GroupA_Approval(unittest.TestCase):
    def test_veto_never_becomes_an_order(self):
        r = Rig()
        rd = decision(verdict=RiskVerdict.REJECT)
        req = request_for(rd)
        with self.assertRaises(ApprovalError):
            r.mgr.submit(req, rd, r.broker, r.session)
        self.assertEqual(r.broker.order_statuses(r.session), {})
        self.assertIsNone(r.mgr.record(req.idempotency_key))

    def test_stale_risk_rule_version_quantity_over_ceiling_and_wrong_decision_are_refused(self):
        r = Rig()
        for rd, req in (
            (decision(rrv=new_id()), None),
            (decision(qty=50.0), "over"),
            (decision(), "mismatch"),
        ):
            if req == "over":
                q = request_for(rd, 100.0)
            elif req == "mismatch":
                q = request_for(decision(), 10.0)
            else:
                q = request_for(rd, 10.0)
            with self.subTest(case=req):
                with self.assertRaises(ApprovalError):
                    r.mgr.submit(q, rd, r.broker, r.session)
        self.assertEqual(r.broker.order_statuses(r.session), {})

    def test_fractional_quantity_refused(self):
        r = Rig()
        rd = decision()
        with self.assertRaises(ApprovalError):
            r.mgr.submit(request_for(rd, 10.5), rd, r.broker, r.session)

    def test_one_approval_cannot_back_two_orders(self):
        r = Rig()
        rd = decision()
        r.mgr.submit(request_for(rd, 10.0), rd, r.broker, r.session)
        with self.assertRaises(ApprovalError):
            r.mgr.submit(request_for(rd, 10.0), rd, r.broker, r.session)

    def test_manager_requires_explicit_policy_and_clock(self):
        with self.assertRaises(ValueError):
            OrderLifecycleManager("", lambda: T0)
        with self.assertRaises(ValueError):
            OrderLifecycleManager(RRV, None)

    def test_halt_blocks_new_submissions(self):
        r = Rig()
        r.mgr.apply_event(fill_event("nope", synthetic_fill("nope", 1, 1)))  # unknown order -> halt
        rd = decision()
        with self.assertRaises(ExecutionHalted):
            r.mgr.submit(request_for(rd, 10.0), rd, r.broker, r.session)


class GroupB_Idempotency(unittest.TestCase):
    def test_duplicate_submission_creates_one_broker_order(self):
        r = Rig()
        req, rd, first = r.submit()
        again = r.mgr.submit(req, rd, r.broker, r.session)
        self.assertIs(again.outcome, SubmitOutcome.DUPLICATE_NOT_RESENT)
        self.assertEqual(len(r.broker.order_statuses(r.session)), 1)
        self.assertEqual(r.broker.duplicate_submissions, 0)  # the adapter was never even asked twice
        self.assertIs(again.record, first.record)

    def test_duplicate_ack_is_ignored(self):
        r = Rig()
        req, _, sub = r.submit()
        ev = BrokerEvent(EventKind.ACKNOWLEDGED, sub.record.order.broker_order_id, req.idempotency_key)
        self.assertIs(r.mgr.apply_event(ev).status, EventStatus.DUPLICATE_IGNORED)
        self.assertFalse(r.mgr.halted)

    def test_duplicate_fill_does_not_double_account(self):
        r = Rig(max_fill_fraction_per_bar=Decimal("0.4"))
        req, _, _ = r.submit()
        evs = r.fill_events(r.advance(1))
        self.assertIs(r.mgr.apply_event(evs[0]).status, EventStatus.APPLIED)
        for _ in range(2):
            self.assertIs(r.mgr.apply_event(evs[0]).status, EventStatus.DUPLICATE_IGNORED)
        self.assertEqual(r.mgr.record(req.idempotency_key).filled_qty, 40)

    def test_same_fill_redelivered_under_a_new_event_id_is_still_a_duplicate(self):
        r = Rig(max_fill_fraction_per_bar=Decimal("0.4"))
        req, _, _ = r.submit()
        reps = r.advance(1)
        r.mgr.apply_event(r.fill_events(reps, ["e1"])[0])
        res = r.mgr.apply_event(r.fill_events(reps, ["e2"])[0])
        self.assertIs(res.status, EventStatus.DUPLICATE_IGNORED)
        self.assertEqual(r.mgr.record(req.idempotency_key).filled_qty, 40)

    def test_same_fill_id_with_different_payload_is_a_conflict_not_a_guess(self):
        r = Rig()
        req, _, _ = r.submit()
        k = req.idempotency_key
        r.mgr.apply_event(fill_event(k, synthetic_fill(k, 40, 50, fid="fill_x")))
        res = r.mgr.apply_event(fill_event(k, synthetic_fill(k, 40, 51, fid="fill_x"), event_id="redelivery"))
        self.assertIs(res.status, EventStatus.ESCALATED)
        self.assertTrue(r.mgr.halted)
        self.assertEqual(r.mgr.record(k).filled_qty, 40)

    def test_distinct_but_identical_looking_fills_are_both_applied(self):
        r = Rig()
        req, _, _ = r.submit()
        k = req.idempotency_key
        for _ in range(2):
            self.assertIs(r.mgr.apply_event(fill_event(k, synthetic_fill(k, 40, 50))).status, EventStatus.APPLIED)
        self.assertEqual(r.mgr.record(k).filled_qty, 80)

    def test_overfill_is_quarantined(self):
        r = Rig()
        req, _, _ = r.submit()
        k = req.idempotency_key
        r.mgr.apply_event(fill_event(k, synthetic_fill(k, 80, 50)))
        res = r.mgr.apply_event(fill_event(k, synthetic_fill(k, 40, 50, FillType.FULL)))
        self.assertIs(res.status, EventStatus.QUARANTINED)
        self.assertEqual(r.mgr.record(k).filled_qty, 80)
        self.assertTrue(r.mgr.halted)

    def test_fill_type_contradiction_is_quarantined(self):
        r = Rig()
        req, _, _ = r.submit()
        k = req.idempotency_key
        res = r.mgr.apply_event(fill_event(k, synthetic_fill(k, 40, 50, FillType.FULL)))
        self.assertIs(res.status, EventStatus.QUARANTINED)
        self.assertEqual(r.mgr.record(k).filled_qty, 0)

    def test_unknown_order_event_halts(self):
        r = Rig()
        res = r.mgr.apply_event(BrokerEvent(EventKind.ACKNOWLEDGED, "SIM-unknown"))
        self.assertIs(res.status, EventStatus.UNKNOWN_ORDER)
        self.assertTrue(r.mgr.halted)

    def test_event_with_no_identity_is_invalid_and_halts(self):
        r = Rig()
        res = r.mgr.apply_event(BrokerEvent(EventKind.FILL))
        self.assertIs(res.status, EventStatus.INVALID)
        self.assertTrue(r.mgr.halted)

    def test_identity_fallbacks_when_broker_has_no_event_id(self):
        k = "ord-key"
        f = synthetic_fill(k, 10, 5, fid="fill_abc")
        self.assertEqual(fill_event(k, f).identity(), "fill:fill_abc")
        self.assertEqual(fill_event(k, f, "E9").identity(), "evt:E9")
        self.assertEqual(BrokerEvent(EventKind.ACKNOWLEDGED, "B1").identity(), "ACKNOWLEDGED:B1")
        self.assertIsNone(BrokerEvent(EventKind.ACKNOWLEDGED).identity())

    def test_fill_for_a_different_order_is_refused(self):
        r = Rig()
        r.submit()
        req2, _, _ = r.submit(qty=50.0)
        wrong = fill_event(req2.idempotency_key, synthetic_fill("some-other-key", 10, 5))
        res = r.mgr.apply_event(wrong)
        self.assertIsNot(res.status, EventStatus.APPLIED)
        self.assertEqual(r.mgr.record(req2.idempotency_key).filled_qty, 0)

    def test_stale_ack_after_progress_is_logged_not_discarded(self):
        r = Rig()
        req, _, sub = r.submit()
        for ev in r.fill_events(r.advance(1)):
            r.mgr.apply_event(ev)
        res = r.mgr.apply_event(BrokerEvent(EventKind.ACKNOWLEDGED, sub.record.order.broker_order_id,
                                            req.idempotency_key, event_id="late-ack"))
        self.assertIs(res.status, EventStatus.STALE_IGNORED)
        self.assertTrue(any(e["status"] == "STALE_IGNORED" for e in r.mgr.record(req.idempotency_key).event_log))

    def test_ack_after_rejection_is_a_conflict(self):
        r = Rig()
        rd = decision()
        from domain.models.order_request import OrderRequest
        req = OrderRequest(A, Action.BUY, 10.0, OrderType.LIMIT, rd.risk_decision_id, 50.0)
        sub = r.mgr.submit(req, rd, r.broker, r.session)
        res = r.mgr.apply_event(BrokerEvent(EventKind.ACKNOWLEDGED, sub.record.order.broker_order_id,
                                            req.idempotency_key, event_id="odd"))
        self.assertIs(res.status, EventStatus.QUARANTINED)
        self.assertTrue(r.mgr.halted)


class GroupC_FailureRecovery(unittest.TestCase):
    def test_failure_before_acceptance_is_uncertain_then_confirmed_absent_then_new_order_only(self):
        r = Rig()
        r.broker.inject_fault("FAIL_BEFORE_ACCEPT")
        req, rd, sub = r.submit()
        self.assertIs(sub.outcome, SubmitOutcome.UNCERTAIN)
        rec = sub.record
        self.assertIs(rec.submission, SubmissionStatus.SENT_UNCONFIRMED)
        self.assertIs(rec.order.state, S.SUBMITTED)
        self.assertTrue(r.mgr.halted)
        with self.assertRaises(UnresolvedSubmission):
            r.mgr.submit(req, rd, r.broker, r.session)        # no blind retry
        self.assertEqual(r.broker.order_statuses(r.session), {})
        self.assertEqual(r.mgr.resolve_uncertain_submission(req.idempotency_key, r.broker, r.session), "ABSENT_AT_BROKER")
        self.assertIs(rec.submission, SubmissionStatus.ABSENT_AT_BROKER)
        self.assertIs(rec.order.state, S.REJECTED)
        self.assertEqual(r.broker.order_statuses(r.session), {})  # still nothing: never fabricated
        self.assertTrue(r.mgr.halted)                             # resolution alone does not clear the halt
        with self.assertRaises(ExecutionHalted):
            r.submit()

    def test_failure_after_acceptance_is_reconciled_without_a_second_broker_order(self):
        r = Rig()
        r.broker.inject_fault("FAIL_AFTER_ACCEPT")
        req, rd, sub = r.submit()
        self.assertIs(sub.outcome, SubmitOutcome.UNCERTAIN)
        self.assertEqual(len(r.broker.order_statuses(r.session)), 1)   # the broker did accept it
        with self.assertRaises(UnresolvedSubmission):
            r.mgr.submit(req, rd, r.broker, r.session)
        self.assertEqual(len(r.broker.order_statuses(r.session)), 1)   # and the retry was NOT sent
        self.assertEqual(r.broker.duplicate_submissions, 0)
        out = r.mgr.resolve_uncertain_submission(req.idempotency_key, r.broker, r.session)
        self.assertIn("RECONCILED_FROM_BROKER", out)
        rec = r.mgr.record(req.idempotency_key)
        self.assertIs(rec.order.state, S.ACKNOWLEDGED)
        self.assertIs(rec.submission, SubmissionStatus.RECONCILED_FROM_BROKER)

    def test_missing_ack_then_fill_arrives_first_gives_evidence_based_acknowledgement(self):
        r = Rig()
        r.broker.inject_fault("FAIL_AFTER_ACCEPT")
        req, _, _ = r.submit()
        for ev in r.fill_events(r.advance(1)):
            self.assertIs(r.mgr.apply_event(ev).status, EventStatus.APPLIED)
        rec = r.mgr.record(req.idempotency_key)
        self.assertIs(rec.order.state, S.FILLED)
        self.assertIs(rec.submission, SubmissionStatus.RECONCILED_FROM_BROKER)
        self.assertTrue(any("implicit acknowledgement" in h.detail for h in rec.order.state_history))
        self.assertTrue(r.mgr.halted)  # the uncertainty halt remains until an operator clears it

    def test_halt_clearing_needs_resolution_and_an_operator(self):
        r = Rig()
        r.broker.inject_fault("FAIL_AFTER_ACCEPT")
        req, _, _ = r.submit()
        h = r.mgr.active_halts()[0]
        with self.assertRaises(ValueError):
            r.mgr.clear_halt(h.halt_id, "op", "looks fine")      # still unresolved
        r.mgr.resolve_uncertain_submission(req.idempotency_key, r.broker, r.session)
        with self.assertRaises(ValueError):
            r.mgr.clear_halt(h.halt_id, "", "")                  # no operator / reason
        cleared = r.mgr.clear_halt(h.halt_id, "operator-1", "reconciled from broker lookup")
        self.assertTrue(cleared.cleared)
        self.assertFalse(r.mgr.halted)

    def test_interrupted_portfolio_update_is_detected_and_recoverable(self):
        r = Rig()
        r.submit()
        reps = r.advance(1)
        r.mgr.apply_event(r.fill_events(reps)[0])               # fill recorded; crash before the portfolio update
        pending = r.mgr.fills_pending_portfolio_application()
        self.assertEqual([f.fill_id for _k, f in pending], [reps[0].fill.fill_id])
        r.mgr.mark_portfolio_applied(reps[0].fill.fill_id)       # recovery re-applies idempotently, then confirms
        self.assertEqual(r.mgr.fills_pending_portfolio_application(), ())
        with self.assertRaises(KeyError):
            r.mgr.mark_portfolio_applied("not-a-fill")

    def test_snapshot_restore_round_trip_keeps_idempotency(self):
        r = Rig(max_fill_fraction_per_bar=Decimal("0.4"))
        req, _, _ = r.submit()
        evs = r.fill_events(r.advance(1))
        r.mgr.apply_event(evs[0])
        snap = json.loads(json.dumps(r.mgr.snapshot()))          # survives real JSON serialisation
        m2 = OrderLifecycleManager.restore(snap, lambda: T0, {req.idempotency_key: req})
        rec = m2.record(req.idempotency_key)
        self.assertEqual((rec.order.state, rec.filled_qty), (S.PARTIALLY_FILLED, 40))
        self.assertIs(m2.apply_event(evs[0]).status, EventStatus.DUPLICATE_IGNORED)
        self.assertEqual(m2.record(req.idempotency_key).filled_qty, 40)
        self.assertEqual([h.to_state for h in rec.order.state_history],
                         [h.to_state for h in r.mgr.record(req.idempotency_key).order.state_history])

    def test_restore_refuses_tampering_and_substituted_requests(self):
        r = Rig()
        req, _, _ = r.submit()
        snap = json.loads(json.dumps(r.mgr.snapshot()))
        bad = json.loads(json.dumps(snap))
        bad["body"]["records"][0]["applied_fills"] = []
        bad["body"]["records"][0]["submission"] = "ACCEPTED"
        bad["body"]["seq"] += 1
        with self.assertRaises(ValueError):
            OrderLifecycleManager.restore(bad, lambda: T0, {req.idempotency_key: req})
        other = request_for(decision(), 5.0, key=req.idempotency_key)
        with self.assertRaises(ValueError):
            OrderLifecycleManager.restore(snap, lambda: T0, {req.idempotency_key: other})
        with self.assertRaises(ValueError):
            OrderLifecycleManager.restore(snap, lambda: T0, {})

    def test_restore_preserves_halts_and_uncertain_submissions(self):
        r = Rig()
        r.broker.inject_fault("FAIL_AFTER_ACCEPT")
        req, rd, _ = r.submit()
        m2 = OrderLifecycleManager.restore(json.loads(json.dumps(r.mgr.snapshot())), lambda: T0, {req.idempotency_key: req})
        self.assertTrue(m2.halted)
        with self.assertRaises(UnresolvedSubmission):
            m2.submit(req, rd, r.broker, r.session)

    def test_operator_resolution_paths_are_consistent_with_accounted_fills(self):
        r = Rig()
        req, _, sub = r.submit()
        k = req.idempotency_key
        r.mgr.apply_event(BrokerEvent(EventKind.CANCEL_CONFIRMED, sub.record.order.broker_order_id, k))  # -> RECON
        with self.assertRaises(ValueError):
            r.mgr.resolve_reconciliation_required(k, S.FILLED, "op", "evidence")     # 0/100 filled
        with self.assertRaises(ValueError):
            r.mgr.resolve_reconciliation_required(k, S.CANCELLED, "", "")
        rec = r.mgr.resolve_reconciliation_required(k, S.CANCELLED, "op-1", "broker statement shows cancelled, 0 filled")
        self.assertIs(rec.order.state, S.CANCELLED)
        self.assertEqual(rec.corrections[-1]["operator"], "op-1")

    def test_quarantined_fill_can_be_accepted_only_by_operator_and_is_traceable(self):
        r = Rig()
        req, _, _ = r.submit()
        k = req.idempotency_key
        r.mgr.apply_event(fill_event(k, synthetic_fill(k, 40, 50)))
        # force a quarantine via a fill-type contradiction, then accept it explicitly
        bad = synthetic_fill(k, 20, 50, FillType.FULL, fid="late_fid")
        r.mgr.apply_event(fill_event(k, bad))
        rec = r.mgr.record(k)
        self.assertEqual(rec.filled_qty, 40)
        with self.assertRaises(ValueError):
            r.mgr.accept_quarantined_fill(k, "late_fid", "", "")
        acc = r.mgr.accept_quarantined_fill(k, "late_fid", "op-2", "broker fill report confirms 20 @ 50")
        self.assertTrue(acc.via_correction)
        self.assertEqual(rec.filled_qty, 60)
        self.assertEqual(rec.corrections[-1]["kind"], "ACCEPT_FILL")


if __name__ == "__main__":
    unittest.main()
