"""Slice 11 - disclosure data contract and point-in-time rules. SYNTHETIC fixtures."""

from __future__ import annotations

import unittest
from datetime import timedelta

from data.disclosures.source import NotConnectedSource, SourceStatus
from data.disclosures.store import ContextConfig, DisclosureStore
from domain.models.disclosure import DisclosureRecord, DisclosureStatus
from tests.unit._slice11_helpers import INGEST, T0, context, imap, item, load


class IngestionTests(unittest.TestCase):
    def test_valid_ingestion_preserves_four_times_hash_and_ref(self):
        s, rep = load([item(event_time="2024-02-27T00:00:00+00:00", source_reference="local:file-1")])
        (r,) = s.records()
        self.assertEqual(r.status, DisclosureStatus.VALID)
        self.assertEqual((r.event_time.day, r.published_at.day), (27, 28))
        self.assertEqual(r.ingested_at, INGEST)
        self.assertEqual(r.available_at, INGEST)  # max(published, ingested)
        self.assertEqual(len(r.content_hash), 64)
        self.assertEqual(r.source_reference, "local:file-1")
        self.assertEqual(rep["by_status"], {"VALID": 1})

    def test_invalid_records_rejected_with_reason_never_dropped(self):
        s, rep = load([item(text=""), item(src="X", published=None), item(src="Y", published="2024-02-28T10:00:00")])
        self.assertEqual(rep["by_status"], {"REJECTED": 3})
        self.assertEqual(len(rep["rejections"]), 3)
        self.assertTrue(any("naive" in w for r in rep["rejections"] for w in r["warnings"]))

    def test_missing_publication_time_rejected(self):
        s, rep = load([item(published="")])
        self.assertEqual(s.records()[0].status, DisclosureStatus.REJECTED)

    def test_instrument_mapping_failure_is_unmapped_never_guessed(self):
        s, rep = load([item(isin=None, symbol="ZZZ"), item(src="B", isin="INE999Z99999", symbol=None, exchange=None)])
        self.assertEqual(rep["by_status"], {"UNMAPPED": 2})
        self.assertIsNone(s.records()[0].instrument_id)

    def test_conflicting_isin_and_symbol_not_mapped(self):
        m = imap()
        from data.adapters.disclosure_local_import import InstrumentMap

        m2 = InstrumentMap({"INE000A01001": "I1"}, {("NSE", "AAA"): "I2"})
        s, rep = load([item()], m2)
        self.assertEqual(s.records()[0].status, DisclosureStatus.UNMAPPED)
        del m

    def test_available_at_cannot_precede_published_or_ingested(self):
        s, rep = load([item(available_at="2024-02-01T00:00:00+00:00")])
        self.assertEqual(s.records()[0].status, DisclosureStatus.REJECTED)

    def test_idempotent_reimport_and_changed_text_is_new_record(self):
        s, _ = load([item(), item()])
        self.assertEqual(len(s.records()), 1)
        s2, _ = load([item(), item(text="Different revised text.")])
        self.assertEqual(len(s2.records()), 2)  # original is never overwritten

    def test_usable_record_requires_matching_hash(self):
        s, _ = load([item()])
        r = s.records()[0]
        with self.assertRaises(ValueError):
            DisclosureRecord(**{**{f: getattr(r, f) for f in r.__dataclass_fields__}, "text": "tampered"})

    def test_real_time_feed_is_not_connected(self):
        self.assertEqual(NotConnectedSource().status(), SourceStatus.NOT_CONNECTED)
        self.assertEqual(list(NotConnectedSource().read_raw()), [])


class PointInTimeTests(unittest.TestCase):
    def test_future_ingested_document_never_affects_a_past_decision(self):
        # event date in the past, but ingested AFTER the decision: unavailable at the decision time.
        s, _ = load([item(event_time="2024-01-01T00:00:00+00:00", published="2024-01-01T00:00:00+00:00")],
                    ingest=T0 + timedelta(days=30))  # fmt: skip
        ctx = context(s, ts=T0)
        self.assertTrue(ctx.is_empty)
        self.assertEqual(dict(ctx.excluded_counts), {"NOT_YET_AVAILABLE": 1})
        self.assertFalse(context(s, ts=T0 + timedelta(days=31)).is_empty)

    def test_boundary_available_at_equals_decision_is_usable(self):
        s, _ = load([item()], ingest=T0)
        self.assertFalse(context(s, ts=T0).is_empty)
        self.assertTrue(context(s, ts=T0 - timedelta(seconds=1)).is_empty)

    def test_revision_does_not_retroactively_replace_earlier_decision(self):
        s, _ = load([item(src="A", text="Original text."),
                     item(src="A2", text="Revised text.", revises_source_document_id="A",
                          ingested_at="2024-03-05T00:00:00+00:00")])  # fmt: skip
        early = context(s, ts=T0)  # revision not yet available
        self.assertEqual([d.text for d in early.documents], ["Original text."])
        late = context(s, ts=T0 + timedelta(days=6))
        self.assertEqual([d.text for d in late.documents], ["Revised text."])
        self.assertEqual(len(s.records()), 2)  # both preserved

    def test_duplicates_collapse_with_accounting(self):
        s, _ = load([item(src="A"), item(src="B")])  # same text => same content hash
        ctx = context(s)
        self.assertEqual(len(ctx.documents), 1)
        self.assertEqual(dict(ctx.excluded_counts).get("DUPLICATE"), 1)

    def test_bounded_and_lookback(self):
        items = [item(src=f"D{i}", text=f"text {i}", published=f"2024-02-{10 + i:02d}T10:00:00+00:00") for i in range(8)]
        s, _ = load(items)
        ctx = context(s, cfg=ContextConfig(max_documents=3, lookback_days=30))
        self.assertEqual(len(ctx.documents), 3)
        self.assertEqual(dict(ctx.excluded_counts)["OVER_MAX_DOCUMENTS"], 5)
        with self.assertRaises(ValueError):
            ContextConfig(max_documents=21)
        self.assertTrue(context(s, ts=T0 + timedelta(days=400), cfg=ContextConfig(lookback_days=7)).is_empty)

    def test_empty_context_is_valid_and_hash_stable(self):
        s = DisclosureStore()
        a, b = context(s), context(s)
        self.assertTrue(a.is_empty)
        self.assertEqual(a.context_hash, b.context_hash)

    def test_unmapped_and_rejected_never_enter_context(self):
        s, _ = load([item(isin=None, symbol="ZZZ"), item(src="Q", text="")])
        self.assertTrue(context(s).is_empty)

    def test_context_hash_changes_with_documents(self):
        s1, _ = load([item(text="one")])
        s2, _ = load([item(text="two")])
        self.assertNotEqual(context(s1).context_hash, context(s2).context_hash)


if __name__ == "__main__":
    unittest.main()
