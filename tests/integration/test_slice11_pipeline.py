"""Slice 11 - optional AI overlay inside the real Tier-2 pipeline. SYNTHETIC; infrastructure
evidence only - NOT evidence that the AI signal improves returns."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from data.adapters.disclosure_local_import import InstrumentMap, LocalDisclosureImport
from data.disclosures.store import ContextConfig, DisclosureStore
from intelligence.llm_component.overlay import ConfidenceAdjustmentConfig, DisclosureOverlayStrategy
from intelligence.llm_component.provider import ProviderTimeout, StubProvider, stub_signal
from intelligence.llm_component.signals import SignalConfig, SignalService, SignalStore
from observability.decision_log.events import EventType as ET
from observability.decision_log.query import JournalReader
from research.harness.failures import RunStatus
from simulation import PipelineHarness
from tests.integration.test_decision_journal_pipeline import go
from tests.unit._pipeline_helpers import ISINS, TEST_START
from tests.unit._slice11_helpers import CUTOFF, mv

PUBLISHED = "2026-03-25T10:00:00+00:00"
INGESTED = datetime(2026, 3, 25, 11, 0, tzinfo=UTC)


def disclosure_store(isins=ISINS, covered=None):
    items = [{"source_document_id": f"D-{i}", "exchange": "NSE", "symbol": f"S{i}", "isin": isin,
              "published_at": PUBLISHED, "title": "Results", "text": f"SYNTHETIC announcement for {isin}."}  # fmt: skip
             for i, isin in enumerate(isins) if covered is None or isin in covered]
    p = Path(tempfile.mkdtemp()) / "d.jsonl"
    p.write_text("\n".join(map(json.dumps, items)))
    st = DisclosureStore()
    rep = LocalDisclosureImport(p, clock=lambda: INGESTED).load_into(
        st, InstrumentMap({i: i for i in isins}, {("NSE", f"S{k}"): i for k, i in enumerate(isins)}))
    return st, rep


class _Recorder:
    """Records every candidate batch the base strategy emits (to know instruments/timestamps)."""

    def __init__(self, base):
        self.base = base
        self.strategy_version_id = base.strategy_version_id
        self.expected_feature_set_id = getattr(base, "expected_feature_set_id", None)
        self.seen = []

    def generate_candidate_trades(self, *a):
        out = self.base.generate_candidate_trades(*a)
        self.seen.extend(out)
        return out


def run_overlay(mode="POSITIVE", covered=None, provider=None, enabled=True, cfg=None, pc_over=None):
    """mode: sentiment string | 'FAIL' | 'NONE' (no disclosures)."""
    store, _ = disclosure_store(covered=covered if mode != "NONE" else ())
    box = {}

    def wrap(base):
        def lookup(iid, ts):
            return box["signals"].get(iid, ts)

        o = DisclosureOverlayStrategy(base, lookup, cfg or ConfidenceAdjustmentConfig(), mv(base.strategy_version_id))
        box["overlay"] = o
        return o

    # First pass needs candidates' (instrument, timestamp) to precompute the signals; the harness
    # is deterministic, so a baseline pass supplies exactly those keys.
    _, _, _ = go()
    rec_box = {}
    go(strat_wrap=lambda b: rec_box.setdefault("r", _Recorder(b)))
    signals = SignalStore()

    def responder(req):
        iid = req.user.split("\n")[0].split(": ")[1]
        d = [ln for ln in req.user.split("\n") if ln.startswith("<document id=")]
        ids = [ln.split('"')[1] for ln in d]
        ctx_like = type("C", (), {"document_ids": tuple(ids)})()
        return json.dumps(stub_signal(ctx_like, mode))

    class P(StubProvider):
        def complete(self, req):
            if mode == "FAIL":
                raise ProviderTimeout("simulated")
            return super().complete(req)

    prov = provider or P(responder)
    svc = SignalService(prov, SignalConfig(enabled=enabled, max_requests=10_000), clock=lambda: INGESTED, sleep=lambda s: None)
    for c in rec_box["r"].seen:
        signals.put(svc.evaluate(store.build_context(c.instrument_id, c.timestamp, ContextConfig(lookback_days=366), c.input_snapshot_id)))
    box["signals"] = signals
    res, j, r = go(strat_wrap=wrap, pc_over=pc_over)
    return res, j, r, box["overlay"], signals, svc


def _strip(o):
    """Drop identity/provenance keys (they legitimately differ when a candidate is re-identified)."""
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items()
                if not (k.endswith("_id") or k.endswith("_ids") or "candidate" in k or k in ("rationale", "confidence", "idempotency_key"))}  # fmt: skip
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def comparable(reader):
    """Economic outcome downstream of the strategy (verdicts, quantities, fills, portfolio),
    independent of candidate re-identification and of the additive AI journal events."""
    keep = (ET.RISK_EVALUATED, ET.SIZING_EVALUATED, ET.ORDER_INTENT, ET.FILL_RECORDED, ET.PORTFOLIO_SETTLED)
    return [(e.event_type.value, json.dumps(_strip(e.payload), sort_keys=True, default=str)) for e in reader.events() if e.event_type in keep]


class AiDisabledInvariant(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res0, cls.j0, cls.r0 = go()

    def test_baseline_is_deterministic_and_has_no_ai_events(self):
        res, j, r = go()
        self.assertEqual(comparable(r), comparable(self.r0))
        self.assertEqual([e for e in r.events() if e.event_type is ET.AI_SIGNAL_EVALUATED], [])

    def test_overlay_with_no_disclosures_equals_baseline_downstream(self):
        res, j, r, o, sigs, svc = run_overlay("NONE")
        self.assertIs(res.run.status, RunStatus.COMPLETED, res.run.failure)
        self.assertEqual(comparable(r), comparable(self.r0))
        self.assertEqual({k for k in svc.status_counts}, {"EMPTY_CONTEXT"})
        self.assertTrue(r.verify().ok)

    def test_disabled_service_never_calls_provider_and_matches_baseline(self):
        prov = StubProvider()
        res, j, r, o, sigs, svc = run_overlay("POSITIVE", provider=prov, enabled=False)
        self.assertEqual(prov.calls, 0)
        self.assertEqual(comparable(r), comparable(self.r0))
        self.assertEqual({k for k in svc.status_counts}, {"DISABLED"})

    def test_provider_failure_preserves_baseline(self):
        res, j, r, o, sigs, svc = run_overlay("FAIL")
        self.assertIs(res.run.status, RunStatus.COMPLETED)
        self.assertEqual(comparable(r), comparable(self.r0))
        self.assertEqual({k for k in svc.status_counts}, {"TIMEOUT"})

    def test_unmapped_documents_preserve_baseline(self):
        res, j, r, o, sigs, svc = run_overlay("POSITIVE", covered=())
        self.assertEqual(comparable(r), comparable(self.r0))


class AiEnabledLineage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = go()
        cls.res, cls.j, cls.r, cls.o, cls.sigs, cls.svc = run_overlay("POSITIVE")

    def test_run_completes_journal_verifies(self):
        self.assertIs(self.res.run.status, RunStatus.COMPLETED, self.res.run.failure)
        self.assertTrue(self.r.verify().ok)

    def test_actions_and_size_hints_identical_confidence_changed(self):
        base = {(e.payload["candidate_timestamp"], e.payload["action"], e.payload["size_hint"], e.payload["input_snapshot_id"]): e
                for e in self.base[2].events() if e.event_type is ET.CANDIDATE_EMITTED}  # fmt: skip
        ai = {(e.payload["candidate_timestamp"], e.payload["action"], e.payload["size_hint"], e.payload["input_snapshot_id"]): e
              for e in self.r.events() if e.event_type is ET.CANDIDATE_EMITTED}  # fmt: skip
        self.assertEqual(set(base), set(ai))  # BUY/SELL/HOLD and size_hint untouched
        changed = [k for k in base if base[k].payload["confidence"] != ai[k].payload["confidence"]]
        self.assertTrue(changed)
        for k in changed:
            self.assertLessEqual(abs(float(ai[k].payload["confidence"]) - float(base[k].payload["confidence"])), 0.10 + 1e-9)
            self.assertEqual(ai[k].payload["model_version_id"], self.o.model_version.version_id)

    def test_orders_and_fills_unaffected_because_confidence_is_not_a_sizing_input(self):
        self.assertEqual(comparable(self.r), comparable(self.base[2]))

    def test_journal_records_full_ai_provenance(self):
        evs = [e for e in self.r.events() if e.event_type is ET.AI_SIGNAL_EVALUATED]
        self.assertTrue(evs)
        p = next(e.payload for e in evs if e.payload["applied"])
        sig = p["signal"]
        for k in ("context_hash", "input_snapshot_id", "provider_status", "model_identifier", "prompt_hash",
                  "output_schema_version", "document_ids", "requested_at", "completed_at", "response_hash", "interpretation"):  # fmt: skip
            self.assertIn(k, sig, k)
        for k in ("adjustment_version", "original_confidence", "adjusted_confidence", "baseline_strategy_version_id",
                  "overlay_strategy_version_id", "model_version_id", "original_candidate_id", "original_action"):  # fmt: skip
            self.assertIn(k, p, k)
        self.assertEqual(p["label"], "RESEARCH SIGNAL ONLY")
        self.assertNotIn("api_key", json.dumps(p, default=str).lower())

    def test_journal_snapshot_id_matches_signal_context(self):
        for e in self.r.events():
            if e.event_type is ET.AI_SIGNAL_EVALUATED and e.payload["signal"]:
                self.assertTrue(e.payload["signal"]["input_snapshot_id"])

    def test_future_availability_cannot_influence_earlier_decision(self):
        # documents are ingested 2026-03-25; a decision before that must see an empty context
        st, _ = disclosure_store()
        early = st.build_context(ISINS[0], datetime(2026, 3, 1, tzinfo=UTC))
        self.assertTrue(early.is_empty)

    def test_same_frozen_input_reproduces_identical_artifacts(self):
        res2, j2, r2, o2, s2, svc2 = run_overlay("POSITIVE")
        a = [e.payload for e in self.r.events() if e.event_type is ET.AI_SIGNAL_EVALUATED]
        b = [e.payload for e in r2.events() if e.event_type is ET.AI_SIGNAL_EVALUATED]
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))
        self.assertEqual(self.o.model_version.version_id, o2.model_version.version_id)

    def test_different_adjustment_config_creates_distinguishable_strategy_version(self):
        _, _, _, o2, _, _ = run_overlay("POSITIVE", cfg=ConfidenceAdjustmentConfig(max_delta=0.05))
        self.assertNotEqual(self.o.overlay_version_id, o2.overlay_version_id)
        self.assertEqual(self.o.strategy_version_id, o2.strategy_version_id)  # run-facing id stays the baseline


class RiskVetoRemainsAuthoritative(unittest.TestCase):
    def test_active_kill_switch_vetoes_everything_even_with_strong_ai_signals(self):
        from risk_execution.risk_engine.config import KillSwitchState
        from tests.unit._pipeline_helpers import pipeline, tier2

        over = None
        res, j, r, o, s, svc = run_overlay("POSITIVE", pc_over=dict(kill_switch=KillSwitchState.ACTIVE))
        self.assertTrue(svc.status_counts.get("OK"))  # strong signals really were produced
        self.assertEqual(len(res.orders), 0)
        self.assertEqual(len(res.broker_fills), 0)
        self.assertTrue(all(rd["verdict"] != "APPROVE" for rd in res.risk_decisions))
        self.assertFalse(hasattr(o, "place_order") or hasattr(o, "submit_order") or hasattr(o, "approve"))
        del over, pipeline, tier2

    def test_model_output_cannot_approve_or_submit(self):
        c = type("C", (), {"document_ids": ("x",)})()
        bad = json.dumps({**stub_signal(c, "POSITIVE"), "risk_approved": True, "order": {"qty": 10}})
        svc = SignalService(StubProvider(bad), SignalConfig(enabled=True), clock=lambda: INGESTED)
        st, _ = disclosure_store()
        rec = svc.evaluate(st.build_context(ISINS[0], datetime(2026, 4, 6, tzinfo=UTC)))
        self.assertFalse(rec.has_signal)


if __name__ == "__main__":
    unittest.main()
