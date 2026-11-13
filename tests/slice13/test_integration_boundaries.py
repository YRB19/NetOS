import copy
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from data.live.observation import LiveObservation
from data.live.quality import QualityPolicy
from markets.lane import DataProvenance, MarketLane
from markets.readiness import (
    compute_lane_readiness, default_external_verification, default_source_verification,
)  # fmt: skip
from prediction_ledger.reader import LedgerReader
from research.harness.failures import RunStatus
from risk_execution.broker.adapters.simulated import SimulatedBrokerAdapter
from risk_execution.external_paper.mirror import ExternalMirror
from risk_execution.external_paper.mock import Fault, MockExternalPaperAdapter
from shared.arch_lint.rules import RULES
from simulation.multi_market.comparison import compare_execution
from simulation.multi_market.shadow import InternalPathBlocked, LaneShadowSession, new_external_ledger
from simulation.multi_market.sessions import Tier
from tests.slice13.helpers import CUR, T0, obs, policy, pred
from tests.unit._pipeline_helpers import ISINS, JournaledHarness, config, pipeline, tier2, universe, weekly_bars

IN, US = MarketLane.IN_EQUITIES, MarketLane.US_EQUITIES
ROOT = Path(__file__).resolve().parents[2]


def readiness(lane, integrated):
    return compute_lane_readiness(lane, default_source_verification(lane), default_external_verification(lane),
                                  internal_execution_integrated=integrated, cost_schedule_fully_verified=False)


def india_session(root):
    pol = QualityPolicy(IN, "INR", frozenset(ISINS), frozenset(ISINS), timedelta(seconds=60),
                        timedelta(days=30), 0.5, 1.0, timedelta(days=30))  # fmt: skip
    s = LaneShadowSession(Path(root), IN, pol, readiness(IN, True))
    items = [LiveObservation(IN, "SYNTH_IN", b.instrument_id, "XTST", b.timestamp, b.timestamp, b.timestamp,
                             b.open, b.high, b.low, b.close, b.volume, "INR", DataProvenance.SYNTHETIC)
             for b in weekly_bars()]  # fmt: skip
    s.ingest(items)
    return s


def runner(md):
    strat, b = tier2(0.3)
    return JournaledHarness().run(config(), strat, md, [universe()], pipeline(b))


ASOF = datetime(2030, 1, 1, tzinfo=UTC)


class IndiaInternalPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory()
        cls.s = india_session(cls._td.name)
        cls.res = cls.s.run_internal(Tier.TIER2, runner, ASOF)  # one pipeline run shared by the tests below

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def test_pipeline_runs_on_captured_observations_and_is_labelled_synthetic(self):
        md = self.s.market_data(ASOF)
        self.assertEqual(len(md), len(weekly_bars()))
        self.assertTrue(all(m.source.startswith("SYNTHETIC:") for m in md))
        self.assertIs(self.res.run.status, RunStatus.COMPLETED)
        self.assertGreater(len(self.res.orders), 0)
        self.assertEqual(self.s.reader().provenances(), frozenset({DataProvenance.SYNTHETIC}))

    def test_ai_prediction_recording_cannot_change_deterministic_orders(self):
        with tempfile.TemporaryDirectory() as d2:
            b = india_session(d2)
            for i in range(5):
                b.record_prediction(pred(pid=f"x{i}", lane=IN, inst=ISINS[0], created=T0), T0 + timedelta(seconds=1))
            rb = b.run_internal(Tier.TIER2, runner, ASOF)
            key = lambda r: [(o["instrument_id"], o["side"], o["quantity"], o["final_state"]) for o in r.orders]  # noqa: E731
            self.assertEqual(key(self.res), key(rb))
            self.assertEqual(len(LedgerReader(d2, IN).views()), 5)
            self.assertEqual(len(LedgerReader(self._td.name, IN).views()), 0)

    def test_external_mirror_failures_never_change_internal_result(self):
        res = self.res
        before = copy.deepcopy((res.orders, res.broker_fills, res.summary))
        for fault in (Fault.NONE, Fault.REJECT, Fault.OUTAGE, Fault.TIMEOUT_NO_ORDER, Fault.PARTIAL):
            ad = MockExternalPaperAdapter(IN, fault=fault)
            led = new_external_ledger(IN)
            recs = self.s.mirror(self.s.intents_from(res.orders), ExternalMirror(ad, led))
            self.assertEqual(len(recs), len(res.orders))
            self.assertEqual(led.currency, "INR")
        self.assertEqual(before, (res.orders, res.broker_fills, res.summary))

    def test_comparison_keeps_both_outcomes(self):
        res = self.res
        ad = MockExternalPaperAdapter(IN, fill_price_offset_bps=40)
        recs = self.s.mirror(self.s.intents_from(res.orders), ExternalMirror(ad, new_external_ledger(IN)))
        c = compare_execution(res.orders, res.broker_fills, recs)
        self.assertEqual(c["orders"], len(res.orders))
        self.assertGreater(c["disagreements"], 0)
        self.assertTrue(all(r["internal"] is not None and r["external"] is not None for r in c["rows"]))
        self.assertFalse(c["reconciled_by_overwrite"])


class UsInternalPathBlocked(unittest.TestCase):
    def test_us_internal_execution_blocked_and_broker_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            s = LaneShadowSession(Path(d), US, policy(), readiness(US, False))
            with mock.patch.object(SimulatedBrokerAdapter, "place_order", side_effect=AssertionError("called")):
                with self.assertRaises(InternalPathBlocked):
                    s.run_internal(Tier.TIER1, runner, T0)

    def test_us_session_ingest_and_prediction_work_independently_of_india(self):
        with tempfile.TemporaryDirectory() as d:
            s = LaneShadowSession(Path(d), US, policy(), readiness(US, False))
            self.assertEqual(s.ingest([obs()]), {"ACCEPTED": 1})
            self.assertEqual(s.readiness.overall.value, "BLOCKED")
            self.assertFalse((Path(d) / "IN_EQUITIES").exists())

    def test_session_rejects_wrong_lane_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                LaneShadowSession(Path(d), US, policy(IN, ("AAA",), ("AAA",)), readiness(US, False))


def imports_of(pkg_dir: str) -> str:
    out = []
    for p in (ROOT / pkg_dir).rglob("*.py"):
        out += [ln for ln in p.read_text().splitlines() if ln.startswith(("from ", "import "))]
    return "\n".join(out)


class BoundaryTests(unittest.TestCase):
    def test_ai_packages_cannot_reach_ledger_observations_external_or_markets(self):
        for pkg in ("intelligence", "model_providers"):
            txt = imports_of(pkg)
            for banned in ("prediction_ledger", "risk_execution.external_paper", "data.live", "from markets", "import markets"):
                self.assertNotIn(banned, txt, f"{pkg} imports {banned}")

    def test_strategies_and_risk_do_not_import_ai_ledger_or_eval(self):
        for pkg in ("risk_execution", "data/adapters", "intelligence/baseline"):
            txt = imports_of(pkg)
            for banned in ("prediction_ledger", "prediction_eval", "model_providers"):
                self.assertNotIn(banned, txt, f"{pkg} imports {banned}")

    def test_research_cannot_import_writers_or_external(self):
        txt = imports_of("research")
        for banned in ("data.live.store", "data.live.adapters", "prediction_ledger.ledger", "external_paper", "multi_market"):
            self.assertNotIn(banned, txt)

    def test_slice13_rules_registered(self):
        have = {(r.source_package, r.forbidden_prefix) for r in RULES}
        self.assertIn(("research", "observability.prediction_ledger.ledger"), have)
        self.assertIn(("intelligence", "observability.prediction_ledger"), have)
        self.assertIn(("markets", "data"), have)

    def test_no_live_endpoint_or_credentials_in_slice13_sources(self):
        for pkg in ("markets", "data/live", "risk_execution/external_paper", "simulation/multi_market",
                    "observability/prediction_ledger", "research/prediction_eval", "research/confirmatory"):  # fmt: skip
            for p in (ROOT / pkg).rglob("*.py"):
                t = p.read_text().lower()
                for bad in ("api.alpaca.markets", "paper-api.alpaca", "requests.", "urllib.request", "socket", "selenium",
                            "playwright", "investopedia", "tradingview"):  # fmt: skip
                    self.assertNotIn(bad, t, f"{p} mentions {bad}")


if __name__ == "__main__":
    unittest.main()
