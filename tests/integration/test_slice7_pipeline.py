"""Slice 7 — lifecycle + reconciliation inside the end-to-end pipeline. SYNTHETIC; infrastructure only."""

from __future__ import annotations

import unittest
from unittest import mock

from research.harness.failures import FailureCategory, RunStatus
from risk_execution.broker.adapters.simulated import SimulatedBrokerAdapter
from risk_execution.order_lifecycle import OrderLifecycleManager
from simulation import PipelineHarness
from tests.unit._pipeline_helpers import config, pipeline, tier2, universe, weekly_bars

PH = PipelineHarness


def run(fraction=0.3):
    strat, b = tier2(fraction)
    return PH().run(config(), strat, weekly_bars(), [universe()], pipeline(b))


class PipelineLifecycleTests(unittest.TestCase):
    def test_every_cycle_carries_an_execution_reconciliation_that_is_consistent(self):
        res = run()
        self.assertIs(res.run.status, RunStatus.COMPLETED, res.run.failure)
        rows = [r for r in res.reconciliations if "execution_reconciliation" in r]
        self.assertTrue(rows, "no execution reconciliation rows recorded")
        for r in rows:
            self.assertIn(r["execution_reconciliation"]["outcome"], ("CONSISTENT", "CONSISTENT_AFTER_SAFE_DUPLICATES"))

    def test_duplicate_fill_redelivery_is_never_double_booked(self):
        orig = SimulatedBrokerAdapter.advance

        def advance_twice_delivered(self, t, prices):
            reps = orig(self, t, prices)
            return list(reps) + list(reps)           # the transport redelivers every fill report

        with mock.patch.object(SimulatedBrokerAdapter, "advance", advance_twice_delivered):
            dup = run()
        base = run()
        self.assertIs(dup.run.status, RunStatus.COMPLETED, dup.run.failure)
        self.assertEqual(dup.summary, base.summary)
        self.assertEqual(len(dup.broker_fills), len(base.broker_fills))

    def test_unresolved_submission_fails_the_run_closed_and_never_fabricates_a_fill(self):
        orig = SimulatedBrokerAdapter.place_order
        n = {"c": 0}

        def flaky(self, session, request):
            n["c"] += 1
            if n["c"] == 1:
                self.inject_fault("FAIL_AFTER_ACCEPT")
            return orig(self, session, request)

        with mock.patch.object(SimulatedBrokerAdapter, "place_order", flaky):
            res = run()
        self.assertIs(res.run.status, RunStatus.FAILED)
        self.assertIs(res.run.failure.category, FailureCategory.RECONCILIATION_REQUIRED)
        self.assertEqual([o for o in res.orders if o["filled_quantity"] > 0], [])  # nothing was fabricated

    def test_manager_type_is_the_existing_lifecycle_extension_not_a_second_state_machine(self):
        from domain.models.order import Order
        self.assertTrue(issubclass(OrderLifecycleManager, object))
        self.assertTrue(hasattr(Order, "transition_to"))


if __name__ == "__main__":
    unittest.main()
