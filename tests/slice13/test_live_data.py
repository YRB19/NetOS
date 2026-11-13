import json
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from data.live.adapters import ReplayAdapter, SourceNotVerified, UnverifiedSourceAdapter
from data.live.observation import FeedEvent, FeedEventKind
from data.live.quality import QualityEngine, QualityVerdict, SessionHealth
from data.live.reader import ObservationReader, StoreError, verify_store
from data.live.store import ObservationStore
from markets.lane import DataProvenance, MarketLane
from tests.slice13.helpers import T0, obs, policy

V = QualityVerdict


class Quality(unittest.TestCase):
    def setUp(self):
        self.q = QualityEngine(policy())

    def test_accepts_clean(self):
        self.assertEqual(self.q.assess(obs()).verdict, V.ACCEPTED)

    def test_duplicate(self):
        self.q.assess(obs())
        self.assertEqual(self.q.assess(obs()).verdict, V.DUPLICATE)

    def test_correction_is_new_revision_not_overwrite(self):
        self.q.assess(obs())
        self.assertEqual(self.q.assess(obs(close=101, revision=1)).verdict, V.CORRECTION_ACCEPTED)

    def test_out_of_order_flagged(self):
        self.q.assess(obs(t=T0 + timedelta(minutes=5)))
        self.assertEqual(self.q.assess(obs(t=T0)).verdict, V.OUT_OF_ORDER)

    def test_late(self):
        self.assertEqual(self.q.assess(obs(lag=600)).verdict, V.LATE)
        self.assertFalse(self.q.assess(obs(t=T0 + timedelta(minutes=1), lag=600)).usable)

    def test_invalid_prices_never_zero_filled(self):
        for bad in (0.0, -5.0, float("nan"), float("inf")):
            self.assertEqual(self.q.assess(obs(close=bad)).verdict, V.INVALID_PRICE, bad)

    def test_invalid_timestamp(self):
        o = obs()
        self.assertEqual(self.q.assess(replace(o, available_time=o.event_time - timedelta(seconds=1))).verdict,
                         V.INVALID_TIMESTAMP)

    def test_unsupported_wrong_lane_currency(self):
        self.assertEqual(self.q.assess(obs(inst="ZZZ")).verdict, V.UNSUPPORTED_INSTRUMENT)
        self.assertEqual(self.q.assess(obs(lane=MarketLane.IN_EQUITIES, inst="AAA")).verdict, V.WRONG_LANE)
        self.assertEqual(self.q.assess(replace(obs(), currency="INR")).verdict, V.CURRENCY_MISMATCH)

    def test_health_blocks_on_missing_required_and_never_fills(self):
        now = T0 + timedelta(minutes=30)
        h, d = self.q.health(now)
        self.assertEqual(h, SessionHealth.BLOCKED)
        self.assertEqual(d["missing_or_stale"], ["AAA", "BBB"])

    def test_health_degraded_then_ok(self):
        self.q.assess(obs(inst="AAA"))
        self.assertEqual(self.q.health(T0 + timedelta(seconds=10))[0], SessionHealth.DEGRADED)
        self.q.assess(obs(inst="BBB"))
        self.assertEqual(self.q.health(T0 + timedelta(seconds=10))[0], SessionHealth.OK)

    def test_long_disconnect_blocks(self):
        self.q.assess(obs(inst="AAA"))
        self.q.assess(obs(inst="BBB"))
        self.q.record_feed_event(FeedEvent(MarketLane.US_EQUITIES, "P", FeedEventKind.DISCONNECT, T0))
        self.assertEqual(self.q.health(T0 + timedelta(seconds=200))[0], SessionHealth.BLOCKED)


class Store(unittest.TestCase):
    def test_roundtrip_keeps_rejected_with_verdict(self):
        with tempfile.TemporaryDirectory() as d:
            s, q = ObservationStore(d, MarketLane.US_EQUITIES), QualityEngine(policy())
            for o in (obs(), obs(close=-1, t=T0 + timedelta(minutes=1))):
                s.append(o, q.assess(o))
            r = ObservationReader(d, MarketLane.US_EQUITIES)
            self.assertEqual(len(r.all()), 2)
            self.assertEqual(r.verdict_counts(), {"ACCEPTED": 1, "INVALID_PRICE": 1})
            self.assertEqual(len(r.usable_as_of(T0 + timedelta(hours=1))), 1)

    def test_tamper_detected(self):
        with tempfile.TemporaryDirectory() as d:
            s, q = ObservationStore(d, MarketLane.US_EQUITIES), QualityEngine(policy())
            for i in range(3):
                o = obs(t=T0 + timedelta(minutes=i))
                s.append(o, q.assess(o))
            p = s.path
            lines = p.read_text().splitlines()
            rec = json.loads(lines[1])
            rec["body"]["obs"]["close"] = 999.0
            lines[1] = json.dumps(rec, sort_keys=True)
            p.write_text("\n".join(lines) + "\n")
            self.assertFalse(verify_store(p).ok)
            with self.assertRaises(StoreError):
                ObservationReader(d, MarketLane.US_EQUITIES)
            with self.assertRaises(StoreError):
                ObservationStore(d, MarketLane.US_EQUITIES)

    def test_deletion_detected(self):
        with tempfile.TemporaryDirectory() as d:
            s, q = ObservationStore(d, MarketLane.US_EQUITIES), QualityEngine(policy())
            for i in range(3):
                o = obs(t=T0 + timedelta(minutes=i))
                s.append(o, q.assess(o))
            lines = s.path.read_text().splitlines()
            s.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
            self.assertFalse(verify_store(s.path).ok)

    def test_point_in_time_hides_future_and_latest_revision_wins(self):
        with tempfile.TemporaryDirectory() as d:
            s, q = ObservationStore(d, MarketLane.US_EQUITIES), QualityEngine(policy())
            for o in (obs(close=100), obs(close=101, revision=1, lag=30), obs(t=T0 + timedelta(minutes=9), close=5)):
                s.append(o, q.assess(o))
            r = ObservationReader(d, MarketLane.US_EQUITIES)
            self.assertEqual([x.close for x in r.usable_as_of(T0 + timedelta(seconds=10))], [100])
            self.assertEqual([x.close for x in r.usable_as_of(T0 + timedelta(seconds=40))], [101])

    def test_store_lane_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            s = ObservationStore(d, MarketLane.US_EQUITIES)
            with self.assertRaises(StoreError):
                s.append(obs(lane=MarketLane.IN_EQUITIES), QualityEngine(policy()).assess(obs()))
            self.assertNotEqual(ObservationStore(d, MarketLane.IN_EQUITIES).path.parent, s.path.parent)

    def test_reader_has_no_mutation_api(self):
        self.assertFalse(any(m in dir(ObservationReader) for m in ("append", "write", "delete", "update")))


class Adapters(unittest.TestCase):
    def test_unverified_adapter_fails_closed(self):
        with self.assertRaises(SourceNotVerified):
            UnverifiedSourceAdapter(MarketLane.IN_EQUITIES, "X").poll()

    def test_replay_cannot_claim_live(self):
        with self.assertRaises(ValueError):
            ReplayAdapter(MarketLane.US_EQUITIES, "R", [], DataProvenance.LIVE)

    def test_replay_relabels_provenance(self):
        a = ReplayAdapter(MarketLane.US_EQUITIES, "R", [obs(prov=DataProvenance.LIVE)], DataProvenance.REPLAY)
        self.assertEqual(a.poll()[0].provenance, DataProvenance.REPLAY)
        self.assertEqual(a.poll(), [])


if __name__ == "__main__":
    unittest.main()
