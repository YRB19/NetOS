"""Slice 9 tests — SYNTHETIC fixtures only. Nothing here is market evidence.

Expected values are hand-calculated in comments/literals, not produced by the code under test.
"""

import dataclasses
import json
import math
import random
import statistics
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from data.features.universe import make_permitted_universe
from domain.models.market_data import MarketData
from intelligence.baseline.tier1_equal_weight import Tier1EqualWeightBuyHold
from research.contamination.point_in_time import (
    AvailabilityBasis as AB,
    AvailabilityLedger,
    PitStatus,
    UnknownAvailabilityPolicy,
    VersionedObservation as VO,
)
from research.experiments.store import write_run
from research.harness.failures import ResearchRunFailure
from research.harness.runner import ResearchHarness
from research.protocol.protocol import (
    AcceptanceCriterion, Comparator, ExperimentMode, ExperimentProtocol, HoldoutReusePolicy,
)  # fmt: skip
from research.protocol.registry import (
    ProtocolConflict, ProtocolError, ProtocolNotRegistered, ProtocolRegistry,
)  # fmt: skip
from research.splits.plan import (
    WalkForwardMode, WalkForwardPlan, purge_boundary, run_walk_forward, validate_split_with_horizon,
)  # fmt: skip
from research.stats.pbo import PboStatus, compute_pbo
from research.stats.regimes import (
    RegimeDefinition, RegimeDimension, classify, equal_weight_index, segment_equity,
)  # fmt: skip
from research.trials.holdout import HoldoutRegistry, HoldoutReuseError, HoldoutStatus, holdout_id_for
from research.trials.ledger import TrialLedger, TrialLedgerError, TrialOutcome
from research.validity.assumptions import AssumptionStatus, ExecutionAssumptions
from research.validity.evaluation import (
    ReproducibilityFailure, assess_criteria, build_report, reproduce_run, write_report,
)  # fmt: skip
from research.validity.metrics import compute_extended_metrics, final_marks_from_market_data
from research.validity.quality import DatasetProvenance, assess_quality
from shared.costs import CostModel
from tests.unit._research_helpers import BASE, ISINS, V1, V2, ThresholdStrategy, bar, config, day, make_bars, universe

CLOCK0 = datetime(2026, 1, 1, tzinfo=UTC)


def proto(**over) -> ExperimentProtocol:
    cfg = config()
    args = dict(
        protocol_id="syn-proto", version=1, mode=ExperimentMode.CONFIRMATORY,
        hypothesis="SYNTHETIC plumbing", research_question="SYNTHETIC q", universe_policy="fixed",
        universe_versions=("u1",), dataset_id="synthetic", dataset_version="synthetic-v1",
        data_start=day(-30), data_end=day(9), sampling_frequency="DAILY",
        availability_requirement="NOT_REQUIRED_SYNTHETIC", split=cfg.split,
        strategy_version_ids=("s1",), benchmark_version_ids=("b1",), cost_schedule_version=V2,
        entry_exit_cost_assumption="booked per fill; terminal estimated separately",
        execution_assumptions={"fill": "NEXT_BAR_OPEN"}, unverified_elements=("brokerage",),
        primary_metrics=("net_return",), secondary_metrics=("max_drawdown",),
        metric_definitions_version="metrics-v2-slice9",
        acceptance_criteria=(AcceptanceCriterion("max_drawdown", Comparator.GT, "0.5", "adverse if > 50%", adverse=True),),
        negative_result_definition="criteria not met or adverse", holdout_id="h1",
        holdout_reuse_policy=HoldoutReusePolicy.REJECT, strategy_configured_through=day(-31),
        information_horizon_days=0,
    )  # fmt: skip
    args.update(over)
    return ExperimentProtocol(**args)


class ProtocolTests(unittest.TestCase):
    def test_register_freeze_and_version(self):
        with tempfile.TemporaryDirectory() as d:
            reg = ProtocolRegistry(d, clock=lambda: CLOCK0)
            p1 = proto()
            r1 = reg.register(p1)
            self.assertEqual(reg.register(p1).protocol_hash, r1.protocol_hash)  # idempotent
            with self.assertRaises(ProtocolConflict):
                reg.register(proto(hypothesis="changed after registration"))  # same version, new content
            p2 = proto(version=2, hypothesis="changed", supersedes_protocol_hash=r1.protocol_hash)
            reg.register(p2)
            self.assertEqual(reg.get("syn-proto", 1).protocol_hash, r1.protocol_hash)  # original intact
            with self.assertRaises(ProtocolError):
                reg.register(proto(version=3, supersedes_protocol_hash="wrong"))

    def test_registered_before_evaluation(self):
        with tempfile.TemporaryDirectory() as d:
            reg = ProtocolRegistry(d, clock=lambda: CLOCK0)
            p = proto()
            with self.assertRaises(ProtocolNotRegistered):
                reg.verify_registered_before(p, CLOCK0 + timedelta(days=1))
            reg.register(p)
            reg.verify_registered_before(p, CLOCK0 + timedelta(days=1))
            with self.assertRaises(ProtocolError):  # evaluation began before registration
                reg.verify_registered_before(p, CLOCK0 - timedelta(days=1))

    def test_invalid_protocol_rejected_and_no_invented_thresholds(self):
        with tempfile.TemporaryDirectory() as d:
            reg = ProtocolRegistry(d, clock=lambda: CLOCK0)
            with self.assertRaises(ProtocolError):
                reg.register(proto(acceptance_criteria=()))  # confirmatory needs structured criteria
            with self.assertRaises(ProtocolError):
                reg.register(proto(information_horizon_days=None))
            bad = proto(acceptance_criteria=(AcceptanceCriterion("net_return", Comparator.GT, "abc", "x"),))
            self.assertTrue(any("not numeric" in e for e in bad.validate()))

    def test_criteria_assessment_structured_only(self):
        p = proto(acceptance_criteria=(AcceptanceCriterion("net_return", Comparator.GT, "0.01", "r"),
                                       AcceptanceCriterion("max_drawdown", Comparator.GT, "0.2", "adv", adverse=True)))  # fmt: skip
        ok = {"net_return": {"value": "0.05", "status": "OK"}, "max_drawdown": {"value": "0.1", "status": "OK"}}
        self.assertEqual(assess_criteria(p, ok)["overall"], "CRITERIA_MET")
        adv = dict(ok, max_drawdown={"value": "0.3", "status": "OK"})
        self.assertEqual(assess_criteria(p, adv)["overall"], "ADVERSE")
        missing = {"net_return": {"value": None, "status": "UNAVAILABLE"}, "max_drawdown": {"value": "0.1", "status": "OK"}}
        a = assess_criteria(p, missing)
        self.assertEqual(a["overall"], "INCONCLUSIVE")
        self.assertFalse(a["free_text_assessed"])


class TrialAndHoldoutTests(unittest.TestCase):
    def test_every_trial_retained_and_chain_verifies(self):
        with tempfile.TemporaryDirectory() as d:
            led = TrialLedger(d, clock=lambda: CLOCK0)
            for i, o in enumerate((TrialOutcome.COMPLETED, TrialOutcome.FAILED, TrialOutcome.COMPLETED_WORSE_THAN_BASELINE,
                                   TrialOutcome.INVALID_CONFIGURATION, TrialOutcome.UNSUPPORTED)):  # fmt: skip
                led.record(protocol_id="p", protocol_hash="h", strategy_id=f"s{i}", mode="EXPLORATORY", outcome=o,
                           reason=None if "COMPLETED" in o.value else "controlled reason")  # fmt: skip
            self.assertEqual(led.count(protocol_id="p"), 5)
            self.assertEqual(len(led.select(outcome=TrialOutcome.FAILED)), 1)
            self.assertEqual(led.verify(), [])
            with self.assertRaises(TrialLedgerError):  # failures need a controlled reason
                led.record(protocol_id="p", protocol_hash=None, strategy_id="x", mode="EXPLORATORY", outcome=TrialOutcome.FAILED)

    def test_tampering_detected(self):
        with tempfile.TemporaryDirectory() as d:
            led = TrialLedger(d, clock=lambda: CLOCK0)
            for i in range(3):
                led.record(protocol_id="p", protocol_hash="h", strategy_id=f"s{i}", mode="EXPLORATORY", outcome=TrialOutcome.COMPLETED)
            path = Path(d) / "trials" / "ledger.jsonl"
            lines = path.read_text().splitlines()
            path.write_text("\n".join([lines[0], lines[2]]) + "\n")  # delete the middle trial
            self.assertTrue(led.verify())

    def test_holdout_reuse_cannot_be_called_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            hr = HoldoutRegistry(d, clock=lambda: CLOCK0)
            hid = holdout_id_for(dataset_id="ds", dataset_hash="x", universe_versions=("u1",), test_start=day(0), test_end=day(9))
            self.assertIs(hr.status(hid), HoldoutStatus.UNTOUCHED)
            self.assertIs(hr.expose(holdout_id=hid, protocol_id="a", protocol_hash="1", run_id="r1", mode="CONFIRMATORY",
                                    policy=HoldoutReusePolicy.REJECT), HoldoutStatus.UNTOUCHED)  # fmt: skip
            with self.assertRaises(HoldoutReuseError):
                hr.expose(holdout_id=hid, protocol_id="a", protocol_hash="1", run_id="r2", mode="CONFIRMATORY", policy=HoldoutReusePolicy.REJECT)
            st = hr.expose(holdout_id=hid, protocol_id="b", protocol_hash="2", run_id="r3", mode="CONFIRMATORY",
                           policy=HoldoutReusePolicy.DOWNGRADE_TO_NON_CONFIRMATORY)  # fmt: skip
            self.assertIs(st, HoldoutStatus.REUSED_NON_CONFIRMATORY)
            self.assertEqual(len(hr.exposures(hid)), 2)  # history kept; the rejected attempt was not recorded as use
            # a NEW protocol does not change the holdout identity, so exposure is still visible
            same = holdout_id_for(dataset_id="ds", dataset_hash="x", universe_versions=("u1",), test_start=day(0), test_end=day(9))
            self.assertIs(hr.status(same), HoldoutStatus.REUSED_NON_CONFIRMATORY)

    def test_exploratory_exposure_spoils_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            hr = HoldoutRegistry(d, clock=lambda: CLOCK0)
            hr.expose(holdout_id="h", protocol_id="a", protocol_hash=None, run_id=None, mode="EXPLORATORY",
                      policy=HoldoutReusePolicy.DOWNGRADE_TO_NON_CONFIRMATORY)  # fmt: skip
            self.assertIs(hr.status("h"), HoldoutStatus.REUSED_NON_CONFIRMATORY)


def _ledger(data, **kw):
    return AvailabilityLedger([VO(m, 0, m.timestamp, AB.SYNTHETIC_DECLARED) for m in data], **kw)


class PointInTimeTests(unittest.TestCase):
    def test_event_earlier_but_available_later_is_not_visible(self):
        late = bar(ISINS[0], 3, 103.0)
        led = AvailabilityLedger([VO(late, 0, day(6), AB.SOURCE_PUBLISHED)] + [VO(bar(ISINS[0], 1, 101.0), 0, day(1), AB.SOURCE_PUBLISHED)])
        self.assertEqual([m.timestamp for m in led.resolve(day(5))], [day(1)])
        self.assertEqual([m.timestamp for m in led.resolve(day(6))], [day(1), day(3)])

    def test_revision_cannot_leak_into_earlier_decision(self):
        r0, r1 = bar(ISINS[0], 2, 102.0), bar(ISINS[0], 2, 999.0)
        led = AvailabilityLedger([VO(r0, 0, day(2), AB.SOURCE_PUBLISHED), VO(r1, 1, day(7), AB.SOURCE_PUBLISHED)])
        self.assertEqual(led.resolve_one(ISINS[0], day(2), day(5)).close, 102.0)
        self.assertEqual(led.resolve_one(ISINS[0], day(2), day(7)).close, 999.0)
        self.assertEqual(led.revised_keys(), [(ISINS[0], day(2))])

    def test_future_event_time_never_visible(self):
        led = _ledger(make_bars())
        self.assertTrue(all(m.timestamp <= day(4) for m in led.resolve(day(4))))
        self.assertIsNone(led.resolve_one(ISINS[0], day(8), day(4)))

    def test_unknown_availability_is_unverifiable_not_clean(self):
        unk = VO(bar(ISINS[0], 1, 101.0))  # legacy: basis UNKNOWN, no availability
        led = AvailabilityLedger([unk, VO(bar(ISINS[0], 2, 102.0), 0, day(2), AB.SYNTHETIC_DECLARED)])
        self.assertEqual(led.status(), PitStatus.UNVERIFIABLE)
        rep = led.report()
        self.assertFalse(rep["clean_point_in_time_claim"])
        self.assertEqual(len(rep["unverifiable_records"]), 1)
        self.assertEqual([m.timestamp for m in led.resolve(day(5))], [day(2)])  # excluded, never substituted
        with self.assertRaises(ResearchRunFailure):
            AvailabilityLedger([unk], unknown_policy=UnknownAvailabilityPolicy.FAIL)

    def test_basis_requires_evidence(self):
        with self.assertRaises(ValueError):
            VO(bar(ISINS[0], 1, 10.0), 0, day(1), AB.UNKNOWN)
        with self.assertRaises(ValueError):
            VO(bar(ISINS[0], 1, 10.0), 0, None, AB.SOURCE_PUBLISHED)

    def test_ingestion_time_is_not_silently_availability(self):
        m = bar(ISINS[0], 1, 10.0)  # ingestion_time = BASE, a later/other time than the bar
        self.assertEqual(AvailabilityLedger([VO(m)]).status(), PitStatus.UNVERIFIABLE)

    def test_fingerprint_changes_with_revision(self):
        a = AvailabilityLedger([VO(bar(ISINS[0], 1, 10.0), 0, day(1), AB.SYNTHETIC_DECLARED)])
        b = AvailabilityLedger([VO(bar(ISINS[0], 1, 10.0), 0, day(1), AB.SYNTHETIC_DECLARED), VO(bar(ISINS[0], 1, 20.0), 1, day(3), AB.SYNTHETIC_DECLARED)])  # fmt: skip
        self.assertNotEqual(a.fingerprint(), b.fingerprint())

    def test_harness_decisions_unchanged_by_late_poisoned_revision(self):
        data = make_bars()
        clean = ResearchHarness(availability=_ledger(data)).run(config(), ThresholdStrategy(), data, [universe()])
        poisoned_bar = bar(ISINS[0], 5, 9999.0)
        obs = [VO(m, 0, m.timestamp, AB.SYNTHETIC_DECLARED) for m in data] + [VO(poisoned_bar, 1, day(8), AB.SYNTHETIC_DECLARED)]
        dirty = ResearchHarness(availability=AvailabilityLedger(obs)).run(config(), ThresholdStrategy(), data, [universe()])
        self.assertTrue(clean.succeeded, clean.failure)
        self.assertTrue(dirty.succeeded, dirty.failure)
        early = lambda r: [(d["decision_timestamp"], d["instrument_id"], d["action"]) for d in r.decisions if d["decision_timestamp"] < day(8)]  # noqa: E731
        self.assertEqual(early(clean), early(dirty))
        self.assertEqual(clean.contamination_report["point_in_time"]["status"], "SYNTHETIC")
        self.assertNotEqual(clean.data_snapshot_version, dirty.data_snapshot_version)

    def test_harness_without_availability_discloses_unverifiable(self):
        r = ResearchHarness().run(config(), Tier1EqualWeightBuyHold(), make_bars(), [universe()])
        self.assertEqual(r.contamination_report["point_in_time"]["status"], "UNVERIFIABLE")
        self.assertFalse(r.contamination_report["point_in_time"]["clean_point_in_time_claim"])


class SplitTests(unittest.TestCase):
    def test_purge_boundary_hand_calculated(self):
        # train_end day 10, test_start day 20, horizon 5, embargo 2 -> samples valid iff t < day 13
        p = purge_boundary(day(10), day(20), 5, 2)
        self.assertEqual(p.status, "APPLIED")
        self.assertEqual(p.train_cutoff_exclusive, day(13))
        self.assertIsNone(p.excluded_interval)  # cutoff day 13 is already after train_end day 10: nothing purged
        # horizon so small nothing is purged beyond declared train end
        q = purge_boundary(day(10), day(20), 1, 0)
        self.assertIsNone(q.excluded_interval)

    def test_purge_when_horizon_overlaps_boundary(self):
        p = purge_boundary(day(10), day(12), 5, 0)  # cutoff day 7 < train_end day 10
        self.assertEqual(p.train_cutoff_exclusive, day(7))
        self.assertEqual(p.excluded_interval, (day(7), day(10)))

    def test_zero_horizon_needs_justification_and_none_is_not_declared(self):
        with self.assertRaises(ValueError):
            purge_boundary(day(1), day(2), 0, 0)
        self.assertEqual(purge_boundary(day(1), day(2), 0, 0, "daily bars, one-day label closed at t").status, "NOT_REQUIRED_JUSTIFIED")  # fmt: skip
        self.assertEqual(purge_boundary(day(1), day(2), None).status, "NOT_DECLARED")

    def test_split_report_with_empty_validation(self):
        rep = validate_split_with_horizon(config().split, 0, 0, "justified")
        self.assertEqual(list(rep), ["train_to_test"])

    def test_walk_forward_windows_chronological(self):
        plan = WalkForwardPlan(WalkForwardMode.EXPANDING, day(0), day(29), 10, 5, 5, 2, 1)
        w = plan.windows()
        self.assertEqual(len(w), 3)  # tests start d10,15,20; a d25 window would end after data_end d29
        self.assertTrue(all(a.test_end < b.test_start for a, b in zip(w, w[1:])))
        self.assertTrue(all(x.train_end < x.test_start for x in w))
        self.assertFalse(w[0].earlier_test_windows_in_training)
        self.assertTrue(w[1].earlier_test_windows_in_training)
        self.assertEqual(w[0].purge.train_cutoff_exclusive, day(10) - timedelta(days=3))
        self.assertEqual(plan.plan_hash(), WalkForwardPlan(WalkForwardMode.EXPANDING, day(0), day(29), 10, 5, 5, 2, 1).plan_hash())

    def test_rolling_and_overlap_rejected(self):
        r = WalkForwardPlan(WalkForwardMode.ROLLING, day(0), day(29), 10, 5, 5, 0, 0, "justified", rolling_train_days=7).windows()
        self.assertEqual(r[1].train_start, r[1].test_start - timedelta(days=7))
        with self.assertRaises(ValueError):
            WalkForwardPlan(WalkForwardMode.EXPANDING, day(0), day(29), 10, 5, 3, 0, 0, "j").windows()

    def test_walk_forward_runs_and_refit_unsupported(self):
        data = make_bars(days=20)
        plan = WalkForwardPlan(WalkForwardMode.EXPANDING, day(-6), day(19), 6, 5, 5, 0, 0, "daily, same-day signal")
        out = run_walk_forward(ResearchHarness(), plan, config(), Tier1EqualWeightBuyHold(), data, [universe()])
        self.assertIn(out.status, ("COMPLETED", "FAILED"))
        self.assertEqual(out.refit, "NOT_APPLICABLE_FIXED_CONFIGURATION")
        self.assertEqual(len(out.window_results), 3)
        self.assertEqual(run_walk_forward(ResearchHarness(), plan, config(), None, data, [universe()], refit_required=True).status, "UNSUPPORTED")  # fmt: skip


class PboTests(unittest.TestCase):
    A = [3, 1, -2, 0]
    B = [0, 0, 1, 2]

    def test_hand_calculated_anti_persistent(self):
        # 6 combos; IS-best loses OOS rank in all (omega=1/3 five times, 1/2 once) -> PBO = 1.0
        r = compute_pbo({"A": self.A, "B": self.B}, 4, "MEAN_RETURN")
        self.assertEqual(r.status, PboStatus.OK)
        self.assertEqual(r.n_combinations, 6)
        self.assertEqual(r.pbo, 1.0)
        self.assertEqual(r.is_ties, 1)
        self.assertAlmostEqual(r.mean_logit, -5 * math.log(2) / 6, places=12)
        self.assertAlmostEqual(r.prob_oos_loss_of_selected, 2 / 6, places=12)

    def test_hand_calculated_persistent(self):
        # A always beats B everywhere: star=A, OOS rank 2 -> omega=2/3, logit=+ln2 > 0 -> PBO 0
        r = compute_pbo({"A": [2, 2, 2, 2], "B": [1, 1, 1, 1]}, 4, "MEAN_RETURN")
        self.assertEqual(r.pbo, 0.0)
        self.assertAlmostEqual(r.mean_logit, math.log(2), places=12)

    def test_unsupported_and_insufficient_return_no_number(self):
        for res in (compute_pbo({"A": self.A}, 4, "MEAN_RETURN"),
                    compute_pbo({"A": self.A, "B": self.B[:3]}, 4, "MEAN_RETURN"),
                    compute_pbo({"A": self.A, "B": [0, 0, 1, None]}, 4, "MEAN_RETURN"),
                    compute_pbo({"A": self.A, "B": self.B}, 3, "MEAN_RETURN"),
                    compute_pbo({"A": self.A + [1], "B": self.B + [1]}, 4, "MEAN_RETURN"),
                    compute_pbo({"A": self.A, "B": list(self.A)}, 4, "MEAN_RETURN"),  # identical candidates
                    compute_pbo({"A": [1, 1, 1, 1], "B": [2, 2, 2, 2]}, 4, "SHARPE")):  # zero variance
            self.assertIsNone(res.pbo)
            self.assertNotEqual(res.status, PboStatus.OK)
            self.assertTrue(res.reason)
        dup = compute_pbo({"A": self.A, "B": list(self.A)}, 4, "MEAN_RETURN")
        self.assertEqual(dup.duplicate_trial_ids, ("B",))
        self.assertEqual(dup.n_trials_supplied, 2)

    def test_noise_only_in_range(self):
        rng = random.Random(7)
        r = compute_pbo({f"t{i}": [Decimal(str(rng.gauss(0, 1))) for _ in range(64)] for i in range(10)}, 8, "SHARPE")
        self.assertEqual(r.status, PboStatus.OK)
        self.assertEqual(r.n_combinations, 70)
        self.assertTrue(0.0 <= r.pbo <= 1.0)
        self.assertEqual(r.n_trials_used, 10)

    def test_deterministic(self):
        rng = random.Random(1)
        d = {f"t{i}": [rng.gauss(0, 1) for _ in range(32)] for i in range(5)}
        self.assertEqual(compute_pbo(d, 4).to_dict(), compute_pbo(d, 4).to_dict())


class RegimeTests(unittest.TestCase):
    def test_trend_labels_hand_calculated(self):
        t = [day(i) for i in range(6)]
        levels = [Decimal(x) for x in (100, 110, 121, 110, 100, 100)]
        series = list(zip(t, levels))
        d = RegimeDefinition("syn", 1, RegimeDimension.TREND, 2, Decimal("0.05"), Decimal("0.05"), 1)
        lab = classify(series, d)
        self.assertEqual(lab[t[0]], "UNCLASSIFIED_INSUFFICIENT_HISTORY")
        self.assertEqual(lab[t[2]], "RISING")      # 121/100-1 = 21%
        self.assertEqual(lab[t[3]], "RANGE_BOUND")  # 110/110-1 = 0
        self.assertEqual(lab[t[4]], "FALLING")     # 100/121-1 = -17.4%
        self.assertEqual(lab[t[5]], "FALLING")     # 100/110-1 = -9.1% < -5%

    def test_labels_use_only_past_data(self):
        t = [day(i) for i in range(8)]
        a = list(zip(t, [Decimal(x) for x in (100, 101, 102, 103, 104, 105, 106, 107)]))
        b = a[:5] + [(x, Decimal(1)) for x, _ in a[5:]]  # change only the future
        d = RegimeDefinition("syn", 1, RegimeDimension.TREND, 2, Decimal("0.01"), Decimal("0.01"), 1)
        self.assertEqual({k: v for k, v in classify(a, d).items() if k <= t[4]}, {k: v for k, v in classify(b, d).items() if k <= t[4]})

    def test_segment_counts_and_insufficient_sample(self):
        t = [day(i) for i in range(5)]
        eq = [{"timestamp": x, "equity": Decimal(e)} for x, e in zip(t, (100, 110, 121, 121, 133.1))]
        labels = {t[0]: "RISING", t[1]: "RISING", t[2]: "RANGE_BOUND", t[3]: "RISING", t[4]: "RISING"}
        d = RegimeDefinition("syn", 1, RegimeDimension.TREND, 2, Decimal("0.05"), Decimal("0.05"), 3)
        seg = segment_equity(eq, labels, d)["regimes"]
        self.assertEqual(seg["RISING"]["samples"], 3)  # returns t0->1, t1->2, t3->4
        self.assertEqual(seg["RISING"]["status"], "OK")
        self.assertEqual(Decimal(seg["RISING"]["compounded_return"]).quantize(Decimal("0.0001")), Decimal("0.3310"))  # 1.1*1.1*1.1-1
        self.assertEqual(seg["RANGE_BOUND"]["status"], "INSUFFICIENT_SAMPLE")
        self.assertIsNone(seg["RANGE_BOUND"]["compounded_return"])

    def test_liquidity_unsupported(self):
        d = RegimeDefinition("liq", 1, RegimeDimension.LIQUIDITY, 2, Decimal("1"), None, 1)
        self.assertEqual(segment_equity([], {}, d)["status"], "UNSUPPORTED")

    def test_equal_weight_index(self):
        data = [bar(ISINS[0], 0, 100.0), bar(ISINS[1], 0, 200.0), bar(ISINS[0], 1, 110.0), bar(ISINS[1], 1, 200.0)]
        idx = equal_weight_index(data, set(ISINS[:2]))
        self.assertEqual(idx[1][1], Decimal(105))  # mean(+10%, 0%) = +5% -> 105


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.cm = CostModel()
        self.r = ResearchHarness().run(config(), Tier1EqualWeightBuyHold(), make_bars(), [universe()])
        self.assertTrue(self.r.succeeded, self.r.failure)

    def _with_equity(self, eqs):
        rows = tuple({"timestamp": day(i), "cash": Decimal(0), "market_value": Decimal(e), "equity": Decimal(e)} for i, e in enumerate(eqs))
        m = dict(self.r.metrics, initial_capital=Decimal(eqs[0]))
        return dataclasses.replace(self.r, equity_curve=rows, metrics=m)

    def test_drawdown_and_volatility_hand_calculated(self):
        x = compute_extended_metrics(self._with_equity([100, 110, 99, 121]), cost_model=self.cm, final_marks={})
        self.assertEqual(Decimal(x["max_drawdown"]["value"]), Decimal("0.1"))  # (110-99)/110
        self.assertEqual(x["max_drawdown_inr"]["value"], "11.00")
        rets = [0.1, -0.1, 121 / 99 - 1]
        self.assertAlmostEqual(float(x["periodic_volatility"]["value"]), statistics.stdev(rets), places=8)
        self.assertEqual(x["periodic_volatility"]["denominator"], "3 returns")
        self.assertEqual(x["annualised_volatility"]["status"], "UNSUPPORTED")  # no justified convention

    def test_annualisation_only_with_justification(self):
        x = compute_extended_metrics(self._with_equity([100, 110, 99, 121]), cost_model=self.cm, final_marks={},
                                     annualisation_periods_per_year=252, annualisation_justification="NSE ~252 sessions; daily cycles")  # fmt: skip
        self.assertAlmostEqual(float(x["annualised_volatility"]["value"]), statistics.stdev([0.1, -0.1, 121 / 99 - 1]) * math.sqrt(252), places=6)

    def test_insufficient_sample_is_not_zero(self):
        x = compute_extended_metrics(self._with_equity([100, 101]), cost_model=self.cm, final_marks={})
        self.assertIsNone(x["periodic_volatility"]["value"])
        self.assertEqual(x["periodic_volatility"]["status"], "INSUFFICIENT_SAMPLE")

    def _term(self, version, slip=None):
        cfg = config(cost_schedule_version=version)
        r = ResearchHarness().run(cfg, Tier1EqualWeightBuyHold(), make_bars(), [universe()])
        r = dataclasses.replace(r, final_positions=({"instrument_id": ISINS[0], "quantity": 100, "avg_cost": "1"},))
        a = ExecutionAssumptions(terminal_slippage_bps=slip, terminal_slippage_status=AssumptionStatus.ASSUMED_UNVERIFIED) if slip else None
        return r, compute_extended_metrics(r, cost_model=self.cm, final_marks={ISINS[0]: Decimal("200")}, assumptions=a)

    def test_terminal_liquidation_hand_calculated_both_schedules(self):
        # SELL 100 @ 200 = 20,000: STT 20.00 + exch(0.0000297|0.0000307 -> .59|.61) + SEBI .02 + GST 18%*(exch+sebi)=.11
        _, v1 = self._term(V1)
        _, v2 = self._term(V2)
        self.assertEqual(v1["terminal_liquidation"]["estimated_cost"], "20.72")
        self.assertEqual(v2["terminal_liquidation"]["estimated_cost"], "20.74")
        self.assertEqual(v2["terminal_liquidation"]["status"], "ESTIMATED_ASSUMPTION_BASED")

    def test_terminal_slippage_assumption(self):
        # 10 bps on 200 -> 199.80; turnover 19,980: STT 19.98 + exch .61 + sebi .02 + gst .11 = 20.72; slippage 100*0.20 = 20.00
        r, x = self._term(V2, Decimal(10))
        t = x["terminal_liquidation"]
        self.assertEqual(t["estimated_cost"], "20.72")
        self.assertEqual(t["assumed_slippage_cost"], "20.00")
        final_eq = Decimal(r.equity_curve[-1]["equity"])
        self.assertEqual(Decimal(t["result_after_terminal_liquidation"]), (final_eq - Decimal("20.72") - Decimal("20.00")).quantize(Decimal("0.01")))
        self.assertEqual(x["execution_assumptions"]["terminal_slippage"]["status"], "ASSUMED_UNVERIFIED")
        self.assertEqual(x["execution_assumptions"]["slippage_booked_trades"], "UNMODELLED")

    def test_terminal_cost_distinct_from_actual_and_unavailable_without_marks(self):
        x = compute_extended_metrics(self.r, cost_model=self.cm, final_marks=None)
        self.assertEqual(x["terminal_liquidation"]["status"], "UNAVAILABLE")
        self.assertIsNone(x["terminal_liquidation"]["estimated_cost"])
        self.assertEqual(Decimal(x["total_actual_costs"]["value"]).quantize(Decimal("0.01")), self.r.metrics["total_transaction_costs"])
        self.assertEqual(x["reconciliation_actual_costs_vs_portfolio"]["value"], "True")
        self.assertEqual(Decimal(x["actual_exit_costs"]["value"]), 0)  # buy-and-hold made no sell in window

    def test_entry_costs_hand_calculated(self):
        # Tier-1 buys on day0 fills at day1 open; entry cost per fill must equal STT+exch+sebi+gst+stamp on the fill turnover
        buys = [t for t in self.r.trades if t["side"] == "BUY"]
        self.assertTrue(buys)
        for t in buys:
            q, px = t["quantity"], Decimal(str(t["fill_price"]))
            turn = q * px
            stt = (turn * Decimal("0.001")).quantize(Decimal("0.01"), "ROUND_HALF_UP")
            exch = (turn * Decimal("0.0000307")).quantize(Decimal("0.01"), "ROUND_HALF_UP")
            sebi = (turn * Decimal("0.000001")).quantize(Decimal("0.01"), "ROUND_HALF_UP")
            gst = ((exch + sebi) * Decimal("0.18")).quantize(Decimal("0.01"), "ROUND_HALF_UP")
            stamp = (turn * Decimal("0.00015")).quantize(Decimal("0.01"), "ROUND_HALF_UP")
            self.assertEqual(t["cost_estimate"].total_cost, stt + exch + sebi + gst + stamp)

    def test_baseline_comparability(self):
        base = ResearchHarness().run(config(), Tier1EqualWeightBuyHold(), make_bars(), [universe()])
        x = compute_extended_metrics(self.r, cost_model=self.cm, final_marks=None, baseline=base)
        self.assertEqual(Decimal(x["baseline_relative_return"]["value"]), 0)
        other = ResearchHarness().run(config(cost_schedule_version=V1), Tier1EqualWeightBuyHold(), make_bars(), [universe()])
        y = compute_extended_metrics(self.r, cost_model=self.cm, final_marks=None, baseline=other)
        self.assertEqual(y["baseline_relative_return"]["status"], "NON_COMPARABLE")
        self.assertIsNone(y["baseline_relative_return"]["value"])

    def test_final_marks_from_data(self):
        r = dataclasses.replace(self.r, final_positions=({"instrument_id": ISINS[0], "quantity": 1, "avg_cost": "1"},))
        m = final_marks_from_market_data(r, make_bars())
        self.assertEqual(m[ISINS[0]], Decimal(str(100.0 + 9)))
        self.assertIsNone(final_marks_from_market_data(dataclasses.replace(r, final_positions=({"instrument_id": "NOPE", "quantity": 1, "avg_cost": "1"},)), make_bars()))  # fmt: skip


class QualityTests(unittest.TestCase):
    def test_delisted_instrument_fixture(self):
        u1 = make_permitted_universe(list(ISINS), day(0))
        u2 = make_permitted_universe(list(ISINS[:2]), day(5))  # ISINS[2] dropped
        data = [m for m in make_bars() if not (m.instrument_id == ISINS[2] and m.timestamp >= day(5))]
        prov = DatasetProvenance("syn", "v1", "synthetic", True)
        q = assess_quality(data, [u1, u2], prov)
        codes = {w["code"] for w in q["warnings"]}
        self.assertIn("POSSIBLE_SURVIVORSHIP_BIAS", codes)
        self.assertEqual(q["evidence_class"], "SYNTHETIC_INFRASTRUCTURE")
        prov2 = DatasetProvenance("syn", "v1", "synthetic", True, delisted_instruments=frozenset({ISINS[2]}))
        codes2 = {w["code"] for w in assess_quality(data, [u1, u2], prov2)["warnings"]}
        self.assertNotIn("POSSIBLE_SURVIVORSHIP_BIAS", codes2)

    def test_historical_unverified_and_adjustment_mismatch(self):
        data = make_bars()
        data[0] = dataclasses.replace(data[0], adjusted=True)
        q = assess_quality(data, [universe()], DatasetProvenance("h", "v", "vendor", False))
        codes = {w["code"] for w in q["warnings"]}
        self.assertTrue({"CORPORATE_ACTION_ADJUSTMENT_MISMATCH", "UNVERIFIED_HISTORY_SOURCE", "POINT_IN_TIME_NOT_VERIFIED"} <= codes)
        self.assertEqual(q["evidence_class"], "HISTORICAL_UNVERIFIED")

    def test_missing_bars_and_stale_and_identity_gap(self):
        data = make_bars(skip={(ISINS[0], 3)})
        q = assess_quality(data, [make_permitted_universe(list(ISINS[:1]), day(0))], DatasetProvenance("s", "v", "x", True))
        codes = {w["code"] for w in q["warnings"]}
        self.assertIn("MISSING_BARS", codes)
        self.assertIn("IDENTITY_MAPPING_GAP", codes)
        flat = [bar(ISINS[0], i, 100.0, open_=100.0) for i in range(4)]
        self.assertIn("STALE_OBSERVATIONS", {w["code"] for w in assess_quality(flat, [universe(ISINS[:1])], DatasetProvenance("s", "v", "x", True))["warnings"]})  # fmt: skip


class EvaluationIntegrationTests(unittest.TestCase):
    def _report(self, root, p, holdout="UNTOUCHED", mode_reg="2026-01-01T00:00:00+00:00", synthetic=True, pit_clean=False):
        data = make_bars()
        led = _ledger(data)
        h = ResearchHarness(availability=led)
        r = h.run(config(), Tier1EqualWeightBuyHold(), data, [universe()])
        write_run(r, root)
        ext = compute_extended_metrics(r, cost_model=CostModel(), final_marks=final_marks_from_market_data(r, data))
        q = assess_quality(data, [universe()], DatasetProvenance("syn", "v", "synthetic", synthetic))
        rep = build_report(protocol=p, protocol_hash=p.protocol_hash(), protocol_registered_at=mode_reg, result=r,
                           extended_metrics=ext, quality=q, holdout_status=holdout, trial_count=3, ledger_head_hash="abc",
                           pbo=None, regimes=None, walk_forward=None,
                           purge=validate_split_with_horizon(p.split, p.information_horizon_days, 0, "justified"),
                           journal_refs={"run": "ref-1"})  # fmt: skip
        return r, data, rep

    def test_synthetic_verdict_and_no_profit_claim(self):
        with tempfile.TemporaryDirectory() as d:
            _, _, rep = self._report(d, proto())
            self.assertEqual(rep["verdict"], "INFRASTRUCTURE_ONLY")
            self.assertEqual(rep["profitability_claim"], "NONE")
            self.assertEqual(rep["evidence_class"], "SYNTHETIC_INFRASTRUCTURE")
            self.assertEqual(rep["trial_accounting"]["trials_recorded_for_protocol_family"], 3)
            self.assertIn("not evidence", rep["uncertainty_notice"])

    def test_reused_holdout_downgraded_and_unregistered_unsupported(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._report(d, proto(), holdout="REUSED_NON_CONFIRMATORY")[2]["verdict"], "EXPLORATORY_ONLY")
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._report(d, proto(), mode_reg=None)[2]["verdict"], "UNSUPPORTED")
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._report(d, proto(mode=ExperimentMode.EXPLORATORY))[2]["verdict"], "EXPLORATORY_ONLY")

    def test_hashes_linked_reproducible_and_failures_detected(self):
        with tempfile.TemporaryDirectory() as d:
            r, data, rep = self._report(d, proto())
            path = write_report(rep, d)
            self.assertEqual(write_report(rep, d), path)  # idempotent
            self.assertEqual(rep["report_hash"], build_hash(rep))
            out = reproduce_run(d, path, harness=ResearchHarness(availability=_ledger(data)), config=config(),
                                strategy=Tier1EqualWeightBuyHold(), market_data=data, universe_schedule=[universe()])  # fmt: skip
            self.assertTrue(out["reproduced"])
            with self.assertRaises(ReproducibilityFailure) as c:
                reproduce_run(d, path, harness=ResearchHarness(), config=config(), strategy=Tier1EqualWeightBuyHold(), market_data=None, universe_schedule=[universe()])  # noqa: E501
            self.assertEqual(c.exception.kind, "MISSING_INPUT")
            # corrupt a stored artifact
            tr = Path(d) / "runs" / r.run_id / "trades.jsonl"
            tr.write_text(tr.read_text() + "x")
            with self.assertRaises(ReproducibilityFailure) as c2:
                reproduce_run(d, path, harness=ResearchHarness(), config=config(), strategy=Tier1EqualWeightBuyHold(), market_data=data, universe_schedule=[universe()])  # noqa: E501
            self.assertEqual(c2.exception.kind, "CORRUPT_ARTIFACT")
            import shutil
            shutil.rmtree(Path(d) / "runs" / r.run_id)
            with self.assertRaises(ReproducibilityFailure) as c3:
                reproduce_run(d, path, harness=ResearchHarness(), config=config(), strategy=Tier1EqualWeightBuyHold(), market_data=data, universe_schedule=[universe()])  # noqa: E501
            self.assertEqual(c3.exception.kind, "MISSING_ARTIFACT")

    def test_failed_run_is_invalid_or_unsupported_and_preserved_in_ledger(self):
        data = make_bars()
        bad = config(strategy_configured_through=day(5))  # configured after OOS start -> contamination
        r = ResearchHarness().run(bad, Tier1EqualWeightBuyHold(), data, [universe()])
        self.assertFalse(r.succeeded)
        with tempfile.TemporaryDirectory() as d:
            led = TrialLedger(d, clock=lambda: CLOCK0)
            led.record(protocol_id="p", protocol_hash="h", strategy_id=r.strategy_version_id, mode="CONFIRMATORY",
                       outcome=TrialOutcome.EXCLUDED_VALIDITY_FAILURE, run_id=r.run_id, reason=r.failure.message)  # fmt: skip
            self.assertEqual(led.count(), 1)
            write_run(r, d)  # failed runs persist
            self.assertTrue((Path(d) / "runs" / r.run_id / "failure.json").exists())
            rep = build_report(protocol=proto(), protocol_hash="h", protocol_registered_at="x", result=r, extended_metrics={"status": "UNAVAILABLE"},
                               quality=assess_quality(data, [universe()], DatasetProvenance("s", "v", "x", True)), holdout_status="UNTOUCHED",
                               trial_count=1, ledger_head_hash=led.head_hash(), pbo=None, regimes=None, walk_forward=None, purge=None)  # fmt: skip
            self.assertEqual(rep["verdict"], "INVALID")


def build_hash(rep):
    from research.harness.jsonio import jsonable
    from shared.versioning.content_hash import hash_json_stable
    body = {k: v for k, v in rep.items() if k != "report_hash"}
    return hash_json_stable(jsonable(body))


if __name__ == "__main__":
    unittest.main()
