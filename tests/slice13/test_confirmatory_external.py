import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from markets.lane import MarketLane
from prediction_ledger.models import Designation
from research.confirmatory.protocol import (
    ConfirmatoryProtocol, ConfirmatoryHoldoutRegistry, ProtocolDrift, ConfirmatoryProtocolError, ConfirmatoryProtocolRegistry, VariantLedger,
    confirmatory_verdict, holm_adjust,
)  # fmt: skip
from risk_execution.external_paper.contract import ApprovedIntent, ExternalState, client_order_id
from risk_execution.external_paper.guard import LiveEndpointRefused, PaperCredentials, PaperEndpointPolicy
from risk_execution.external_paper.mirror import ExternalLedger, ExternalMirror
from risk_execution.external_paper.mock import Fault, MockExternalPaperAdapter
from simulation.multi_market.comparison import compare_execution

US, IN = MarketLane.US_EQUITIES, MarketLane.IN_EQUITIES
D = lambda m, d: datetime(2026, m, d, tzinfo=UTC)  # noqa: E731


def proto(lane=US, designation=Designation.CONFIRMATORY, start=D(12, 1), cfg="cfg1", **kw):
    a = dict(lane=lane, protocol_id="p1", designation=designation, window_start=start,
             window_end=start + timedelta(days=60), universe_version="u1", horizons=("1d",), benchmark_id="B",
             primary_metrics=("hit_rate",), secondary_metrics=("rank_ic",), exclusion_criteria=("halted",),
             min_duration_days=30, min_coverage_ratio=0.8, min_scored_predictions=100,
             statistical_method="descriptive+holm", trial_accounting="variant_ledger",
             decision_criteria=("hit_rate CI excludes 0.5",), config_hash=cfg)  # fmt: skip
    a.update(kw)
    return ConfirmatoryProtocol(**a)


class Confirmatory(unittest.TestCase):
    def test_freeze_idempotent_and_drift_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            r = ConfirmatoryProtocolRegistry(d, US)
            h = r.freeze(proto(), D(11, 20))
            self.assertEqual(r.freeze(proto(), D(11, 21)), h)
            with self.assertRaises(ProtocolDrift):
                r.freeze(proto(horizons=("1d", "5d")), D(11, 21))
            r.check_no_drift(proto(), "cfg1")
            with self.assertRaises(ProtocolDrift):
                r.check_no_drift(proto(), "cfg-CHANGED")

    def test_must_freeze_before_window(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ConfirmatoryProtocolError):
                ConfirmatoryProtocolRegistry(d, US).freeze(proto(), D(12, 5))

    def test_lane_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ConfirmatoryProtocolError):
                ConfirmatoryProtocolRegistry(d, US).freeze(proto(lane=IN), D(11, 20))

    def test_exposed_holdout_blocks_confirmatory_in_that_market_only(self):
        with tempfile.TemporaryDirectory() as d:
            hu, hi = ConfirmatoryHoldoutRegistry(d, US), ConfirmatoryHoldoutRegistry(d, IN)
            for h in (hu, hi):
                h.declare("h1", D(11, 25), D(12, 30))
            hu.mark_exposed("h1", "informed a threshold change")
            with self.assertRaises(ConfirmatoryProtocolError):
                ConfirmatoryProtocolRegistry(d, US).freeze(proto(), D(11, 20), hu)
            ConfirmatoryProtocolRegistry(d, IN).freeze(proto(lane=IN), D(11, 20), hi)  # India unaffected

    def test_predeclaration_required(self):
        with self.assertRaises(ValueError):
            proto(primary_metrics=())
        with self.assertRaises(ValueError):
            proto(decision_criteria=())

    def test_variant_ledger_keeps_abandoned_and_tamper_evident(self):
        with tempfile.TemporaryDirectory() as d:
            v = VariantLedger(d, US)
            v.register("v1", "prompt", {"t": 1}, "TRIED")
            v.register("v2", "horizon", {"h": "5d"}, "ABANDONED", "worse on exposed holdout")
            self.assertEqual(VariantLedger(d, US).count(), 2)
            p = v.path
            p.write_text(p.read_text().replace("ABANDONED", "TRIED"))
            with self.assertRaises(ConfirmatoryProtocolError):
                VariantLedger(d, US)

    def test_holm_and_verdict(self):
        adj = holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03})
        self.assertAlmostEqual(adj["a"], 0.03)
        self.assertTrue(all(0 <= x <= 1 for x in adj.values()))
        v = confirmatory_verdict(proto(), elapsed_days=5, coverage_ratio=0.5, scored_n=3)
        self.assertEqual(v["verdict"], "INSUFFICIENT_SAMPLE")
        self.assertEqual(len(v["reasons"]), 3)
        self.assertEqual(confirmatory_verdict(proto(), elapsed_days=40, coverage_ratio=0.9, scored_n=200)["verdict"],
                         "EVALUABLE_AGAINST_PREDECLARED_CRITERIA")


def intent(i=1, lane=US, inst="AAA", qty=10, px=100.0):
    return ApprovedIntent(lane, inst, "BUY", qty, "MARKET", f"ord{i}", f"idem{i}", f"rd{i}", px)


class External(unittest.TestCase):
    def setUp(self):
        self.ad = MockExternalPaperAdapter(US)
        self.led = ExternalLedger("USD")
        self.m = ExternalMirror(self.ad, self.led)

    def test_mock_is_labelled_and_separate_ids(self):
        r = self.m.mirror(intent())
        self.assertEqual(r.mode, "MOCK")
        self.assertNotEqual(r.external_order_id, "ord1")
        self.assertEqual(r.state, ExternalState.FILLED)
        self.assertEqual(self.led.positions["AAA"], 10)
        self.assertLess(self.led.cash, 0)

    def test_intent_cannot_be_modified(self):
        i = intent()
        with self.assertRaises(Exception):
            i.quantity = 99  # frozen dataclass
        self.m.mirror(i)
        self.assertEqual(i.quantity, 10)

    def test_client_id_deterministic_and_platform_scoped(self):
        self.assertEqual(client_order_id(intent(), "P"), client_order_id(intent(), "P"))
        self.assertNotEqual(client_order_id(intent(), "P"), client_order_id(intent(), "Q"))

    def test_rejection_and_unsupported_do_not_raise(self):
        self.ad.fault = Fault.REJECT
        self.assertEqual(self.m.mirror(intent()).state, ExternalState.REJECTED)
        self.ad.fault, self.ad.supported = Fault.NONE, frozenset({"ZZZ"})
        self.assertEqual(self.m.mirror(intent(2)).state, ExternalState.UNSUPPORTED)

    def test_timeout_resolved_by_readback_no_duplicate(self):
        self.ad.fault = Fault.TIMEOUT_ORDER_CREATED
        r = self.m.mirror(intent())
        self.assertEqual(r.resolution, "READBACK_FOUND")
        self.assertEqual(self.ad.submit_calls, 1)  # never blindly resubmitted
        self.assertEqual(self.led.positions["AAA"], 10)

    def test_timeout_without_order_stays_unknown_no_auto_retry(self):
        self.ad.fault = Fault.TIMEOUT_NO_ORDER
        r = self.m.mirror(intent())
        self.assertEqual((r.state, r.resolution), (ExternalState.UNKNOWN, "READBACK_NOT_FOUND"))
        self.assertEqual(self.ad.submit_calls, 1)
        self.assertEqual(self.led.positions, {})

    def test_outage_is_contained(self):
        self.ad.fault = Fault.OUTAGE
        r = self.m.mirror(intent())
        self.assertEqual((r.state, r.resolution), (ExternalState.UNKNOWN, "UNRESOLVED"))

    def test_partial_fill(self):
        self.ad.fault = Fault.PARTIAL
        r = self.m.mirror(intent(qty=10))
        self.assertEqual((r.state, r.filled_quantity), (ExternalState.PARTIALLY_FILLED, 5))

    def test_paper_endpoint_policy_default_unconfigured_and_refuses_unlisted(self):
        p = PaperEndpointPolicy()
        self.assertFalse(p.configured)
        with self.assertRaises(LiveEndpointRefused):
            p.check("https://paper.example.com/v2")
        q = PaperEndpointPolicy(frozenset({"paper.example.com"}))
        self.assertEqual(q.check("https://paper.example.com/v2"), "https://paper.example.com/v2")
        with self.assertRaises(LiveEndpointRefused):
            q.check("https://live.example.com/v2")
        with self.assertRaises(LiveEndpointRefused):
            q.check("http://paper.example.com/v2")

    def test_credentials_never_printed(self):
        c = PaperCredentials("KEY123", "SECRET456")
        self.assertNotIn("SECRET456", repr(c) + str(c))
        self.assertNotIn("KEY123", repr(c))

    def test_comparison_preserves_disagreement_not_overwrite(self):
        self.ad.fill_price_offset_bps = 50
        rec = self.m.mirror(intent())
        orders = [{"order_id": "ord1", "instrument_id": "AAA", "side": "BUY", "quantity": 10, "final_state": "FILLED"}]
        fills = [{"order_id": "ord1", "quantity": 10, "fill_price": 100.0}]
        c = compare_execution(orders, fills, [rec])
        self.assertEqual(c["disagreements"], 1)
        row = c["rows"][0]
        self.assertEqual(row["internal"]["avg_fill_price"], 100.0)
        self.assertAlmostEqual(row["external"]["avg_fill_price"], 100.5)
        self.assertFalse(c["reconciled_by_overwrite"])

    def test_missing_external_counts_as_difference(self):
        orders = [{"order_id": "ord9", "instrument_id": "AAA", "side": "BUY", "quantity": 1, "final_state": "FILLED"}]
        c = compare_execution(orders, [], [])
        self.assertEqual((c["disagreements"], c["rows"][0]["external"]), (1, None))


if __name__ == "__main__":
    unittest.main()
