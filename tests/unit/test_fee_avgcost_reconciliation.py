"""Slice 7 closure — per-fill fee and average-cost reconciliation. SYNTHETIC / offline."""

from __future__ import annotations

import dataclasses
import unittest
from decimal import Decimal

from domain.models.enums import Action
from risk_execution.order_lifecycle import ExecutionHalted
from risk_execution.reconciliation import AVG_COST_TOLERANCE, LedgerView, ReconciliationOutcome, reconcile_execution
from tests.unit._lifecycle_helpers import A, Rig
from tests.unit.test_execution_reconciliation import book, kinds, recon

O = ReconciliationOutcome


def two_fill_rig():
    r = Rig(max_fill_fraction_per_bar=Decimal("0.5"))
    r.submit()
    reps = list(r.advance(1)) + list(r.advance(2))
    book(r, reps)
    return r, reps


def bump(rep, delta: Decimal, **changes):
    c = rep.charges
    return dataclasses.replace(rep, charges=dataclasses.replace(c, brokerage=c.brokerage + delta,
                                                                total_cost=c.total_cost + delta, **changes))


class PerFillCharges(unittest.TestCase):
    def test_consistent_fees_and_average_cost(self):
        r, _ = two_fill_rig()
        res = recon(r)
        self.assertIs(res.outcome, O.CONSISTENT, res.mismatches)

    def test_per_fill_charge_mismatch_is_caught_even_when_aggregate_cash_matches(self):
        r, reps = two_fill_rig()
        d = Decimal("0.50")
        forged = (bump(reps[0], d), bump(reps[1], -d))
        self.assertEqual(sum(x.charges.total_cost for x in forged), sum(x.charges.total_cost for x in reps))
        res = recon(r, fills=forged)
        self.assertNotIn("CASH", kinds(res))                       # aggregate cash agrees...
        self.assertEqual([m.kind for m in res.mismatches if m.kind == "FILL_CHARGES"], ["FILL_CHARGES"] * 2)
        self.assertIn("FILL_CHARGE_COMPONENT", kinds(res))
        self.assertEqual({m.subject for m in res.mismatches if m.kind == "FILL_CHARGES"}, {x.fill.fill_id for x in reps})
        self.assertIs(res.outcome, O.MISMATCH_DETECTED)
        self.assertIsNotNone(r.mgr.record_reconciliation(res))     # material => halt
        with self.assertRaises(ExecutionHalted):
            r.submit()

    def test_schedule_version_mismatch(self):
        r, reps = two_fill_rig()
        forged = (dataclasses.replace(reps[0], charges=dataclasses.replace(reps[0].charges, schedule_version="other-v9")), reps[1])
        res = recon(r, fills=forged)
        self.assertIn("FILL_SCHEDULE_VERSION", kinds(res))
        self.assertFalse(res.consistent)

    def test_missing_broker_charges_are_unresolved_never_zero_and_never_recomputed(self):
        r, reps = two_fill_rig()
        res = recon(r, fills=(dataclasses.replace(reps[0], charges=None), reps[1]))
        self.assertIn("CHARGES_UNAVAILABLE_BROKER", kinds(res))
        self.assertNotIn("FILL_CHARGES", kinds(res))               # not compared against zero / a recomputed value
        self.assertIs(res.outcome, O.UNRESOLVED)
        self.assertFalse(res.consistent)
        self.assertIsNotNone(r.mgr.record_reconciliation(res))

    def test_lifecycle_fill_without_recorded_charges_is_unresolved(self):
        from risk_execution.order_lifecycle import BrokerEvent, EventKind
        r = Rig()
        req, _, _ = r.submit()
        rep = r.advance(1)[0]
        r.mgr.apply_event(BrokerEvent(EventKind.FILL, rep.broker_order_id, req.idempotency_key, fill=rep.fill))  # no charges
        r.mgr.mark_portfolio_applied(rep.fill.fill_id)
        res = recon(r)
        self.assertIn("CHARGES_UNAVAILABLE_LIFECYCLE", kinds(res))
        self.assertIn("CASH_UNVERIFIABLE", kinds(res))
        self.assertFalse(res.consistent)

    def test_fill_provenance_mismatch(self):
        r, reps = two_fill_rig()
        forged = (dataclasses.replace(reps[0], idempotency_key="someone-else"), reps[1])
        self.assertIn("FILL_PROVENANCE", kinds(recon(r, fills=forged)))

    def test_charge_comparison_is_exact_decimal_but_scale_insensitive(self):
        r, reps = two_fill_rig()
        c = reps[0].charges
        same_value_other_scale = dataclasses.replace(c, brokerage=Decimal(str(c.brokerage)) + Decimal("0.000"))
        self.assertNotIn("FILL_CHARGES", kinds(recon(r, fills=(dataclasses.replace(reps[0], charges=same_value_other_scale), reps[1]))))
        tiny = bump(reps[0], Decimal("0.0001"))                      # a 0.01-paisa difference is NOT tolerated
        self.assertIn("FILL_CHARGES", kinds(recon(r, fills=(tiny, reps[1]))))


class AverageCost(unittest.TestCase):
    def test_average_cost_mismatch_despite_equal_quantities(self):
        r, _ = two_fill_rig()
        b = r.broker_view()
        bad = LedgerView(b.cash, b.positions, {A: b.avg_costs[A] + Decimal("1")})
        res = recon(r, internal=bad)
        self.assertNotIn("POSITION", kinds(res))
        self.assertEqual([m.kind for m in res.mismatches].count("AVG_COST"), 2)   # vs lifecycle and vs broker
        self.assertIs(res.outcome, O.MISMATCH_DETECTED)
        self.assertEqual({m.subject for m in res.mismatches}, {A})
        self.assertIsNotNone(r.mgr.record_reconciliation(res))

    def test_average_cost_unavailable_from_one_source_is_unresolved_not_a_match(self):
        r, _ = two_fill_rig()
        b = r.broker_view()
        res = recon(r, internal=LedgerView(b.cash, b.positions, None))
        self.assertEqual(kinds(res), ["AVG_COST_UNAVAILABLE"])
        self.assertIs(res.outcome, O.UNRESOLVED)
        self.assertFalse(res.consistent)
        res2 = recon(r, internal=LedgerView(b.cash, b.positions, {}))     # source silent about a held instrument
        self.assertIn("AVG_COST_UNAVAILABLE", kinds(res2))

    def test_tolerance_boundary_is_inclusive_and_documented(self):
        self.assertEqual(AVG_COST_TOLERANCE, Decimal("1E-9"))
        r, _ = two_fill_rig()
        b = r.broker_view()
        for delta, ok in ((Decimal("0"), True), (AVG_COST_TOLERANCE, True), (AVG_COST_TOLERANCE * 2, False),
                          (Decimal("0.000001"), False)):
            with self.subTest(delta=delta):
                res = recon(r, internal=LedgerView(b.cash, b.positions, {A: b.avg_costs[A] + delta}))
                self.assertEqual(res.consistent, ok, res.mismatches)

    def test_sells_keep_average_cost_and_all_sources_agree(self):
        r = Rig()
        r.submit(100.0)
        book(r, r.advance(1))
        r.submit(40.0, Action.SELL)
        book(r, r.advance(2, "55"))
        res = recon(r)
        self.assertIs(res.outcome, O.CONSISTENT, res.mismatches)
        self.assertEqual(res.implied_positions, {A: 60})

    def test_unknown_opening_average_cost_makes_the_implied_value_unverifiable(self):
        r = Rig()
        r.opening = LedgerView(r.opening.cash, {"OLD": 10}, None)
        b = r.broker_view()
        res = reconcile_execution(r.mgr, r.opening, LedgerView(b.cash, {"OLD": 10}, {"OLD": Decimal(5)}),
                                  LedgerView(b.cash, {"OLD": 10}, {"OLD": Decimal(5)}), {}, ())
        self.assertIn("AVG_COST_UNAVAILABLE", kinds(res))
        self.assertFalse(res.consistent)


if __name__ == "__main__":
    unittest.main()
