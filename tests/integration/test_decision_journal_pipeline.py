"""Slice 8 — journal wired into the real PipelineHarness. SYNTHETIC; infrastructure evidence only,
not trading alpha, profitability, broker compatibility or live readiness."""

from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from domain.models.decision_record import DecisionRecord
from domain.models.enums import TerminalState
from domain.models.risk_decision import RiskCheckResult
from observability.decision_log.events import EventType
from observability.decision_log.journal import FileDecisionJournal, InMemoryJournal
from observability.decision_log.query import JournalReader, decision_record_from_dict
from research.harness.failures import FailureCategory, RunStatus
from research.harness.jsonio import dumps
from risk_execution.broker.adapters.simulated import SimulatedBrokerAdapter
from risk_execution.order_lifecycle import OrderLifecycleManager
from simulation import PipelineHarness
from tests.unit._pipeline_helpers import (
    broker_config,
    config,
    pipeline,
    risk_config,
    tier2,
    universe,
    weekly_bars,
)

ET = EventType


class FailAt(InMemoryJournal):
    """TEST-ONLY: fails the persistence of the nth event of a given type."""

    def __init__(self, run_id, event_type, nth=1):
        super().__init__(run_id)
        self.et, self.nth, self.seen = event_type, nth, 0

    def _persist(self, line):
        if json.loads(line)["event_type"] == self.et.value:
            self.seen += 1
            if self.seen == self.nth:
                raise OSError("simulated journal outage")
        super()._persist(line)


def go(fraction=0.3, pc_over=None, factory=None, harness=None, strat_wrap=None, **kw):
    box: dict = {}

    def f(rid):
        box["j"] = (factory or InMemoryJournal)(rid)
        return box["j"]

    strat, b = tier2(fraction)
    if strat_wrap:
        strat = strat_wrap(strat)
    res = (harness or PipelineHarness)().run(config(**kw.pop("cfg", {})), strat, weekly_bars(), [universe()],
                                              pipeline(b, **(pc_over or {})), journal_factory=f,
                                              evidence_class="SYNTHETIC_INTEGRATION", **kw)  # fmt: skip
    return res, box["j"], JournalReader.from_journal(box["j"])


def states(reader):
    return {s.terminal_state for s in reader.list_decisions(1000)}


class EndToEndReconstruction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res, cls.j, cls.r = go()

    def test_run_completes_and_journal_verifies(self):
        self.assertIs(self.res.run.status, RunStatus.COMPLETED, self.res.run.failure)
        self.assertTrue(self.r.verify().ok)
        self.assertEqual(self.res.journal_ref["event_count"], len(self.j.events()))
        self.assertEqual(self.res.journal_ref["content_digest"], self.j.content_digest())

    def test_full_chain_from_snapshot_to_reconciliation(self):
        d = next(s for s in self.r.list_decisions(1000) if s.terminal_state == "FILLED")
        c = self.r.decision_chain(d.decision_id)
        kinds = [e.event_type for e in c.events]
        for need in (ET.DECISION_STARTED, ET.INPUT_SNAPSHOT_LINKED, ET.CANDIDATE_EMITTED, ET.RISK_EVALUATED, ET.SIZING_EVALUATED,
                     ET.ORDER_INTENT, ET.SUBMISSION_RESULT, ET.ORDER_TRANSITION, ET.BROKER_EVENT, ET.FILL_RECORDED,
                     ET.PORTFOLIO_SETTLED, ET.DECISION_FINALIZED, ET.RECONCILIATION_RESULT):  # fmt: skip
            self.assertIn(need, kinds)
        # causal order within the decision's own events
        own = [e.event_type for e in c.events if e.decision_id == d.decision_id]
        self.assertLess(own.index(ET.ORDER_INTENT), own.index(ET.SUBMISSION_RESULT))
        self.assertLess(own.index(ET.FILL_RECORDED), own.index(ET.PORTFOLIO_SETTLED))
        self.assertEqual((c.status, c.reconciliation_status, c.missing_references), ("FINALIZED", "OK", ()))
        snap = c.sections["snapshot"][0].payload
        self.assertTrue(snap["snapshot_content_hash"] and snap["snapshot"]["feature_values"])
        fill = c.sections["fills"][0].payload
        self.assertTrue(fill["charges"], "itemised charges persisted with the fill")
        settled = c.sections["portfolio_settled"][0].payload["portfolio_snapshot"]
        self.assertIsNone(settled["equity"], "unmarked stage reports unknown, never a guess")
        for k in ("strategy_version_id", "risk_rule_version_id", "config_version_id", "data_snapshot_version",
                  "feature_set_version", "cost_schedule_version", "evidence_class"):  # fmt: skip
            self.assertTrue(c.versions.get(k), k)
        self.assertEqual(c.versions["evidence_class"], "SYNTHETIC_INTEGRATION")
        rec = decision_record_from_dict(c.decision_record)
        self.assertIsInstance(rec, DecisionRecord)
        self.assertIs(rec.terminal_state, TerminalState.FILLED)
        self.assertTrue(any("fill" in ln for ln in self.r.explain(d.decision_id)))

    def test_event_lookup_links_run_decision_and_correlation(self):
        e = next(x for x in self.r.events() if x.event_type is ET.FILL_RECORDED)
        got = self.r.get_event(e.event_id)
        self.assertEqual((got.run_id, got.decision_id), (self.res.run.run_id, e.decision_id))
        self.assertTrue(got.correlation_id and got.links["fill_id"])

    def test_every_decision_is_finalized_with_unique_ids_and_chain_ordered(self):
        ds = self.r.list_decisions(1000)
        self.assertEqual(len({d.decision_id for d in ds}), len(ds))
        self.assertTrue(all(d.status == "FINALIZED" for d in ds))
        seqs = [e.sequence for e in self.r.events()]
        self.assertEqual(seqs, list(range(1, len(seqs) + 1)))

    def test_identical_runs_are_idempotent_on_a_shared_file_journal(self):
        d = tempfile.mkdtemp()
        f = lambda rid: FileDecisionJournal(d, rid)  # noqa: E731
        a, _, _ = go(factory=lambda rid: f(rid))
        n1 = len(FileDecisionJournal(d, a.run.run_id).events())
        b, _, _ = go(factory=lambda rid: f(rid))
        self.assertEqual(len(FileDecisionJournal(d, b.run.run_id).events()), n1)
        self.assertEqual(a.journal_ref, b.journal_ref)
        self.assertTrue(JournalReader.from_file(d, a.run.run_id).verify().ok)


class NoTradeAndFailureOutcomes(unittest.TestCase):
    def test_hold_no_trade_and_distinct_from_no_candidate(self):
        _, _, r = go()
        st = states(r)
        self.assertTrue({"HOLD", "NO_TRADE", "FILLED"} <= st, st)
        nt = next(s for s in r.list_decisions(1000) if s.terminal_state == "NO_TRADE")
        c = r.decision_chain(nt.decision_id)
        self.assertEqual(c.sections["order_intent"], ())
        self.assertTrue(c.decision_record["rationale"] or c.sections["finalized"][0].payload["reason"])
        self.assertIsNone(c.decision_record["order_id"])

    def test_no_candidate_is_recorded_without_inventing_a_candidate(self):
        class Silent:
            def __init__(self, inner):
                self._i = inner

            def __getattr__(self, n):
                return getattr(self._i, n)

            def generate_candidate_trades(self, snaps, uni, prev):
                return [c for c in self._i.generate_candidate_trades(snaps, uni, prev) if c.instrument_id != snaps[0].instrument_id]

        _, _, r = go(strat_wrap=Silent)
        nc = [s for s in r.list_decisions(1000) if s.terminal_state == "NO_CANDIDATE"]
        self.assertTrue(nc)
        rec = r.decision_chain(nc[0].decision_id).decision_record
        self.assertIsNone(rec["candidate_trade_id"])
        self.assertEqual(r.decision_chain(nc[0].decision_id).sections["candidate"], ())

    def test_risk_veto_keeps_reason_and_inputs_and_has_no_order(self):
        res, _, r = go(pc_over=dict(risk=risk_config(max_position_fraction=Decimal("0.2"))))
        vs = [s for s in r.list_decisions(1000) if s.terminal_state == "REJECTED_AT_RISK"]
        self.assertTrue(vs)
        c = r.decision_chain(vs[0].decision_id)
        self.assertEqual((c.sections["sizing"], c.sections["order_intent"], c.sections["fills"]), ((), (), ()))
        rr1 = next(k for k in c.sections["risk"][0].payload["checks"] if k["check_id"] == "RR-1")
        self.assertEqual(rr1["outcome"], "FAIL")
        self.assertEqual(rr1["evidence"]["max_position_fraction"], "0.2")  # configured limit as active at the time
        self.assertIn("target_notional", rr1["evidence"])  # observed input
        self.assertEqual(c.sections["risk"][0].payload["verdict"], "REJECT")

    def test_slow_fills_produce_skipped_pending_and_confirmed_cancellation(self):
        _, _, r = go(pc_over=dict(broker=broker_config(max_fill_fraction_per_bar=Decimal("0.05"))))
        st = states(r)
        self.assertIn("SKIPPED_PENDING_ORDER", st)
        self.assertIn("CANCELLED", st)
        cx = next(s for s in r.list_decisions(1000) if s.terminal_state == "CANCELLED")
        c = r.decision_chain(cx.decision_id)
        self.assertTrue(any(e.payload["kind"] == "CANCELLED" for e in c.sections["broker_events"]))

    def test_broker_rejection_by_policy_is_finalized_with_broker_event(self):
        import dataclasses

        from data.features.builders import ContextFeatureBuilder
        from research.harness.config import OrderRejectionPolicy
        from intelligence.baseline.tier1_equal_weight import Tier1EqualWeightBuyHold
        from tests.unit._pipeline_helpers import ISINS, TEST_START, sizing_config

        u1, bars = [universe(ISINS[:1])], weekly_bars(ISINS[:1])
        spike = sorted(b.timestamp for b in bars if b.timestamp >= TEST_START)[1]
        bars = [dataclasses.replace(b, open=b.open * 1.5, high=b.high * 1.5, low=b.low * 1.5, close=b.close * 1.5)
                if b.timestamp == spike else b for b in bars]  # fmt: skip
        pc = pipeline(ContextFeatureBuilder(), sizing=sizing_config(cash_buffer=Decimal("0")),
                      risk=risk_config(max_position_fraction=Decimal("1.0")))  # fmt: skip
        box = {}
        res = PipelineHarness().run(config(order_rejection_policy=OrderRejectionPolicy.REJECT_AND_CONTINUE),
                                    Tier1EqualWeightBuyHold(), bars, u1, pc,
                                    journal_factory=lambda rid: box.setdefault("j", InMemoryJournal(rid)))  # fmt: skip
        self.assertIs(res.run.status, RunStatus.COMPLETED, res.run.failure)
        r = JournalReader.from_journal(box["j"])
        rj = next(s for s in r.list_decisions(1000) if s.terminal_state == "REJECTED_BY_BROKER")
        c = r.decision_chain(rj.decision_id)
        self.assertTrue(any(e.payload["kind"] == "REJECTED" for e in c.sections["broker_events"]))
        self.assertEqual(c.sections["fills"], ())

    def test_invalid_candidate_is_journaled_and_run_fails(self):
        class Dup:
            def __init__(self, inner):
                self._i = inner

            def __getattr__(self, n):
                return getattr(self._i, n)

            def generate_candidate_trades(self, snaps, uni, prev):
                out = self._i.generate_candidate_trades(snaps, uni, prev)
                return out + out[:1]  # duplicate -> INVALID_CANDIDATE

        res, _, r = go(strat_wrap=Dup)
        self.assertIs(res.run.failure.category, FailureCategory.INVALID_CANDIDATE)
        self.assertIn("REJECTED_INVALID_CANDIDATE", states(r))
        d = next(s for s in r.list_decisions(1000) if s.terminal_state == "REJECTED_INVALID_CANDIDATE")
        c = r.decision_chain(d.decision_id)
        self.assertEqual(c.sections["candidate_rejected"][0].payload["error_code"], "INVALID_CANDIDATE")
        self.assertEqual(c.sections["order_intent"], ())
        self.assertTrue(r.events()[-1].event_type is ET.OPERATIONAL_FAILURE)

    def test_reconciliation_blocked_is_visible_on_the_decision(self):
        done = {"n": 0}

        def inject(broker, t):
            for bid, bo in broker._orders.items():
                if bo.order.state.value == "PARTIALLY_FILLED" and not done["n"]:
                    done["n"] += 1
                    broker.inject_ambiguous_response(bid, "ack lost")

        res, _, r = go(pc_over=dict(broker=broker_config(max_fill_fraction_per_bar=Decimal("0.4"))), broker_fault_injector=inject)
        self.assertIs(res.run.failure.category, FailureCategory.RECONCILIATION_REQUIRED)
        d = next(s for s in r.list_decisions(1000) if s.terminal_state == "RECONCILIATION_REQUIRED")
        c = r.decision_chain(d.decision_id)
        self.assertEqual(c.reconciliation_status, "BLOCKED")
        self.assertTrue(c.sections["fills"], "the partial fill that did occur is retained")

    def test_unknown_submission_result_is_recorded_and_unresolved(self):
        orig, n = SimulatedBrokerAdapter.place_order, {"c": 0}

        def flaky(self, session, request):
            n["c"] += 1
            if n["c"] == 1:
                self.inject_fault("FAIL_AFTER_ACCEPT")
            return orig(self, session, request)

        with mock.patch.object(SimulatedBrokerAdapter, "place_order", flaky):
            res, _, r = go()
        self.assertIs(res.run.status, RunStatus.FAILED)
        sub = [e for e in r.events() if e.event_type is ET.SUBMISSION_RESULT]
        self.assertTrue(sub)
        self.assertEqual(sub[0].payload["outcome"], "UNCERTAIN")
        d = next(x for x in r.list_decisions(1000) if x.decision_id == sub[0].decision_id)
        self.assertNotEqual(d.terminal_state, "FILLED")


class JournalFailureSafety(unittest.TestCase):
    def test_no_journal_means_no_run_and_no_broker_call(self):
        strat, b = tier2(0.3)
        with mock.patch.object(SimulatedBrokerAdapter, "place_order", side_effect=AssertionError("broker called")) as pl:
            res = PipelineHarness().run(config(), strat, weekly_bars(), [universe()], pipeline(b))
        self.assertIs(res.run.status, RunStatus.FAILED)
        self.assertIs(res.run.failure.category, FailureCategory.JOURNAL_FAILURE)
        pl.assert_not_called()

    def test_journal_for_a_different_run_is_rejected(self):
        strat, b = tier2(0.3)
        res = PipelineHarness().run(config(), strat, weekly_bars(), [universe()], pipeline(b),
                                    journal_factory=lambda rid: InMemoryJournal("some_other_run"))  # fmt: skip
        self.assertIs(res.run.failure.category, FailureCategory.JOURNAL_FAILURE)

    def test_pre_submission_write_failure_means_broker_is_never_called(self):
        with mock.patch.object(SimulatedBrokerAdapter, "place_order", side_effect=AssertionError("broker called")) as pl:
            res, j, _ = go(factory=lambda rid: FailAt(rid, ET.ORDER_INTENT))
        self.assertIs(res.run.failure.category, FailureCategory.JOURNAL_FAILURE)
        pl.assert_not_called()
        self.assertTrue(j.failed)

    def test_post_submission_write_failure_halts_and_leaves_recovery_to_existing_lookup(self):
        seen: dict = {"orders": [], "halts": []}
        orig = SimulatedBrokerAdapter.place_order
        halt = OrderLifecycleManager.halt_external

        def spy(self, session, request):
            seen["adapter"], seen["session"] = self, session
            seen["orders"].append(request.idempotency_key)
            return orig(self, session, request)

        def hspy(self, code, detail, key=None):
            seen["halts"].append((code, key))
            return halt(self, code, detail, key)

        with mock.patch.object(SimulatedBrokerAdapter, "place_order", spy), \
             mock.patch.object(OrderLifecycleManager, "halt_external", hspy):  # fmt: skip
            res, j, _ = go(factory=lambda rid: FailAt(rid, ET.SUBMISSION_RESULT))
        self.assertIs(res.run.failure.category, FailureCategory.JOURNAL_FAILURE)
        self.assertEqual(len(seen["orders"]), 1, "no further risk-increasing order after the journal failure")
        self.assertEqual(seen["halts"], [("JOURNAL_FAILURE", seen["orders"][0])])
        found = seen["adapter"].find_order_by_client_key(seen["session"], seen["orders"][0])
        self.assertIsNotNone(found, "the order that may have reached the broker is recoverable via existing lookup")
        self.assertNotIn(ET.PORTFOLIO_SETTLED, [e.event_type for e in j.events()])
        self.assertEqual(res.telemetry["journal_append_failures"], 1)

    def test_fill_record_write_failure_never_claims_settlement(self):
        res, j, _ = go(factory=lambda rid: FailAt(rid, ET.FILL_RECORDED))
        self.assertIs(res.run.failure.category, FailureCategory.JOURNAL_FAILURE)
        self.assertEqual([e for e in j.events() if e.event_type in (ET.PORTFOLIO_SETTLED, ET.FILL_RECORDED)], [])
        self.assertIn("JOURNAL", str(res.run.failure.message).upper())

    def test_failed_run_reports_incomplete_decisions(self):
        res, j, r = go(factory=lambda rid: FailAt(rid, ET.SUBMISSION_RESULT))
        d = [s for s in r.list_decisions(1000) if s.status == "INCOMPLETE"]
        self.assertTrue(d)
        c = r.decision_chain(d[0].decision_id)
        self.assertIn("INCOMPLETE", " ".join(c.caveats))
        self.assertIsNone(c.decision_record)  # no fabricated final record


class EvidenceAndCompatibility(unittest.TestCase):
    def test_every_rule_check_carries_structured_evidence(self):
        _, _, r = go()
        seen = set()
        for e in r.events():
            if e.event_type is ET.RISK_EVALUATED and e.payload["verdict"] == "APPROVE":
                for k in e.payload["checks"]:
                    seen.add(k["check_id"])
                    self.assertTrue(k["evidence"], f"{k['check_id']} has no structured evidence")
        self.assertTrue({"RR-1", "RR-2", "RR-3", "RR-4", "RR-5", "RR-6", "RR-7", "RR-8", "RR-9"} <= seen, seen)

    def test_uncaptured_evidence_is_an_explicit_gap_not_reconstructed(self):
        self.assertEqual(RiskCheckResult("RR-1", True, "legacy-style").evidence, ())
        with self.assertRaises(ValueError):
            RiskCheckResult("RR-1", True, "x", evaluable=False)

    def test_sizing_event_links_candidate_and_risk_and_records_inputs(self):
        _, _, r = go()
        e = next(x for x in r.events() if x.event_type is ET.SIZING_EVALUATED)
        self.assertTrue(e.payload["candidate_id"] and e.payload["risk_decision_id"])
        self.assertIn("equity", e.payload["inputs"])
        self.assertIn("risk_quantity_ceiling", e.payload)

    def test_legacy_decision_record_fixture_still_reads_and_serialises_identically(self):
        fx = Path(__file__).resolve().parents[1] / "fixtures" / "legacy" / "decision_records_slice7.jsonl"
        lines = fx.read_text().splitlines()
        recs = [decision_record_from_dict(json.loads(x)) for x in lines]
        self.assertEqual(len(recs), 3)
        strat, b = tier2(0.3)
        res = PipelineHarness().run(config(), strat, weekly_bars(), [universe()], pipeline(b),
                                    journal_factory=lambda rid: InMemoryJournal(rid))  # fmt: skip
        now = [dumps(x, indent=None) for x in res.run.decision_records[:3]]
        self.assertEqual("".join(now), fx.read_text(), "DecisionRecord serialisation of existing artifacts is unchanged")

    def test_unsupported_decision_record_payload_fails_with_clear_error(self):
        from observability.decision_log.events import JournalError

        with self.assertRaises(JournalError):
            decision_record_from_dict({"__type__": "DecisionRecord", "instrument_id": "x"})

    def test_pipeline_artifacts_keep_run_files_and_add_journal_reference(self):
        from simulation.artifacts import pipeline_files

        res, _, _ = go()
        files = pipeline_files(res)
        self.assertIn("journal_ref.json", files)
        self.assertEqual(json.loads(files["journal_ref.json"])["content_digest"], res.journal_ref["content_digest"])
        for legacy in ("pipeline.json", "risk_decisions.jsonl", "reconciliation.jsonl"):
            self.assertIn(legacy, files)

    def test_secrets_in_strategy_rationale_are_not_persisted(self):
        import dataclasses

        class Leaky:
            def __init__(self, inner):
                self._i = inner

            def __getattr__(self, n):
                return getattr(self._i, n)

            def generate_candidate_trades(self, snaps, uni, prev):
                return [dataclasses.replace(c, rationale=c.rationale + " api_key=sk-FAKEFAKEFAKE12345678")
                        for c in self._i.generate_candidate_trades(snaps, uni, prev)]  # fmt: skip

        _, j, _ = go(strat_wrap=Leaky)
        blob = "".join(j.lines)
        self.assertNotIn("sk-FAKEFAKEFAKE12345678", blob)
        self.assertIn("[REDACTED]", blob)

    def test_telemetry_is_exposed_but_not_persisted_in_run_artifacts(self):
        from simulation.artifacts import pipeline_files

        res, _, _ = go()
        t = res.telemetry
        self.assertGreater(t["journal_events"], 0)
        self.assertEqual(t["reconciliation_unresolved_mismatches"], 0)
        self.assertNotIn("journal_append_latency", "".join(pipeline_files(res).values()))


if __name__ == "__main__":
    unittest.main()
