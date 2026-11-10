"""Slice 12 - signal-level point-in-time and provenance audit. SYNTHETIC fixtures."""

from __future__ import annotations

import dataclasses
import json
import unittest
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta

from domain.models.disclosure import DisclosureStatus
from intelligence.llm_component.prompt import prompt_hash
from intelligence.llm_component.provider import StubProvider, stub_signal
from intelligence.llm_component.schema import OUTPUT_SCHEMA_VERSION
from intelligence.llm_component.signals import SignalConfig, SignalService
from research.ai_eval.pit_audit import Provenance, applied_but_ineligible, audit_signals, classify_provenance
from tests.unit._slice11_helpers import CUTOFF, INGEST, T0, context, item, load

W = (T0 - timedelta(days=1), T0 + timedelta(days=30))
INST = "INE000A01001"
KEY = (INST, T0.isoformat())


def make(items=None, ingest=INGEST):
    store, _ = load(items or [item()], ingest=ingest)
    ctx = context(store, snap="snap-1")
    svc = SignalService(StubProvider(lambda r: json.dumps(stub_signal(ctx, "POSITIVE"))), SignalConfig(enabled=True), clock=lambda: T0, sleep=lambda s: None)
    return store, svc.evaluate(ctx)


def audit(sig, store, **over):
    kw = dict(documents={d.document_id: d for d in store.records()}, expected_snapshot_ids={KEY: "snap-1"},
              model_cutoff=CUTOFF.cutoff, window=W, expected_schema_version=OUTPUT_SCHEMA_VERSION, expected_prompt_hash=prompt_hash())  # fmt: skip
    kw.update(over)
    payloads = sig if isinstance(sig, list) else [sig.to_payload()]
    return audit_signals(payloads, **kw)


class Clean(unittest.TestCase):
    def test_valid_signal_is_eligible_and_classified_offline_fixture(self):
        store, sig = make()
        rep = audit(sig, store)
        self.assertEqual(rep.counts()["eligible"], 1)
        self.assertEqual(rep.entries[0].provenance, Provenance.OFFLINE_FIXTURE)
        self.assertEqual(rep.exclusion_log, [])


class Leakage(unittest.TestCase):
    def reasons(self, rep):
        return set(rep.entries[0].reasons)

    def test_snapshot_missing_and_mismatch_and_unknown_key(self):
        store, sig = make()
        p = sig.to_payload()
        self.assertIn("SNAPSHOT_ID_MISSING", self.reasons(audit([{**p, "input_snapshot_id": None}], store)))
        self.assertIn("SNAPSHOT_ID_MISMATCH", self.reasons(audit([{**p, "input_snapshot_id": "snap-OTHER"}], store)))
        self.assertIn("SNAPSHOT_ID_MISMATCH", self.reasons(audit(sig, store, expected_snapshot_ids={})))

    def test_future_document_availability_is_excluded_not_repaired(self):
        store, sig = make()
        doc = store.records()[0]
        late = dataclasses.replace(doc, available_at=T0 + timedelta(hours=1))
        rep = audit(sig, store, documents={doc.document_id: late})
        self.assertIn("DOC_NOT_AVAILABLE_AT_DECISION", self.reasons(rep))
        self.assertFalse(rep.entries[0].eligible)
        self.assertEqual(len(rep.exclusion_log), 1)

    def test_document_published_after_decision(self):
        store, sig = make()
        doc = store.records()[0]
        bad = dataclasses.replace(doc, published_at=T0 + timedelta(days=1), available_at=T0 + timedelta(days=1))
        self.assertIn("DOC_PUBLISHED_AFTER_DECISION", self.reasons(audit(sig, store, documents={doc.document_id: bad})))

    def test_document_missing_unknown_or_inconsistent(self):
        store, sig = make()
        doc = store.records()[0]
        self.assertIn("DOC_UNKNOWN", self.reasons(audit(sig, store, documents={})))
        rej = dataclasses.replace(doc, available_at=None, status=DisclosureStatus.REJECTED)  # domain forbids usable-without-availability
        r = self.reasons(audit(sig, store, documents={doc.document_id: rej}))
        self.assertTrue({"DOC_AVAILABILITY_MISSING", "DOC_STATUS_UNUSABLE"} <= r)
        # the domain model forbids this combination at construction; the audit still defends against foreign objects
        inc = SimpleNamespace(status=doc.status, available_at=doc.published_at - timedelta(days=1),
                              published_at=doc.published_at, ingested_at=doc.ingested_at)
        self.assertIn("DOC_TIMESTAMPS_INCONSISTENT", self.reasons(audit(sig, store, documents={doc.document_id: inc})))

    def test_model_cutoff_overlap_and_undeclared(self):
        store, sig = make()
        self.assertIn("MODEL_CUTOFF_OVERLAP", self.reasons(audit(sig, store, model_cutoff=T0 + timedelta(days=1))))
        self.assertIn("MODEL_CUTOFF_UNDECLARED", self.reasons(audit(sig, store, model_cutoff=None)))

    def test_outside_window_schema_and_prompt_mismatch(self):
        store, sig = make()
        self.assertIn("OUTSIDE_EVALUATION_WINDOW", self.reasons(audit(sig, store, window=(T0 + timedelta(days=1), T0 + timedelta(days=9)))))
        self.assertIn("SCHEMA_VERSION_MISMATCH", self.reasons(audit(sig, store, expected_schema_version="v0")))
        self.assertIn("PROMPT_HASH_MISMATCH", self.reasons(audit(sig, store, expected_prompt_hash="x")))

    def test_real_provider_must_return_a_model_identifier(self):
        store, sig = make()
        p = {**sig.to_payload(), "provider_name": "ANTHROPIC", "resolved_model_identifier": None, "resolved_model_identifier_status": "UNAVAILABLE",
             "completed_at": T0 + timedelta(minutes=1)}  # fmt: skip
        rep = audit([p], store)
        self.assertIn("MODEL_ID_UNRESOLVED", rep.entries[0].reasons)

    def test_duplicates_and_contradictory_duplicates(self):
        store, sig = make()
        p = sig.to_payload()
        self.assertIn("DUPLICATE_SIGNAL", audit([p, dict(p)], store).entries[1].reasons)
        self.assertIn("CONTRADICTORY_DUPLICATE", audit([p, {**p, "response_hash": "different"}], store).entries[1].reasons)

    def test_model_identifier_drift_is_a_run_level_finding(self):
        store, sig = make()
        p = sig.to_payload()
        a = {**p, "resolved_model_identifier": "m-1", "resolved_model_identifier_status": "RETURNED"}
        b = {**p, "decision_timestamp": T0 + timedelta(days=1), "resolved_model_identifier": "m-2", "resolved_model_identifier_status": "RETURNED"}
        rep = audit([a, b], store, expected_snapshot_ids={KEY: "snap-1", (INST, (T0 + timedelta(days=1)).isoformat()): "snap-1"})
        self.assertTrue(any("MODEL_ID_DRIFT" in f for f in rep.run_level_findings))


class Provenance_(unittest.TestCase):
    def test_classification(self):
        base = {"provider_name": "ANTHROPIC", "provider_status": "OK", "completed_at": T0 - timedelta(minutes=1)}
        self.assertEqual(classify_provenance({**base, "provider_name": "STUB"}, T0), Provenance.OFFLINE_FIXTURE)
        self.assertEqual(classify_provenance(base, T0), Provenance.LIVE_CAPTURED)
        self.assertEqual(classify_provenance({**base, "completed_at": T0 + timedelta(days=400)}, T0), Provenance.RETROSPECTIVE_REPLAY)
        self.assertEqual(classify_provenance({**base, "provider_status": "TIMEOUT"}, T0), Provenance.NO_PROVIDER_OUTPUT)


class JournalSideDetector(unittest.TestCase):
    def test_applied_ineligible_signal_is_a_breach(self):
        _, sig = make()
        ev = {"applied": True, "signal": {"instrument_id": INST, "decision_timestamp": T0.isoformat()}}
        self.assertEqual(applied_but_ineligible([ev], frozenset({KEY})), [])
        bad = applied_but_ineligible([ev], frozenset())
        self.assertEqual(bad[0]["reason"], "APPLIED_INELIGIBLE_SIGNAL")
        self.assertEqual(applied_but_ineligible([{"applied": True}], frozenset())[0]["reason"], "APPLIED_WITHOUT_SIGNAL")
        self.assertEqual(applied_but_ineligible([{"applied": False, "signal": ev["signal"]}], frozenset()), [])


if __name__ == "__main__":
    unittest.main()
