"""Slice 11 test helpers. SYNTHETIC fixtures only: no real announcements, no credentials."""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from data.adapters.disclosure_local_import import InstrumentMap, LocalDisclosureImport
from data.disclosures.store import ContextConfig, DisclosureStore
from intelligence.llm_component.model_version import (
    CutoffBasis,
    CutoffDeclaration,
    build_model_version,
)
from intelligence.llm_component.overlay import ConfidenceAdjustmentConfig
from intelligence.llm_component.provider import StubProvider, stub_signal
from intelligence.llm_component.signals import SignalConfig, SignalService

T0 = datetime(2024, 3, 1, 10, 0, tzinfo=UTC)
INGEST = datetime(2024, 3, 1, 9, 0, tzinfo=UTC)
CUTOFF = CutoffDeclaration(CutoffBasis.PROVIDER_DOCUMENTED, datetime(2023, 6, 30, tzinfo=UTC),
                           "SYNTHETIC TEST DECLARATION - not a real provider statement")  # fmt: skip


def imap(instrument_id: str = "INE000A01001") -> InstrumentMap:
    return InstrumentMap(by_isin={"INE000A01001": instrument_id},
                         by_exchange_symbol={("NSE", "AAA"): instrument_id})  # fmt: skip


def item(
    src="DOC-1",
    text="Company reports record quarterly profit.",
    published="2024-02-28T10:00:00+00:00",
    **kw,
):
    d = {"source_document_id": src, "exchange": "NSE", "symbol": "AAA", "isin": "INE000A01001",
         "published_at": published, "text": text, "title": "Results"}  # fmt: skip
    d.update(kw)
    return d


def load(items, instruments=None, ingest=INGEST):
    d = tempfile.mkdtemp()
    p = Path(d) / "disc.jsonl"
    p.write_text("\n".join(json.dumps(i) for i in items), encoding="utf-8")
    store = DisclosureStore()
    rep = LocalDisclosureImport(p, clock=lambda: ingest).load_into(store, instruments or imap())
    return store, rep


def context(store, instrument="INE000A01001", ts=T0, snap="snap-1", cfg=None):
    return store.build_context(instrument, ts, cfg or ContextConfig(), snap)


def service(responder=None, enabled=True, **cfg):
    prov = StubProvider(responder)
    return SignalService(
        prov, SignalConfig(enabled=enabled, **cfg), clock=lambda: T0, sleep=lambda s: None
    ), prov


def mv(parent="tier2_x", provider="STUB", model="stub-model-v1", cutoff=CUTOFF):
    return build_model_version(provider, model, cutoff, parent)


ADJ = ConfidenceAdjustmentConfig()
__all__ = [
    "ADJ",
    "CUTOFF",
    "INGEST",
    "T0",
    "context",
    "imap",
    "item",
    "load",
    "mv",
    "service",
    "stub_signal",
    "timedelta",
]
