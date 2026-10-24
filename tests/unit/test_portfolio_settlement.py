"""Slice 7 final closure (ADR-13) — idempotent, durable portfolio settlement. SYNTHETIC / offline.

Expected values come from hand-written literals and an independent plain-Decimal reference ledger (`reference`),
never from `ResearchPortfolio`. A "restart" here means: a new OrderLifecycleManager built from its checkpoint file AND a
new ResearchPortfolio built from its checkpoint file; the simulated broker (an external system) survives.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

from domain.models.enums import Action
from research.harness.failures import FailureCategory, ResearchRunFailure
from research.harness.portfolio import FillApplyStatus, ResearchPortfolio
from research.harness.portfolio_checkpoint import PortfolioCheckpointStore
from risk_execution.reconciliation import LedgerView, reconcile_execution
from shared.versioning.content_hash import hash_json_stable
from simulation.settlement import apply_pending_fills
from tests.unit._lifecycle_helpers import A
from tests.unit.test_restart_recovery import Base


def reference(capital: D, fills: list[tuple[str, int, D, D]]) -> dict:
    """Independent plain-Decimal ledger: (side, qty, price, cost) -> cash, qty, avg_cost, costs, turnover, realized."""
    cash, qty, basis, costs, turn, real = capital, 0, D(0), D(0), D(0), D(0)
    for side, q, p, c in fills:
        gross = q * p
        costs += c
        turn += gross
        if side == "BUY":
            cash -= gross + c
            qty += q
            basis += gross
        else:
            avg = basis / qty
            cash += gross - c
            real += (p - avg) * q
            basis -= avg * q
            qty -= q
    return {"cash": cash, "qty": qty, "avg": (basis / qty) if qty else D(0), "costs": costs, "turnover": turn,
            "realized": real, "n": len(fills)}


def state(pf: ResearchPortfolio, inst: str = A) -> dict:
    pos = {p["instrument_id"]: p for p in pf.positions_snapshot()}
    avg = D(pos[inst]["avg_cost"]) if inst in pos else D(0)
    return {"cash": pf.cash, "qty": pf.quantity(inst), "avg": avg, "costs": pf.cumulative_costs,
            "turnover": pf.cumulative_turnover, "realized": pf.realized_pnl_gross, "n": pf.transaction_count}


class FailingPortfolioStore(PortfolioCheckpointStore):
    def __init__(self, path) -> None:
        super().__init__(path)
        self.fail = False

    def write(self, snapshot):
        if self.fail:
            raise ResearchRunFailure(FailureCategory.PORTFOLIO_CHECKPOINT_ERROR, "simulated disk failure")
        super().write(snapshot)


class Accounting(unittest.TestCase):
    def test_ordinary_buy_and_sell_match_literals_and_the_legacy_path(self):
        pf = ResearchPortfolio(D("100000"))
        a = pf.apply_fill("f1", "X", "BUY", 10, D("50"), D("1.5"))
        b = pf.apply_fill("f2", "X", Action.SELL, 4, D("60"), D("1"))
        self.assertIs(a.status, FillApplyStatus.APPLIED)
        self.assertIs(b.status, FillApplyStatus.APPLIED)
        self.assertEqual(state(pf, "X"), {"cash": D("99737.5"), "qty": 6, "avg": D("50"), "costs": D("2.5"),
                                          "turnover": D("740"), "realized": D("40"), "n": 2})
        legacy = ResearchPortfolio(D("100000"))
        legacy.buy("X", 10, D("50"), D("1.5"))
        legacy.sell("X", 4, D("60"), D("1"))
        self.assertEqual(state(legacy, "X"), state(pf, "X"))

    def test_same_fill_id_twice_changes_state_once(self):
        pf = ResearchPortfolio(D("100000"))
        pf.apply_fill("f1", "X", "BUY", 10, D("50"), D("1.5"))
        once = state(pf, "X")
        for _ in range(3):
            r = pf.apply_fill("f1", "X", "BUY", 10, D("50.0"), D("1.50"))   # equal Decimal values, different spelling
            self.assertIs(r.status, FillApplyStatus.ALREADY_APPLIED)
            self.assertIsNone(r.change)
        self.assertEqual(state(pf, "X"), once)
        self.assertEqual(once["n"], 1)

    def test_conflicting_payload_fails_closed_for_every_material_field(self):
        base = ("f1", "X", "BUY", 10, D("50"), D("1.5"))
        for i, alt in enumerate([("Y",), ("SELL",), (11,), (D("51"),), (D("2"),)]):
            pf = ResearchPortfolio(D("100000"))
            pf.apply_fill(*base)
            before = state(pf, "X")
            args = list(base)
            args[i + 1] = alt[0]
            with self.assertRaises(ResearchRunFailure) as cm:
                pf.apply_fill(*args)
            self.assertIs(cm.exception.category, FailureCategory.ACCOUNTING_ERROR)
            self.assertEqual(state(pf, "X"), before)
            self.assertEqual(pf.applied_fill_ids(), ("f1",))

    def test_invalid_fills_rejected_and_change_nothing(self):
        pf = ResearchPortfolio(D("1000"))
        for args in [("", "X", "BUY", 1, D("1"), D("0")), ("f", "", "BUY", 1, D("1"), D("0")),
                     ("f", "X", "HOLD", 1, D("1"), D("0")), ("f", "X", "BUY", 0, D("1"), D("0")),
                     ("f", "X", "BUY", 1, D("-1"), D("0")), ("f", "X", "BUY", 1, D("1"), D("-1")),
                     ("f", "X", "BUY", 11, D("100"), D("0")),      # insufficient cash
                     ("f", "X", "SELL", 1, D("1"), D("0"))]:       # nothing held
            with self.assertRaises(ResearchRunFailure):
                pf.apply_fill(*args)
        self.assertEqual(pf.transaction_count, 0)
        self.assertEqual((pf.cash, pf.applied_fill_ids()), (D("1000"), ()))

    def test_checkpointed_portfolio_rejects_direct_buy_sell_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            st = PortfolioCheckpointStore(Path(td) / "pf.json")
            pf = ResearchPortfolio(D("1000"), checkpoint=st)
            with self.assertRaises(ResearchRunFailure):
                pf.buy("X", 1, D("1"), D("0"))
            with self.assertRaises(ResearchRunFailure) as cm:
                ResearchPortfolio(D("1000"), checkpoint=st)
            self.assertIs(cm.exception.category, FailureCategory.PORTFOLIO_CHECKPOINT_ERROR)
        mixed = ResearchPortfolio(D("1000"))
        mixed.buy("X", 1, D("1"), D("0"))
        with self.assertRaises(ResearchRunFailure):
            mixed.snapshot()


class Settlement(Base):
    def setUp(self):
        super().setUp()
        self.pstore = FailingPortfolioStore(Path(self._td.name) / "portfolio.json")
        self.pf = ResearchPortfolio(self.rig.opening.cash, checkpoint=self.pstore)

    def book_lifecycle(self):
        req, rd = self.new_order()
        self.rig.mgr.submit(req, rd, self.rig.broker, self.rig.session)
        reps = list(self.rig.advance(1)) + list(self.rig.advance(2))
        for ev in self.rig.fill_events(reps):
            self.rig.mgr.apply_event(ev)           # lifecycle checkpointed; portfolio untouched
        self.reps = reps
        self.expected = reference(self.rig.opening.cash, [("BUY", int(r.fill.quantity), D(str(r.fill.price)),
                                                           r.charges.total_cost) for r in reps])
        return reps

    def restart_both(self):
        m = self.restart()
        pf = ResearchPortfolio.restore_from_store(self.pstore)
        self.assertIsNot(pf, self.pf)
        self.pf = pf
        return m, pf

    def test_crash_after_lifecycle_ingestion_before_portfolio_booking_applies_once(self):
        self.book_lifecycle()
        m, pf = self.restart_both()                # portfolio checkpoint is just the initial, empty state
        self.assertEqual(pf.transaction_count, 0)
        res = apply_pending_fills(m, pf)
        self.assertEqual([r.status for r in res], [FillApplyStatus.APPLIED] * 2)
        self.assertEqual(state(pf), self.expected)
        self.assertEqual(m.fills_pending_portfolio_application(), ())
        self.assertEqual(apply_pending_fills(m, pf), [])
        self.assertEqual(state(pf), self.expected)

    def test_crash_after_portfolio_commit_before_mark_applied_never_double_books(self):
        reps = self.book_lifecycle()
        first = reps[0]
        self.pf.apply_fill(first.fill.fill_id, A, "BUY", int(first.fill.quantity), D(str(first.fill.price)),
                           first.charges.total_cost)           # durable commit ...
        # ... process dies before mark_portfolio_applied(first). Restart both halves from disk.
        m, pf = self.restart_both()
        self.assertEqual(pf.transaction_count, 1)
        self.assertEqual({f.fill_id for _k, f in m.fills_pending_portfolio_application()},
                         {r.fill.fill_id for r in reps})         # lifecycle still believes both are pending
        res = apply_pending_fills(m, pf)
        self.assertEqual([r.status for r in res], [FillApplyStatus.ALREADY_APPLIED, FillApplyStatus.APPLIED])
        self.assertEqual(state(pf), self.expected)
        self.assertEqual(m.fills_pending_portfolio_application(), ())
        m2 = self.restart()                                      # the confirmation itself is durable
        self.assertEqual(m2.fills_pending_portfolio_application(), ())
        self.assertEqual(state(ResearchPortfolio.restore_from_store(self.pstore)), self.expected)

    def test_crash_after_every_fill_committed_before_any_mark(self):
        self.book_lifecycle()
        for r in self.reps:
            self.pf.apply_fill(r.fill.fill_id, A, "BUY", int(r.fill.quantity), D(str(r.fill.price)), r.charges.total_cost)
        m, pf = self.restart_both()
        res = apply_pending_fills(m, pf)
        self.assertEqual([r.status for r in res], [FillApplyStatus.ALREADY_APPLIED] * 2)
        self.assertEqual(state(pf), self.expected)

    def test_failure_before_commit_leaves_fill_eligible_for_later(self):
        self.book_lifecycle()
        self.pstore.fail = True
        before = state(self.pf)
        with self.assertRaises(ResearchRunFailure):
            apply_pending_fills(self.rig.mgr, self.pf)
        self.assertEqual(state(self.pf), before)                 # live object untouched
        self.assertEqual(self.pf.applied_fill_ids(), ())
        self.assertEqual(len(self.rig.mgr.fills_pending_portfolio_application()), 2)   # still pending: NOT marked
        self.assertEqual(state(ResearchPortfolio.restore_from_store(self.pstore)), before)   # disk untouched too
        self.pstore.fail = False
        apply_pending_fills(self.rig.mgr, self.pf)               # later, healthy: applied once
        self.assertEqual(state(self.pf), self.expected)

    def test_persistence_failure_is_not_reported_as_settlement(self):
        self.book_lifecycle()
        self.pstore.fail = True
        with self.assertRaises(ResearchRunFailure) as cm:
            self.pf.apply_fill("fx", A, "BUY", 1, D("50"), D("1"))
        self.assertIs(cm.exception.category, FailureCategory.PORTFOLIO_CHECKPOINT_ERROR)
        self.assertFalse(self.pf.has_applied("fx"))
        self.assertEqual(self.pf.transaction_count, 0)

    def test_replay_of_broker_evidence_and_duplicate_events_after_recovery_changes_nothing(self):
        self.book_lifecycle()
        m, pf = self.restart_both()
        apply_pending_fills(m, pf)
        events = self.rig.fill_events(self.reps)
        for _ in range(3):
            for ev in events:
                m.apply_event(ev)
            m.recover_after_restart(self.rig.broker, self.rig.session)
            self.assertEqual(apply_pending_fills(m, pf), [])
            for r in self.reps:                                  # direct duplicate booking is also a no-op
                dup = pf.apply_fill(r.fill.fill_id, A, "BUY", int(r.fill.quantity), D(str(r.fill.price)),
                                    r.charges.total_cost)
                self.assertIs(dup.status, FillApplyStatus.ALREADY_APPLIED)
        self.assertEqual(state(pf), self.expected)

    def test_reconciliation_after_recovery_against_independent_broker_evidence(self):
        self.book_lifecycle()
        self.pf.apply_fill(self.reps[0].fill.fill_id, A, "BUY", int(self.reps[0].fill.quantity),
                           D(str(self.reps[0].fill.price)), self.reps[0].charges.total_cost)
        m, pf = self.restart_both()
        apply_pending_fills(m, pf)
        m.recover_after_restart(self.rig.broker, self.rig.session)
        snap = pf.positions_snapshot()
        res = reconcile_execution(m, self.rig.opening,
                                  LedgerView(pf.cash, {A: pf.quantity(A)}, {A: D(snap[0]["avg_cost"])}),
                                  self.rig.broker_view(), self.rig.broker.order_statuses(self.rig.session),
                                  tuple(self.rig.broker.get_fills(self.rig.session)))
        self.assertTrue(res.consistent, res.mismatches)
        b = self.rig.broker_view()
        self.assertEqual((pf.cash, pf.quantity(A)), (b.cash, b.positions[A]))
        self.assertEqual(pf.cash, self.expected["cash"])

    def test_unknown_charges_are_never_settled_as_zero(self):
        self.book_lifecycle()
        key, f = self.rig.mgr.fills_pending_portfolio_application()[0]
        rec = self.rig.mgr.record(key)
        rec.applied_fills[f.fill_id] = type(f)(**{**f.__dict__, "charges_total": None})
        with self.assertRaises(ResearchRunFailure) as cm:
            apply_pending_fills(self.rig.mgr, self.pf)
        self.assertIs(cm.exception.category, FailureCategory.RECONCILIATION_REQUIRED)
        self.assertEqual(self.pf.transaction_count, 0)


class CorruptCheckpoints(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.store = PortfolioCheckpointStore(Path(self._td.name) / "pf.json")
        self.pf = ResearchPortfolio(D("100000"), checkpoint=self.store)
        self.pf.apply_fill("f1", "X", "BUY", 10, D("50"), D("1.5"))
        self.pf.apply_fill("f2", "X", "SELL", 4, D("60"), D("1"))

    def assertFailsClosed(self):
        with self.assertRaises(ResearchRunFailure) as cm:
            ResearchPortfolio.restore_from_store(self.store)
        self.assertIs(cm.exception.category, FailureCategory.PORTFOLIO_CHECKPOINT_ERROR)

    def test_roundtrip_is_faithful(self):
        r = ResearchPortfolio.restore_from_store(self.store)
        self.assertEqual(state(r, "X"), state(self.pf, "X"))
        self.assertEqual(r.applied_fill_ids(), ("f1", "f2"))
        self.assertEqual(r.snapshot(), self.pf.snapshot())
        self.assertEqual(r.apply_fill("f1", "X", "BUY", 10, D("50"), D("1.5")).status, FillApplyStatus.ALREADY_APPLIED)

    def test_missing_checkpoint_is_not_an_empty_portfolio(self):
        self.store.path.unlink()
        self.assertFailsClosed()

    def test_garbage_and_non_object_files_fail_closed(self):
        for text in ("{not json", "[]", "", '"x"'):
            self.store.path.write_text(text)
            self.assertFailsClosed()

    def test_tampered_value_with_stale_checksum_fails(self):
        d = json.loads(self.store.path.read_text())
        d["body"]["cash"] = "999999"
        self.store.path.write_text(json.dumps(d))
        self.assertFailsClosed()

    def test_inconsistent_state_with_a_recomputed_valid_checksum_fails(self):
        for field, val in (("cash", "1"), ("realized_pnl_gross", "0"), ("transaction_count", 1),
                           ("cumulative_costs", "0"), ("cumulative_turnover", "1")):
            d = json.loads(self.pf.snapshot() and json.dumps(self.pf.snapshot()))
            d["body"][field] = val
            d["checksum"] = hash_json_stable(d["body"])
            self.store.path.write_text(json.dumps(d))
            self.assertFailsClosed()

    def test_ledger_tampering_with_valid_checksum_fails(self):
        mutate = (lambda b: b["applied_fills"].pop(), lambda b: b["applied_fills"].append(dict(b["applied_fills"][0])),
                  lambda b: b["applied_fills"][0].update(quantity=11),
                  lambda b: b["applied_fills"][0].update(fingerprint="0" * 64),
                  lambda b: b["holdings"]["X"].update(quantity=99), lambda b: b.update(version=2))
        for fn in mutate:
            d = json.loads(json.dumps(self.pf.snapshot()))
            fn(d["body"])
            d["checksum"] = hash_json_stable(d["body"])
            self.store.path.write_text(json.dumps(d))
            self.assertFailsClosed()

    def test_malformed_fields_fail_closed_not_with_raw_exceptions(self):
        for fn in (lambda b: b.pop("cash"), lambda b: b.update(cash="abc"), lambda b: b.update(applied_fills=None)):
            d = json.loads(json.dumps(self.pf.snapshot()))
            fn(d["body"])
            d["checksum"] = hash_json_stable(d["body"])
            self.store.path.write_text(json.dumps(d))
            self.assertFailsClosed()

    def test_failed_write_leaves_previous_checkpoint_intact(self):
        good = self.store.path.read_bytes()
        bad = PortfolioCheckpointStore(Path(self._td.name) / "nodir" / "x")
        Path(self._td.name, "nodir").write_text("a file where a directory is needed")
        with self.assertRaises(ResearchRunFailure):
            bad.write(self.pf.snapshot())
        self.assertEqual(self.store.path.read_bytes(), good)


if __name__ == "__main__":
    unittest.main()
