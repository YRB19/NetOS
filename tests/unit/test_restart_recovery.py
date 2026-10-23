"""Slice 7 closure — restart/recovery at the critical boundaries. SYNTHETIC / offline.

The simulated broker stands in for an EXTERNAL broker: it is deliberately RETAINED across the simulated
process death (only the lifecycle manager is rebuilt from disk). Crash = a BaseException that the manager's
`except Exception` cannot absorb, i.e. the process "dies" at that exact point.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from domain.models.enums import OrderState as S
from research.harness.portfolio import ResearchPortfolio
from risk_execution.broker.adapters.simulated import SimulatedBrokerAdapter
from risk_execution.order_lifecycle import (
    CheckpointError,
    CheckpointStore,
    ExecutionHalted,
    OrderLifecycleManager,
    SubmissionStatus,
    UnresolvedSubmission,
)
from risk_execution.reconciliation import LedgerView, reconcile_execution
from shared.versioning.content_hash import hash_json_stable
from tests.unit._lifecycle_helpers import A, RRV, T0, Rig, decision, request_for
from tests.unit.test_execution_reconciliation import recon


class Crash(BaseException):
    """Process death. Not an Exception: nothing in the manager may swallow it."""


class CrashingAdapter:
    def __init__(self, inner: SimulatedBrokerAdapter, when: str) -> None:
        self._inner, self._when = inner, when

    def place_order(self, session, request):
        if self._when == "before":
            raise Crash("died before the broker saw the request")
        self._inner.place_order(session, request)
        raise Crash("died after the broker accepted, before the caller got the response")

    def __getattr__(self, name):
        return getattr(self._inner, name)


class FailingStore(CheckpointStore):
    def __init__(self, path, fail_on: int) -> None:
        super().__init__(path)
        self.fail_on, self.calls = fail_on, 0

    def write(self, snapshot):
        self.calls += 1
        if self.calls == self.fail_on:
            raise CheckpointError("simulated disk failure")
        super().write(snapshot)


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.path = Path(self._td.name) / "lifecycle.json"
        self.store = CheckpointStore(self.path)
        self.requests: dict = {}     # stands in for the sizing-owned store of the ORIGINAL OrderRequests
        self.rig = Rig(max_fill_fraction_per_bar=Decimal("0.5"))
        self.rig.mgr = OrderLifecycleManager(RRV, lambda: self.rig.now["t"], self.store)

    def new_order(self, qty: float = 100.0):
        rd = decision(qty)
        req = request_for(rd, qty)
        self.requests[req.idempotency_key] = req
        return req, rd

    def restart(self):
        """A brand-new manager object from disk; the broker object (external system) survives."""
        m = OrderLifecycleManager.restore_from_store(self.store, lambda: self.rig.now["t"], self.requests)
        self.assertIsNot(m, self.rig.mgr)
        self.rig.mgr = m
        return m


class Boundaries(Base):
    def test_before_submission_nothing_exists_and_a_fresh_manager_submits_exactly_once(self):
        with self.assertRaises(CheckpointError):
            OrderLifecycleManager.restore_from_store(self.store, lambda: T0, {})
        req, rd = self.new_order()
        sub = self.rig.mgr.submit(req, rd, self.rig.broker, self.rig.session)
        self.assertEqual(len(self.rig.broker.order_statuses(self.rig.session)), 1)
        self.assertIs(sub.record.order.state, S.ACKNOWLEDGED)

    def test_mandatory_pre_submission_checkpoint_failure_prevents_the_send(self):
        self.rig.mgr = OrderLifecycleManager(RRV, lambda: T0, FailingStore(self.path, fail_on=1))
        req, rd = self.new_order()
        with self.assertRaises(CheckpointError):
            self.rig.mgr.submit(req, rd, self.rig.broker, self.rig.session)
        self.assertEqual(self.rig.broker.order_statuses(self.rig.session), {})        # NOT sent
        rec = self.rig.mgr.record(req.idempotency_key)
        self.assertIs(rec.submission, SubmissionStatus.LOCAL_FAILURE)
        self.assertIs(rec.order.state, S.APPROVED)
        self.assertEqual(self.rig.mgr.active_halts()[0].code, "CHECKPOINT_FAILURE")
        with self.assertRaises(ExecutionHalted):
            self.rig.mgr.submit(*self.new_order(), self.rig.broker, self.rig.session)

    def test_later_checkpoint_failure_halts_and_never_reports_clean_success(self):
        self.rig.mgr = OrderLifecycleManager(RRV, lambda: T0, FailingStore(self.path, fail_on=2))   # 2nd write = post-submission
        req, rd = self.new_order()
        with self.assertRaises(CheckpointError):
            self.rig.mgr.submit(req, rd, self.rig.broker, self.rig.session)
        self.assertTrue(self.rig.mgr.halted)
        self.assertEqual(len(self.rig.broker.order_statuses(self.rig.session)), 1)     # the broker did get it
        # disk still holds the write-ahead state, so a restart recovers by LOOKUP, not by re-sending
        m = self.restart()
        m.recover_after_restart(self.rig.broker, self.rig.session)
        self.assertEqual(len(self.rig.broker.order_statuses(self.rig.session)), 1)
        self.assertIs(m.record(req.idempotency_key).order.state, S.ACKNOWLEDGED)

    def test_crash_after_write_ahead_before_the_broker_accepts(self):
        req, rd = self.new_order()
        with self.assertRaises(Crash):
            self.rig.mgr.submit(req, rd, CrashingAdapter(self.rig.broker, "before"), self.rig.session)
        self.assertEqual(self.rig.broker.order_statuses(self.rig.session), {})
        m = self.restart()
        rec = m.record(req.idempotency_key)
        self.assertIs(rec.submission, SubmissionStatus.APPROVED_NOT_SENT)
        acts = m.recover_after_restart(self.rig.broker, self.rig.session)
        self.assertEqual(acts["marked_unconfirmed"], [req.idempotency_key])
        self.assertIs(rec.submission, SubmissionStatus.ABSENT_AT_BROKER)
        self.assertEqual(self.rig.broker.order_statuses(self.rig.session), {})        # never fabricated, never re-sent
        self.assertTrue(m.halted)                                                       # operator must clear it
        with self.assertRaises(ExecutionHalted):
            m.submit(*self.new_order(), self.rig.broker, self.rig.session)

    def test_crash_after_broker_acceptance_before_the_caller_gets_the_response(self):
        req, rd = self.new_order()
        with self.assertRaises(Crash):
            self.rig.mgr.submit(req, rd, CrashingAdapter(self.rig.broker, "after"), self.rig.session)
        self.assertEqual(len(self.rig.broker.order_statuses(self.rig.session)), 1)
        m = self.restart()
        acts = m.recover_after_restart(self.rig.broker, self.rig.session)
        self.assertIn("RECONCILED_FROM_BROKER", acts["resolved"][0])
        self.assertEqual(len(self.rig.broker.order_statuses(self.rig.session)), 1)    # still exactly one broker order
        self.assertEqual(self.rig.broker.duplicate_submissions, 0)
        rec = m.record(req.idempotency_key)
        self.assertEqual((rec.order.state, rec.submission), (S.ACKNOWLEDGED, SubmissionStatus.RECONCILED_FROM_BROKER))
        again = m.submit(req, rd, self.rig.broker, self.rig.session)                       # a retry is never re-sent
        self.assertEqual(again.outcome.value, "DUPLICATE_NOT_RESENT")
        self.assertEqual(len(self.rig.broker.order_statuses(self.rig.session)), 1)

    def test_unconfirmed_submission_cannot_be_retried_before_reconciliation_even_after_restart(self):
        self.rig.broker.inject_fault("FAIL_AFTER_ACCEPT")
        req, rd = self.new_order()
        self.rig.mgr.submit(req, rd, self.rig.broker, self.rig.session)
        m = self.restart()
        with self.assertRaises(UnresolvedSubmission):
            m.submit(req, rd, self.rig.broker, self.rig.session)
        self.assertEqual(len(self.rig.broker.order_statuses(self.rig.session)), 1)

    def test_after_ack_but_before_fills_were_processed(self):
        req, rd = self.new_order()
        self.rig.mgr.submit(req, rd, self.rig.broker, self.rig.session)
        self.rig.advance(1)                                   # broker fills 50; the process died before ingesting them
        m = self.restart()
        self.assertEqual(m.record(req.idempotency_key).filled_qty, 0)
        acts = m.recover_after_restart(self.rig.broker, self.rig.session)
        self.assertEqual(len(acts["replayed_fills"]), 1)
        self.assertEqual((m.record(req.idempotency_key).filled_qty, m.record(req.idempotency_key).order.state),
                         (50, S.PARTIALLY_FILLED))
        again = m.recover_after_restart(self.rig.broker, self.rig.session)                # replay twice: no new effect
        self.assertEqual(again["replayed_fills"], [])
        self.assertEqual(m.record(req.idempotency_key).filled_qty, 50)

    def test_after_fill_ingestion_before_portfolio_application_applies_exactly_once(self):
        req, rd = self.new_order()
        self.rig.mgr.submit(req, rd, self.rig.broker, self.rig.session)
        reps = list(self.rig.advance(1)) + list(self.rig.advance(2))
        for ev in self.rig.fill_events(reps):
            self.rig.mgr.apply_event(ev)                      # checkpointed; the portfolio update never happened
        m = self.restart()
        pending = m.fills_pending_portfolio_application()
        self.assertEqual({f.fill_id for _k, f in pending}, {x.fill.fill_id for x in reps})
        pf = ResearchPortfolio(self.rig.opening.cash)
        by_id = {x.fill.fill_id: x for x in reps}
        for _k, f in pending:                                 # recovery re-applies, confirming each one
            pf.buy(A, f.quantity, f.price, by_id[f.fill_id].charges.total_cost)
            m.mark_portfolio_applied(f.fill_id)
        m.recover_after_restart(self.rig.broker, self.rig.session)         # replaying broker evidence changes nothing
        self.assertEqual(m.fills_pending_portfolio_application(), ())
        clean = ResearchPortfolio(self.rig.opening.cash)                    # the uninterrupted reference
        for x in reps:
            clean.buy(A, int(x.fill.quantity), Decimal(str(x.fill.price)), x.charges.total_cost)
        self.assertEqual((pf.cash, pf.quantity(A)), (clean.cash, clean.quantity(A)))
        b = self.rig.broker_view()
        snap = pf.positions_snapshot()
        res = reconcile_execution(m, self.rig.opening, LedgerView(pf.cash, {A: pf.quantity(A)},
                                                                  {A: Decimal(snap[0]["avg_cost"])}), b,
                                  self.rig.broker.order_statuses(self.rig.session), tuple(self.rig.broker.get_fills(self.rig.session)))
        self.assertTrue(res.consistent, res.mismatches)

    def test_crash_during_reconciliation_records_nothing_and_never_counts_as_success(self):
        req, rd = self.new_order()
        self.rig.mgr.submit(req, rd, self.rig.broker, self.rig.session)
        for ev in self.rig.fill_events(self.rig.advance(1)):
            self.rig.mgr.apply_event(ev)
            self.rig.mgr.mark_portfolio_applied(ev.fill.fill_id)
        b = self.rig.broker_view()
        bad = LedgerView(b.cash + 1, b.positions, b.avg_costs)
        halt = self.rig.mgr.record_reconciliation(recon(self.rig, internal=bad))
        m = self.restart()
        self.assertEqual([h.halt_id for h in m.active_halts()], [halt.halt_id])        # halt survived the restart
        with self.assertRaises(Crash):                                                   # reconciliation dies mid-way
            reconcile_execution(m, self.rig.opening, b, b, (_ for _ in ()).throw(Crash()), ())
        with self.assertRaises(ValueError):
            m.clear_halt(halt.halt_id, "op", "assumed fine", "recon_never_finished")
        good = recon(self.rig)                                                           # after restart the check completes
        m.record_reconciliation(good)
        m.clear_halt(halt.halt_id, "op-1", "re-ran reconciliation after restart", good.run_id)
        self.assertFalse(m.halted)

    def test_replay_and_duplicate_delivery_after_restore_change_nothing(self):
        req, rd = self.new_order()
        self.rig.mgr.submit(req, rd, self.rig.broker, self.rig.session)
        reps = list(self.rig.advance(1)) + list(self.rig.advance(2))
        events = self.rig.fill_events(reps)
        for ev in events:
            self.rig.mgr.apply_event(ev)
            self.rig.mgr.mark_portfolio_applied(ev.fill.fill_id)
        before = recon(self.rig)
        m = self.restart()
        for _ in range(3):
            for ev in events:
                m.apply_event(ev)
            m.recover_after_restart(self.rig.broker, self.rig.session)
        rec = m.record(req.idempotency_key)
        self.assertEqual((rec.filled_qty, len(rec.applied_fills), rec.order.state), (100, 2, S.FILLED))
        self.assertEqual(len(self.rig.broker.order_statuses(self.rig.session)), 1)
        after = recon(self.rig)
        self.assertEqual((after.implied_cash, after.implied_positions), (before.implied_cash, before.implied_positions))
        self.assertTrue(after.consistent, after.mismatches)
        self.assertFalse(m.halted)


class RestoreValidationAndAtomicity(Base):
    def _submitted(self):
        req, rd = self.new_order()
        self.rig.mgr.submit(req, rd, self.rig.broker, self.rig.session)
        return req

    def test_checkpoint_file_contains_no_credentials_or_sessions(self):
        self._submitted()
        text = self.path.read_text().lower()
        for needle in ("password", "api_key", "access_token", "secret", "session"):
            self.assertNotIn(needle, text)

    def test_tampered_corrupt_or_foreign_checkpoints_are_refused(self):
        req = self._submitted()
        good = json.loads(self.path.read_text())
        bad = json.loads(json.dumps(good))
        bad["body"]["records"][0]["submission"] = "ACCEPTED"
        bad["body"]["seq"] += 7
        self.path.write_text(json.dumps(bad))
        with self.assertRaises(ValueError):
            OrderLifecycleManager.restore_from_store(self.store, lambda: T0, self.requests)
        self.path.write_text("{not json")
        with self.assertRaises(CheckpointError):
            OrderLifecycleManager.restore_from_store(self.store, lambda: T0, self.requests)
        self.path.write_text(json.dumps(good))
        with self.assertRaises(ValueError):                           # lifecycle must not invent a replacement request
            OrderLifecycleManager.restore_from_store(self.store, lambda: T0, {})
        other = request_for(decision(), 7.0, key=req.idempotency_key)
        with self.assertRaises(ValueError):
            OrderLifecycleManager.restore_from_store(self.store, lambda: T0, {req.idempotency_key: other})

    def test_inconsistent_history_with_a_valid_checksum_is_refused(self):
        req = self._submitted()
        snap = json.loads(self.path.read_text())
        body = snap["body"]
        body["records"][0]["history"][-1]["to"] = "FILLED"          # ACK recorded as FILLED with zero fills
        bad = {"body": body, "checksum": hash_json_stable(body)}
        self.path.write_text(json.dumps(bad))
        with self.assertRaises(ValueError):
            OrderLifecycleManager.restore_from_store(self.store, lambda: T0, self.requests)
        self.assertIn(req.idempotency_key, self.requests)

    def test_failed_atomic_write_leaves_the_previous_checkpoint_intact(self):
        self._submitted()
        before = self.path.read_bytes()
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(CheckpointError):
                self.store.write({"body": {}, "checksum": "x"})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.read()["checksum"], json.loads(before)["checksum"])
        self.restart()                                                # and it still restores

    def test_written_file_is_atomic_json_and_fsynced(self):
        with mock.patch("os.fsync", wraps=os.fsync) as fs:
            self._submitted()
        self.assertGreaterEqual(fs.call_count, 1)
        self.assertFalse(self.path.with_name(self.path.name + ".tmp").exists())

    def test_fresh_empty_broker_is_NOT_a_survivor__recovery_trusts_retained_external_state(self):
        """Documents the dependency: recovery asks the broker. If the 'external broker' lost its state
        (here: a brand-new simulated broker) the lookup honestly reports ABSENT. The guarantee therefore
        holds only when broker-side records survive, as a real broker's do."""
        req, rd = self.new_order()
        with self.assertRaises(Crash):
            self.rig.mgr.submit(req, rd, CrashingAdapter(self.rig.broker, "after"), self.rig.session)
        amnesiac = Rig(max_fill_fraction_per_bar=Decimal("0.5"))
        m = self.restart()
        acts = m.recover_after_restart(amnesiac.broker, amnesiac.session)
        self.assertIn("ABSENT_AT_BROKER", acts["resolved"][0])        # (and the original broker still holds the real order)
        self.assertEqual(len(self.rig.broker.order_statuses(self.rig.session)), 1)
        self.assertTrue(m.halted)


if __name__ == "__main__":
    unittest.main()
