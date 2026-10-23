"""Slice 7 — execution reconciliation (orders, fills, positions, cash, halts). SYNTHETIC / offline."""

from __future__ import annotations

import dataclasses
import unittest
from decimal import Decimal

from domain.models.enums import FillType, OrderState
from risk_execution.order_lifecycle import BrokerEvent, EventKind, ExecutionHalted
from risk_execution.reconciliation import (
    LedgerView,
    ReconciliationOutcome,
    compare_cash_positions,
    reconcile_execution,
    reconcile_from_broker_evidence,
)
from tests.unit._lifecycle_helpers import A, Rig, decision, fill_event, request_for, synthetic_fill

O = ReconciliationOutcome


def recon(r: Rig, internal: LedgerView | None = None, fills=None, statuses=None, fn=reconcile_execution):
    b = r.broker_view()
    return fn(r.mgr, r.opening, internal or b, b,
              r.broker.order_statuses(r.session) if statuses is None else statuses,
              tuple(r.broker.get_fills(r.session)) if fills is None else fills)


def kinds(res):
    return sorted({m.kind for m in res.mismatches})


def book(r: Rig, reports) -> None:
    for ev in r.fill_events(reports):
        r.mgr.apply_event(ev)
        r.mgr.mark_portfolio_applied(ev.fill.fill_id)


class GroupD_Reconciliation(unittest.TestCase):
    def test_consistent_ledgers_orders_fills_cash_positions(self):
        r = Rig()
        r.submit()
        book(r, r.advance(1))
        res = recon(r)
        self.assertIs(res.outcome, O.CONSISTENT, res.mismatches)
        self.assertEqual(res.implied_positions, {A: 100})
        self.assertEqual(res.implied_cash, r.broker_view().cash)
        self.assertIsNone(r.mgr.record_reconciliation(res))
        self.assertFalse(r.mgr.halted)

    def test_safe_duplicates_do_not_double_account_and_are_reported(self):
        r = Rig()
        r.submit()
        reps = r.advance(1)
        book(r, reps)
        r.mgr.apply_event(r.fill_events(reps)[0])
        res = recon(r)
        self.assertIs(res.outcome, O.CONSISTENT_AFTER_SAFE_DUPLICATES)
        self.assertEqual(res.safe_duplicates_ignored, 1)
        self.assertEqual(res.implied_positions, {A: 100})

    def test_partial_fill_then_cancel_reconciles(self):
        r = Rig(max_fill_fraction_per_bar=Decimal("0.4"))
        req, _, sub = r.submit()
        book(r, r.advance(1))
        r.broker.cancel_order(r.session, sub.record.order.broker_order_id)
        r.mgr.apply_event(BrokerEvent(EventKind.CANCEL_CONFIRMED, sub.record.order.broker_order_id, req.idempotency_key))
        res = recon(r)
        self.assertIs(res.outcome, O.CONSISTENT, res.mismatches)
        self.assertEqual(res.implied_positions, {A: 40})

    def test_missing_fill_in_lifecycle_is_detected_then_reconciled_from_broker_evidence(self):
        r = Rig()
        r.submit()
        reps = r.advance(1)                       # broker filled; the event was never delivered to us
        res = recon(r)
        self.assertIn("FILL_MISSING_IN_LIFECYCLE", kinds(res))
        self.assertIn("POSITION", kinds(res))
        self.assertIs(res.outcome, O.MISMATCH_DETECTED)
        stale_books = LedgerView(r.opening.cash, {}, {})           # internal portfolio never saw the fill either
        behind = reconcile_from_broker_evidence(r.mgr, r.opening, stale_books, r.broker_view(),
                                                r.broker.order_statuses(r.session), tuple(r.broker.get_fills(r.session)))
        self.assertFalse(behind.consistent)                    # lifecycle caught up, internal books did not
        self.assertIn("PORTFOLIO_APPLICATION_PENDING", kinds(behind))
        r2 = Rig()
        r2.submit()
        reps2 = r2.advance(1)
        fixed = reconcile_from_broker_evidence(r2.mgr, r2.opening, LedgerView(r2.opening.cash, {}, {}), r2.broker_view(),
                                               r2.broker.order_statuses(r2.session), tuple(r2.broker.get_fills(r2.session)),
                                               book_evidence=lambda rep: r2.broker_view())
        self.assertIs(fixed.outcome, O.RECONCILED_FROM_BROKER_EVIDENCE, fixed.mismatches)
        self.assertEqual(fixed.evidence_fill_ids, (reps2[0].fill.fill_id,))
        self.assertEqual(r2.mgr.fills_pending_portfolio_application(), ())

    def test_extra_fill_lifecycle_has_but_broker_does_not(self):
        r = Rig()
        req, _, _ = r.submit()
        k = req.idempotency_key
        r.mgr.apply_event(fill_event(k, synthetic_fill(k, 100, 50, FillType.FULL, fid="ghost")))
        res = recon(r)
        self.assertIn("FILL_NOT_AT_BROKER", kinds(res))
        self.assertIn("POSITION", kinds(res))
        self.assertIn("ORDER_FILLED_QTY", kinds(res))

    def test_contradictory_fill_report(self):
        r = Rig()
        r.submit()
        reps = r.advance(1)
        book(r, reps)
        forged = dataclasses.replace(reps[0], fill=dataclasses.replace(reps[0].fill, price=60.0))
        res = recon(r, fills=(forged,))
        self.assertIn("FILL_CONTRADICTION", kinds(res))
        self.assertFalse(res.consistent)

    def test_position_mismatch_and_cash_mismatch(self):
        r = Rig()
        r.submit()
        book(r, r.advance(1))
        b = r.broker_view()
        pos = recon(r, internal=LedgerView(b.cash, {A: 99}, b.avg_costs))
        self.assertEqual([m.kind for m in pos.mismatches if m.kind == "POSITION"].count("POSITION"), 2)
        cash = recon(r, internal=LedgerView(b.cash + Decimal("0.01"), b.positions, b.avg_costs))
        self.assertIn("CASH", kinds(cash))
        self.assertIs(cash.outcome, O.MISMATCH_DETECTED)

    def test_outstanding_order_mismatch(self):
        r = Rig(max_fill_fraction_per_bar=Decimal("0.4"))
        req, _, sub = r.submit()
        book(r, r.advance(1))
        sts = dict(r.broker.order_statuses(r.session))
        bid = sub.record.order.broker_order_id
        sts[bid] = dataclasses.replace(sts[bid], remaining_quantity=sts[bid].remaining_quantity + 5)
        self.assertIn("OUTSTANDING_QTY", kinds(recon(r, statuses=sts)))

    def test_order_state_and_missing_order_at_broker(self):
        r = Rig()
        _req, _, sub = r.submit()
        bid = sub.record.order.broker_order_id
        self.assertIn("ORDER_MISSING_AT_BROKER", kinds(recon(r, statuses={})))
        sts = dict(r.broker.order_statuses(r.session))
        sts[bid] = dataclasses.replace(sts[bid], state=OrderState.CANCELLED)
        self.assertIn("ORDER_STATE", kinds(recon(r, statuses=sts)))

    def test_unresolved_order_identity_unknown_broker_order(self):
        r = Rig()
        rd = decision()
        r.broker.place_order(r.session, request_for(rd, 10.0))     # placed behind the lifecycle's back
        res = recon(r)
        self.assertIn("UNKNOWN_BROKER_ORDER", kinds(res))
        self.assertIs(res.outcome, O.UNRESOLVED)
        self.assertFalse(res.consistent)

    def test_uncertain_submission_is_unresolved_not_consistent(self):
        r = Rig()
        r.broker.inject_fault("FAIL_AFTER_ACCEPT")
        r.submit()
        res = recon(r)
        self.assertFalse(res.consistent)
        self.assertIn("UNRESOLVED_ORDER", kinds(res))

    def test_cash_unverifiable_when_charges_unknown_is_never_reported_consistent(self):
        r = Rig()
        req, _, _ = r.submit()
        k = req.idempotency_key
        f = synthetic_fill(k, 100, 50, FillType.FULL)
        r.mgr.apply_event(fill_event(k, f))
        res = recon(r)
        self.assertIn("CASH_UNVERIFIABLE", kinds(res))
        self.assertFalse(res.consistent)

    def test_pending_portfolio_application_blocks_a_clean_result(self):
        r = Rig()
        r.submit()
        for ev in r.fill_events(r.advance(1)):
            r.mgr.apply_event(ev)                                  # crash before portfolio update
        self.assertIn("PORTFOLIO_APPLICATION_PENDING", kinds(recon(r)))

    def test_mismatch_halts_execution_and_only_an_evidenced_operator_action_clears_it(self):
        r = Rig()
        r.submit()
        book(r, r.advance(1))
        b = r.broker_view()
        bad = recon(r, internal=LedgerView(b.cash + 1, b.positions, b.avg_costs))
        halt = r.mgr.record_reconciliation(bad)
        self.assertIsNotNone(halt)
        with self.assertRaises(ExecutionHalted):
            r.submit()
        # a later passing check does NOT make the halt disappear by itself
        good = recon(r)
        r.mgr.record_reconciliation(good)
        self.assertTrue(r.mgr.halted)
        with self.assertRaises(ValueError):
            r.mgr.clear_halt(halt.halt_id, "op", "all good")                      # no run cited
        with self.assertRaises(ValueError):
            r.mgr.clear_halt(halt.halt_id, "op", "all good", bad.run_id)          # cites the failing run
        r.mgr.clear_halt(halt.halt_id, "op-9", "ledgers agree after manual review", good.run_id)
        self.assertFalse(r.mgr.halted)

    def test_interrupted_reconciliation_is_not_success(self):
        r = Rig()
        r.submit()
        book(r, r.advance(1))
        b = r.broker_view()
        halt = r.mgr.record_reconciliation(recon(r, internal=LedgerView(b.cash + 1, b.positions, b.avg_costs)))

        def boom(*_a, **_k):
            raise ConnectionError("broker ledger unavailable mid-reconciliation")
        with self.assertRaises(ConnectionError):
            reconcile_execution(r.mgr, r.opening, b, b, boom(), ())   # nothing is recorded
        with self.assertRaises(ValueError):
            r.mgr.clear_halt(halt.halt_id, "op", "assumed fine", "recon_never_ran")
        self.assertTrue(r.mgr.halted)

    def test_run_id_is_deterministic_and_mismatches_carry_subjects(self):
        r = Rig()
        r.submit()
        book(r, r.advance(1))
        b = r.broker_view()
        a1 = recon(r, internal=LedgerView(b.cash, {A: 1}, b.avg_costs))
        a2 = recon(r, internal=LedgerView(b.cash, {A: 1}, b.avg_costs))
        self.assertEqual(a1.run_id, a2.run_id)
        self.assertNotEqual(a1.run_id, recon(r).run_id)
        self.assertTrue(all(m.subject for m in a1.mismatches))

    def test_quarantined_overfill_blocks_until_dismissed_with_traceable_correction(self):
        r = Rig()
        req, _, _ = r.submit()
        book(r, r.advance(1))
        k = req.idempotency_key
        r.mgr.apply_event(fill_event(k, synthetic_fill(k, 10, 50, fid="x1")))   # overfill -> quarantined, halted
        res = recon(r)
        self.assertFalse(res.consistent)
        self.assertIn("UNRESOLVED_ORDER", kinds(res))
        r.mgr.dismiss_quarantined(k, next(iter(r.mgr.record(k).quarantined)), "op-3", "no such fill at broker")
        self.assertEqual(r.mgr.record(k).corrections[-1]["operator"], "op-3")
        r.mgr.acknowledge_terminal_discrepancy(k, "op-3", "overfill report was spurious; broker shows 100/100")
        good = recon(r)
        r.mgr.record_reconciliation(good)
        self.assertTrue(r.mgr.halted)                                   # still halted until explicitly cleared
        for h in r.mgr.active_halts():
            r.mgr.clear_halt(h.halt_id, "op-3", "dismissed; ledgers agree", good.run_id)
        self.assertFalse(r.mgr.halted)


class SharedComparisonTests(unittest.TestCase):
    def test_original_two_ledger_messages_are_preserved(self):
        out = compare_cash_positions(Decimal(1), {"X": 1}, Decimal(2), {"X": 2, "Y": 1})
        self.assertEqual(out, ["cash: portfolio 1 != broker 2", "position X: portfolio 1 != broker 2",
                               "position Y: portfolio 0 != broker 1"])


if __name__ == "__main__":
    unittest.main()
