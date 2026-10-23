"""Slice 7 closure — event identity & provenance, snapshot versioning, sensitive-data hygiene. SYNTHETIC."""

from __future__ import annotations

import json
import unittest
from datetime import timedelta
from decimal import Decimal

from domain.models.enums import FillType
from risk_execution.order_lifecycle import BrokerEvent, EventKind, EventStatus, OrderLifecycleManager
from shared.versioning.content_hash import hash_json_stable
from tests.unit._lifecycle_helpers import T0, Rig, fill_event, synthetic_fill


def rows(r: Rig, key: str):
    return r.mgr.record(key).event_log


class Provenance(unittest.TestCase):
    def test_identical_content_with_distinct_ids_stays_distinguishable(self):
        r = Rig()
        req, _, _ = r.submit()
        k = req.idempotency_key
        for fid, eid in (("fA", "E1"), ("fB", "E2")):
            r.mgr.apply_event(fill_event(k, synthetic_fill(k, 40, 50, fid=fid), eid))
        applied = [e for e in rows(r, k) if e["kind"] == "FILL" and e["status"] == "APPLIED"]
        self.assertEqual([(e["event_id"], e["identity"]) for e in applied], [("E1", "evt:E1"), ("E2", "evt:E2")])
        self.assertEqual(r.mgr.record(k).filled_qty, 80)

    def test_duplicate_delivery_has_one_financial_effect_and_a_traceable_log_row(self):
        r = Rig()
        req, _, _ = r.submit()
        k = req.idempotency_key
        ev = fill_event(k, synthetic_fill(k, 40, 50, fid="fA"), "E1")
        r.mgr.apply_event(ev)
        r.mgr.apply_event(ev)
        self.assertEqual(r.mgr.record(k).filled_qty, 40)
        dup = [e for e in rows(r, k) if e["status"] == "DUPLICATE_IGNORED"]
        self.assertEqual([e["identity"] for e in dup], ["evt:E1"])

    def test_event_time_and_recorded_time_are_distinct_and_unknown_stays_unknown(self):
        r = Rig()
        req, _, sub = r.submit()
        k = req.idempotency_key
        src_time = T0 - timedelta(hours=3)
        r.at(T0 + timedelta(days=1))
        r.mgr.apply_event(BrokerEvent(EventKind.FILL, None, k, fill=synthetic_fill(k, 40, 50, fid="fA"), event_time=src_time,
                                      source="sim", source_version="1"))
        r.mgr.apply_event(fill_event(k, synthetic_fill(k, 30, 50, fid="fB")))                 # no event_time: fill.timestamp
        r.mgr.apply_event(BrokerEvent(EventKind.ACKNOWLEDGED, sub.record.order.broker_order_id, k, event_id="late"))
        a, b, c = [e for e in rows(r, k) if e["event_id"] != "x"][-3:]
        self.assertEqual((a["event_time"], a["event_time_source"]), (src_time.isoformat(), "event"))
        self.assertNotEqual(a["event_time"], a["recorded_at"])
        self.assertEqual(a["recorded_at"], (T0 + timedelta(days=1)).isoformat())
        self.assertEqual(b["event_time_source"], "fill.timestamp")                           # labelled, not passed off as broker time
        self.assertEqual((c["event_time"], c["event_time_source"]), (None, "unknown"))       # nothing synthesized
        self.assertEqual((b["source"], b["source_version"]), (None, None))                  # missing source metadata is explicit

    def test_order_identifiers_and_correlation_link_submission_events_halts_and_recovery(self):
        r = Rig()
        r.broker.inject_fault("FAIL_AFTER_ACCEPT")
        req, _, sub = r.submit()
        k = req.idempotency_key
        corr = sub.record.correlation_id
        self.assertTrue(corr.startswith("corr_"))
        r.mgr.resolve_uncertain_submission(k, r.broker, r.session)
        for ev in r.fill_events(r.advance(1)):
            r.mgr.apply_event(ev)
        log = rows(r, k)
        self.assertTrue(log and all(e["correlation_id"] == corr for e in log))
        self.assertTrue(all(e["idempotency_key"] == k and e["order_id"] == sub.record.order.order_id for e in log))
        fills = [e for e in log if e["kind"] == "FILL"]
        self.assertEqual((fills[0]["source"], fills[0]["source_version"]), (r.session.adapter_id, r.session.adapter_version))
        self.assertEqual(r.mgr.active_halts()[0].correlation_id, corr)
        r2 = Rig()
        _, _, sub2 = r2.submit()
        self.assertNotEqual(sub2.record.correlation_id, corr)

    def test_event_supplied_correlation_id_is_echoed_separately_from_the_record_one(self):
        r = Rig()
        req, _, sub = r.submit()
        k = req.idempotency_key
        r.mgr.apply_event(BrokerEvent(EventKind.FILL, None, k, fill=synthetic_fill(k, 40, 50, fid="fA"), correlation_id="brk-77"))
        row = [e for e in rows(r, k) if e["kind"] == "FILL"][0]
        self.assertEqual((row["event_correlation_id"], row["correlation_id"]), ("brk-77", sub.record.correlation_id))

    def test_quarantine_and_halt_carry_provenance(self):
        r = Rig()
        req, _, _ = r.submit()
        k = req.idempotency_key
        res = r.mgr.apply_event(fill_event(k, synthetic_fill(k, 40, 50, FillType.FULL, fid="bad"), "E9"))
        self.assertIs(res.status, EventStatus.QUARANTINED)
        h = r.mgr.active_halts()[0]
        self.assertEqual((h.event_identity, h.order_key, h.recorded_at), ("evt:E9", k, T0.isoformat()))
        row = [e for e in rows(r, k) if e["status"] == "QUARANTINED"][0]
        self.assertEqual((row["halt_id"], row["identity"]), (h.halt_id, "evt:E9"))


class SnapshotProvenance(unittest.TestCase):
    def _loaded(self):
        r = Rig(max_fill_fraction_per_bar=Decimal("0.4"))
        req, _, _ = r.submit()
        k = req.idempotency_key
        for ev in r.fill_events(r.advance(1)):
            r.mgr.apply_event(ev)
        r.mgr.apply_event(fill_event(k, synthetic_fill(k, 90, 50, FillType.FULL, fid="over"), "E9"))   # quarantined + halt
        return r, req

    def test_restore_preserves_event_metadata_charges_halts_and_quarantine(self):
        r, req = self._loaded()
        k = req.idempotency_key
        snap = json.loads(json.dumps(r.mgr.snapshot()))
        m2 = OrderLifecycleManager.restore(snap, lambda: T0, {k: req})
        a, b = r.mgr.record(k), m2.record(k)
        self.assertEqual(b.event_log, a.event_log)
        self.assertEqual(b.correlation_id, a.correlation_id)
        self.assertEqual(list(b.quarantined), list(a.quarantined))
        self.assertEqual(m2.active_halts(), r.mgr.active_halts())
        fa, fb = next(iter(a.applied_fills.values())), next(iter(b.applied_fills.values()))
        self.assertEqual(fb, fa)                                   # incl. charge components + schedule version
        self.assertIsNotNone(fb.charges_components)
        self.assertIsNotNone(fb.schedule_version)

    def test_snapshot_is_v2_and_a_v1_snapshot_restores_with_provenance_unknown(self):
        r, req = self._loaded()
        k = req.idempotency_key
        snap = json.loads(json.dumps(r.mgr.snapshot()))
        self.assertEqual(snap["body"]["version"], "order-lifecycle-snapshot-v2")
        body = json.loads(json.dumps(snap["body"]))
        body["version"] = "order-lifecycle-snapshot-v1"
        for rec in body["records"]:
            rec.pop("correlation_id", None)
            for f in rec["applied_fills"]:
                for key in ("charges_components", "schedule_version", "order_id", "source"):
                    f.pop(key, None)
        for h in body["halts"]:
            for key in ("recorded_at", "correlation_id", "event_identity"):
                h.pop(key, None)
        v1 = {"body": body, "checksum": hash_json_stable(body)}
        m = OrderLifecycleManager.restore(v1, lambda: T0, {k: req})
        f = next(iter(m.record(k).applied_fills.values()))
        self.assertIsNone(f.charges_components)                    # unknown, not zero, not invented
        self.assertIsNone(f.schedule_version)
        self.assertIsNone(m.record(k).correlation_id)
        self.assertIsNone(m.active_halts()[0].recorded_at)

    def test_unknown_snapshot_version_is_refused_even_with_a_valid_checksum(self):
        r, req = self._loaded()
        body = json.loads(json.dumps(r.mgr.snapshot()["body"]))
        body["version"] = "order-lifecycle-snapshot-v99"
        with self.assertRaises(ValueError):
            OrderLifecycleManager.restore({"body": body, "checksum": hash_json_stable(body)}, lambda: T0,
                                          {req.idempotency_key: req})

    def test_inconsistent_snapshot_with_a_valid_checksum_is_refused(self):
        r, req = self._loaded()
        body = json.loads(json.dumps(r.mgr.snapshot()["body"]))
        body["records"][0]["applied_fills"] = []                    # state says fills happened; none recorded
        body["records"][0]["history"] = body["records"][0]["history"][:2] + [
            {"from": "SUBMITTED", "to": "ACKNOWLEDGED", "at": T0.isoformat(), "detail": ""},
            {"from": "ACKNOWLEDGED", "to": "FILLED", "at": T0.isoformat(), "detail": ""}]
        with self.assertRaises(ValueError):
            OrderLifecycleManager.restore({"body": body, "checksum": hash_json_stable(body)}, lambda: T0,
                                          {req.idempotency_key: req})

    def test_sensitive_or_oversized_broker_text_is_bounded_and_no_session_data_is_stored(self):
        r = Rig()
        req, _, sub = r.submit()
        k = req.idempotency_key
        secret = "SECRET-TOKEN-" + "x" * 600
        r.mgr.apply_event(BrokerEvent(EventKind.REJECTED, sub.record.order.broker_order_id, k, detail=secret))
        r.mgr.apply_event(BrokerEvent(EventKind.ACKNOWLEDGED, "SIM-unknown", detail=secret))   # unknown order -> halt text
        text = json.dumps(r.mgr.snapshot())
        self.assertNotIn("x" * 300, text)                           # free text is clipped
        for forbidden in ("password", "api_key", "access_token", "credentials"):
            self.assertNotIn(forbidden, text.lower())
        self.assertLessEqual(max(len(e["detail"]) for e in rows(r, k)), 200)


if __name__ == "__main__":
    unittest.main()
