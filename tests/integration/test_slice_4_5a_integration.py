"""Slice 4.5A integration tests: prove Slices 0-4 coexist as one repository.

Synthetic/fixture data only. No broker, network, LLM or research-harness code.
Unittest-style so the suite runs under both pytest and stdlib unittest.
"""

import ast
import unittest
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from data.adapters.nse_bhavcopy_csv import load_bhavcopy_csv
from data.features.context_builder import build_feature_snapshots
from data.features.universe import make_permitted_universe
from data.normalization.pipeline import normalize_bhavcopy_batch
from domain.models import CandidateTrade, FeatureSnapshot
from domain.models.enums import Action
from domain.models.serialization import to_serializable
from intelligence.baseline.tier1_equal_weight import (
    STRATEGY_VERSION_ID,
    Tier1EqualWeightBuyHold,
)
from shared.costs import CostInputs, CostModel, TradeType, TransactionSide

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/historical_data/valid_sample.csv"  # SYNTHETIC fixture
SCHEDULE = "india-equity-v1-unverified"


def _pipeline(raw=None):
    # ingestion_time is stamped once per adapter READ (provenance, by design), so
    # determinism is asserted for a fixed raw read, not across separate reads.
    raw = raw if raw is not None else load_bhavcopy_csv(FIXTURE)
    result = normalize_bhavcopy_batch(raw.observations, raw_source_hash=raw.raw_source_hash)
    records = sorted(result.accepted, key=lambda r: r.identity_key)
    as_of = max(r.timestamp for r in records)
    ids = sorted({r.instrument_id for r in records})
    return result, records, as_of, ids


class TestDataToFeature(unittest.TestCase):
    def test_canonical_market_data_yields_valid_snapshot(self):
        _, records, as_of, ids = _pipeline()
        universe = make_permitted_universe(ids, as_of)
        snaps = build_feature_snapshots(records, universe, as_of)
        self.assertEqual(len(snaps), len(ids))
        for s in snaps:
            self.assertIsInstance(s, FeatureSnapshot)
            self.assertTrue(s.is_complete)
            self.assertTrue(s.is_permitted)
            self.assertEqual(s.universe_version, universe.version)


class TestFeatureToTier1(unittest.TestCase):
    def setUp(self):
        _, self.records, self.as_of, self.ids = _pipeline()
        self.strategy = Tier1EqualWeightBuyHold()

    def _cycle(self, universe, previous, extra_ids=()):
        snaps = build_feature_snapshots(
            self.records, universe, self.as_of,
            instrument_ids=set(universe.instrument_ids) | set(extra_ids),
        )
        return snaps, self.strategy.generate_candidate_trades(snaps, universe, previous)

    def test_initial_universe_buys_all_equal_weight(self):
        u = make_permitted_universe(self.ids, self.as_of)
        snaps, cands = self._cycle(u, None)
        self.assertEqual(len(cands), len(self.ids))
        for c in cands:
            self.assertEqual(c.action, Action.BUY)
            self.assertAlmostEqual(c.size_hint, 1 / len(self.ids))

    def test_unchanged_universe_holds(self):
        u = make_permitted_universe(self.ids, self.as_of)
        _, cands = self._cycle(u, u)
        self.assertTrue(all(c.action == Action.HOLD for c in cands))

    def test_added_instrument_buys_only_new(self):
        prev = make_permitted_universe(self.ids[:1], self.as_of)
        cur = make_permitted_universe(self.ids, self.as_of)
        _, cands = self._cycle(cur, prev)
        actions = {c.instrument_id: c.action for c in cands}
        self.assertEqual(actions[self.ids[0]], Action.HOLD)
        for i in self.ids[1:]:
            self.assertEqual(actions[i], Action.BUY)

    def test_removed_instrument_sells(self):
        prev = make_permitted_universe(self.ids, self.as_of)
        cur = make_permitted_universe(self.ids[:1], self.as_of)
        _, cands = self._cycle(cur, prev, extra_ids=self.ids)
        actions = {c.instrument_id: c.action for c in cands}
        self.assertEqual(actions[self.ids[0]], Action.HOLD)
        for i in self.ids[1:]:
            self.assertEqual(actions[i], Action.SELL)

    def test_candidate_provenance(self):
        u = make_permitted_universe(self.ids, self.as_of)
        snaps, cands = self._cycle(u, None)
        by_inst = {s.instrument_id: s for s in snaps}
        for c in cands:
            self.assertIsInstance(c, CandidateTrade)
            self.assertEqual(c.input_snapshot_id, by_inst[c.instrument_id].snapshot_id)
            self.assertEqual(c.strategy_version_id, STRATEGY_VERSION_ID)
            self.assertIsNone(c.model_version_id)

    def test_candidate_carries_no_executable_quantity(self):
        names = {f.name for f in fields(CandidateTrade)}
        self.assertFalse(names & {"quantity", "qty", "order_type", "broker", "credentials"})


class TestCostModelIndependence(unittest.TestCase):
    FORBIDDEN = ("risk_execution", "intelligence", "research", "governance", "observability",
                 "data", "socket", "http", "urllib", "requests", "ssl", "asyncio")

    def test_cost_model_source_imports_are_pure(self):
        for path in (ROOT / "shared/costs").glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mods = [node.module]
                for m in mods:
                    self.assertNotIn(m.split(".")[0], self.FORBIDDEN, f"{path.name}: {m}")

    def test_estimate_works_standalone_and_is_decimal(self):
        inputs = CostInputs(
            TransactionSide.BUY, TradeType.DELIVERY, 10, Decimal("100.00"), SCHEDULE
        )
        est = CostModel().estimate(inputs)
        self.assertIsInstance(est.total_cost, Decimal)
        self.assertEqual(est.total_cost, est.component_total())

    def test_schedule_remains_unverified(self):
        from shared.costs import default_registry

        sched = default_registry().get(SCHEDULE)
        self.assertFalse(sched.verified)
        self.assertTrue(sched.version_id.endswith("-unverified"))


class TestFullChainAndDeterminism(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = load_bhavcopy_csv(FIXTURE)

    def test_separate_reads_differ_only_by_ingestion_provenance(self):
        a = _pipeline()[1]
        b = _pipeline()[1]
        strip = lambda rs: [(r.identity_key, r.open, r.high, r.low, r.close, r.volume) for r in rs]  # noqa: E731
        self.assertEqual(strip(a), strip(b))

    def _run(self):
        result, records, as_of, ids = _pipeline(self.raw)
        u = make_permitted_universe(ids, as_of)
        snaps = build_feature_snapshots(records, u, as_of)
        cands = Tier1EqualWeightBuyHold().generate_candidate_trades(snaps, u, None)
        est = CostModel().estimate(
            CostInputs(TransactionSide.SELL, TradeType.INTRADAY, 5, Decimal("250.50"), SCHEDULE)
        )
        return result, records, snaps, cands, est

    def test_chain_is_deterministic_across_runs(self):
        a, b = self._run(), self._run()
        self.assertEqual(a[0].data_snapshot_version, b[0].data_snapshot_version)
        self.assertEqual(a[1], b[1])
        self.assertEqual(a[2], b[2])
        self.assertEqual(a[3], b[3])
        self.assertEqual(a[4], b[4])
        self.assertEqual(
            [to_serializable(c) for c in a[3]], [to_serializable(c) for c in b[3]]
        )

    def test_timestamps_are_utc(self):
        _, records, snaps, cands, _ = self._run()
        for obj in (*records, *cands):
            ts = getattr(obj, "timestamp")
            self.assertEqual(ts.utcoffset(), datetime.now(UTC).utcoffset())
        for s in snaps:
            self.assertEqual(s.decision_timestamp.utcoffset(), datetime.now(UTC).utcoffset())


class TestNoCompetingCoreDefinitions(unittest.TestCase):
    # shared.costs.CostEstimate (pure Decimal calculator result) vs
    # domain.models.cost.CostEstimate (Stage 3 §2 audit envelope) is a documented,
    # deliberate split — see docs/repository-integration.md.
    ALLOWED = {"CostEstimate"}

    def test_no_duplicate_class_names_across_packages(self):
        seen: dict[str, list[str]] = {}
        for pkg in ("domain", "data", "intelligence", "shared", "risk_execution", "research",
                    "governance", "observability"):
            for path in (ROOT / pkg).rglob("*.py"):
                for node in ast.parse(path.read_text()).body:
                    if isinstance(node, ast.ClassDef):
                        seen.setdefault(node.name, []).append(str(path.relative_to(ROOT)))
        dups = {k: v for k, v in seen.items() if len(v) > 1 and k not in self.ALLOWED}
        self.assertEqual(dups, {})


if __name__ == "__main__":
    unittest.main()
