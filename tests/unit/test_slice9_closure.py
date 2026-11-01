"""Slice 9 acceptance-closure tests: the enforced evaluation workflow. SYNTHETIC data only.

`historical=True` builds a fixture whose *labels* claim verified provenance so the
verdict logic can be exercised; the bars are still synthetic and prove nothing about markets.
"""

import dataclasses
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from intelligence.baseline.tier1_equal_weight import STRATEGY_VERSION_ID, Tier1EqualWeightBuyHold
from research.contamination.point_in_time import (
    AvailabilityBasis as AB,
    AvailabilityLedger,
    VersionedObservation as VO,
)
from research.harness.runner import ResearchHarness
from research.protocol.protocol import (
    AcceptanceCriterion,
    Comparator,
    ExperimentMode,
    HoldoutReusePolicy,
)
from research.protocol.registry import ProtocolRegistry
from research.trials.holdout import holdout_id_for
from research.trials.ledger import TrialLedger, TrialOutcome
from research.validity.evaluation import build_report, build_verified_report
from research.validity.quality import DatasetProvenance
from research.validity.service import ResearchEvaluationService, compute_dataset_hash
from tests.unit._research_helpers import V1, V2, config, day, make_bars, universe
from tests.unit.test_slice9_validity import proto as base_proto

REG_TIME = datetime(2026, 1, 1, tzinfo=UTC)
RUN_TIME = datetime(2026, 2, 1, tzinfo=UTC)
CFG_CUTOFF = day(-31)


class Ctx:
    def __init__(self, root, historical=False, unknown_obs=False, **proto_over):
        self.root = root
        self.data = make_bars()
        self.uni = [universe()]
        self.historical = historical
        self.avail = None
        if historical:
            obs = [VO(m, 0, m.timestamp, AB.SOURCE_PUBLISHED) for m in self.data]
            if unknown_obs:
                obs.append(
                    VO(
                        dataclasses.replace(
                            self.data[0], timestamp=day(0), instrument_id="INE000Z00009"
                        )
                    )
                )
            self.avail = AvailabilityLedger(obs)
        self.dhash = compute_dataset_hash(self.data, self.avail)
        self.cfg = config(strategy_configured_through=CFG_CUTOFF)
        self.hid = holdout_id_for(dataset_id="synthetic", dataset_hash=self.dhash, universe_versions=(self.uni[0].version,),
                                  test_start=self.cfg.split.test_start, test_end=self.cfg.split.test_end)  # fmt: skip
        args = dict(dataset_version=self.dhash, holdout_id=self.hid, strategy_version_ids=(STRATEGY_VERSION_ID,),
                    benchmark_version_ids=("b1",), universe_versions=(self.uni[0].version,), data_start=day(0), data_end=day(9),
                    strategy_configured_through=CFG_CUTOFF, hypothesis=self.cfg.hypothesis, split=self.cfg.split,
                    links={"information_horizon_justification": "daily bars; label closed at t"},
                    acceptance_criteria=(AcceptanceCriterion("max_drawdown", Comparator.GT, "0.5", "adverse if >50%", adverse=True),),
                    primary_metrics=("net_return",), secondary_metrics=("max_drawdown", "annualised_volatility"))  # fmt: skip
        args.update(proto_over)
        self.protocol = base_proto(**args)
        self.prov = DatasetProvenance("synthetic", "v1", "synthetic fixture", not historical, source_verified=historical,
                                      point_in_time_verified=historical, survivorship_free_claimed=historical,
                                      corporate_actions_source="fixture" if historical else None)  # fmt: skip

    def register(self, protocol=None, at=REG_TIME):
        return ProtocolRegistry(self.root, clock=lambda: at).register(protocol or self.protocol)

    def service(self, at=RUN_TIME, **kw):
        return ResearchEvaluationService(self.root, clock=lambda: at, **kw)

    def run(self, svc=None, protocol=None, **kw):
        args = dict(protocol=protocol or self.protocol, config=self.cfg, strategy=Tier1EqualWeightBuyHold(), market_data=self.data,
                    universe_schedule=self.uni, provenance=self.prov, availability=self.avail, baseline_ids=("b1",))  # fmt: skip
        args.update(kw)
        return (svc or self.service()).evaluate(**args)


def tmp():
    return tempfile.TemporaryDirectory()


class ProtocolEnforcementTests(unittest.TestCase):
    def test_confirmatory_without_registration_is_refused_and_recorded(self):
        with tmp() as d:
            c = Ctx(d)
            out = c.run()
            self.assertEqual(out.status, "REJECTED_PREFLIGHT")
            self.assertTrue(any("PROTOCOL" in r for r in out.reasons))
            led = TrialLedger(d)
            self.assertEqual([e.outcome for e in led.logical_trials()], [TrialOutcome.REJECTED])
            self.assertFalse((Path(d) / "runs").exists())  # the harness never ran

    def test_registration_after_evaluation_start_cannot_confirm(self):
        with tmp() as d:
            c = Ctx(d)
            c.register(at=datetime(2026, 3, 1, tzinfo=UTC))  # later than the service clock (Feb 1)
            self.assertEqual(c.run().status, "REJECTED_PREFLIGHT")

    def test_changed_protocol_same_id_version_is_rejected(self):
        with tmp() as d:
            c = Ctx(d)
            c.register()
            out = c.run(
                protocol=dataclasses.replace(c.protocol, research_question="changed afterwards")
            )
            self.assertEqual(out.status, "REJECTED_PREFLIGHT")
            self.assertTrue(any("differs from the frozen" in r for r in out.reasons))

    def test_material_mismatches_are_rejected_not_substituted(self):
        cases = {
            "strategy": dict(strategy=type("S", (), {"strategy_version_id": "other"})()),
            "cost schedule": dict(
                config=config(strategy_configured_through=CFG_CUTOFF, cost_schedule_version=V1)
            ),
            "split/window": dict(
                config=config(
                    strategy_configured_through=CFG_CUTOFF,
                    split=config().split.__class__(
                        config().split.train_start,
                        config().split.train_end,
                        config().split.validation_start,
                        config().split.validation_end,
                        config().split.test_start,
                        day(8),
                    ),
                )
            ),  # fmt: skip
            "baselines": dict(baseline_ids=("not-in-protocol",)),
            "universe": dict(universe_schedule=[universe(("INE000A00001", "INE000B00002"))]),
            "hypothesis": dict(
                config=config(
                    strategy_configured_through=CFG_CUTOFF, hypothesis="a different hypothesis"
                )
            ),
            "config cutoff": dict(config=config(strategy_configured_through=day(-40))),
        }
        for name, over in cases.items():
            with self.subTest(name), tmp() as d:
                c = Ctx(d)
                c.register()
                out = c.run(**over)
                self.assertEqual(out.status, "REJECTED_PREFLIGHT", out.reasons)
                self.assertTrue(any("MISMATCH" in r for r in out.reasons), out.reasons)

    def test_dataset_and_holdout_identity_must_match(self):
        with tmp() as d:
            c = Ctx(d, dataset_version="not-the-hash")
            c.register()
            self.assertTrue(any("dataset_version" in r for r in c.run().reasons))
        with tmp() as d:
            c = Ctx(d, holdout_id="holdout_forged")
            c.register()
            self.assertTrue(any("holdout_id" in r for r in c.run().reasons))

    def test_fabricated_timestamp_and_forged_evidence_cannot_confirm(self):
        with tmp() as d:
            c = Ctx(d, historical=True)
            c.register()
            ok = c.run()
            self.assertEqual(ok.report["research_validity_verdict"], "CONFIRMATORY_CHECKS_PASSED")
            ev = ok.evidence
            forged = dataclasses.replace(ev, protocol_hash="0" * 64)
            r = build_verified_report(
                evidence=forged,
                protocol=c.protocol,
                result=ok.result,
                extended_metrics=ok.report["metrics"],
                quality=ok.report["dataset_quality"],
            )  # noqa: E501
            self.assertEqual(r["research_validity_verdict"], "UNSUPPORTED")
            self.assertEqual(r["evidence_verification"], "FAILED")
            fake_start = dataclasses.replace(
                ev, evaluation_started_at=datetime(2030, 1, 1, tzinfo=UTC)
            )
            r2 = build_verified_report(
                evidence=fake_start,
                protocol=c.protocol,
                result=ok.result,
                extended_metrics=ok.report["metrics"],
                quality=ok.report["dataset_quality"],
            )  # noqa: E501
            self.assertNotEqual(r2["research_validity_verdict"], "CONFIRMATORY_CHECKS_PASSED")
            legacy = build_report(
                protocol=c.protocol,
                protocol_hash=c.protocol.protocol_hash(),
                protocol_registered_at="2020-01-01T00:00:00+00:00",
                result=ok.result,
                extended_metrics=ok.report["metrics"],
                quality=ok.report["dataset_quality"],
                holdout_status="UNTOUCHED",
                trial_count=1,
                ledger_head_hash="x",
                pbo=None,
                regimes=None,
                walk_forward=None,
                purge=None,
            )  # noqa: E501
            self.assertNotEqual(legacy["research_validity_verdict"], "CONFIRMATORY_CHECKS_PASSED")


class HoldoutEnforcementTests(unittest.TestCase):
    def test_first_exposure_untouched_then_reject_policy_blocks_reuse(self):
        with tmp() as d:
            c = Ctx(d, historical=True)
            c.register()
            first = c.run()
            self.assertEqual(first.report["holdout"]["status"], "UNTOUCHED")
            self.assertEqual(
                first.report["research_validity_verdict"], "CONFIRMATORY_CHECKS_PASSED"
            )
            runs_before = len(list((Path(d) / "runs").iterdir()))
            second = c.run()
            self.assertEqual(second.status, "REJECTED_PREFLIGHT")
            self.assertEqual(
                len(list((Path(d) / "runs").iterdir())), runs_before
            )  # blocked BEFORE evaluation
            led = TrialLedger(d)
            self.assertEqual(
                [e.outcome for e in led.logical_trials()],
                [TrialOutcome.COMPLETED, TrialOutcome.REJECTED],
            )
            self.assertTrue(led.logical_trials()[1].holdout_reused)

    def test_downgrade_policy_is_non_confirmatory(self):
        with tmp() as d:
            c = Ctx(
                d,
                historical=True,
                holdout_reuse_policy=HoldoutReusePolicy.DOWNGRADE_TO_NON_CONFIRMATORY,
            )
            c.register()
            c.run()
            second = c.run()
            self.assertEqual(second.status, "COMPLETED")
            self.assertEqual(second.report["holdout"]["status"], "REUSED_NON_CONFIRMATORY")
            self.assertEqual(second.report["research_validity_verdict"], "EXPLORATORY_ONLY")

    def test_caller_cannot_force_untouched(self):
        with tmp() as d:
            c = Ctx(
                d,
                historical=True,
                holdout_reuse_policy=HoldoutReusePolicy.DOWNGRADE_TO_NON_CONFIRMATORY,
            )
            c.register()
            c.run()
            second = c.run()
            forged = dataclasses.replace(
                second.evidence, exposure_recorded=False
            )  # pretend no exposure
            r = build_verified_report(
                evidence=forged,
                protocol=c.protocol,
                result=second.result,
                extended_metrics=second.report["metrics"],
                quality=second.report["dataset_quality"],
            )  # noqa: E501
            self.assertNotEqual(r["research_validity_verdict"], "CONFIRMATORY_CHECKS_PASSED")
            self.assertNotEqual(r["holdout"]["status"], "UNTOUCHED")

    def test_new_protocol_version_cannot_reset_holdout(self):
        with tmp() as d:
            c = Ctx(d, historical=True)
            r1 = c.register()
            c.run()
            p2 = dataclasses.replace(
                c.protocol,
                version=2,
                supersedes_protocol_hash=r1.protocol_hash,
                research_question="v2",
            )
            c.register(p2)
            out = c.run(protocol=p2)
            self.assertEqual(out.status, "REJECTED_PREFLIGHT")
            self.assertIn("already exposed", out.reasons[0])


class TrialAccountingTests(unittest.TestCase):
    def test_success_recorded_with_lifecycle_and_derived_counts(self):
        with tmp() as d:
            c = Ctx(d, historical=True)
            c.register()
            out = c.run()
            led = TrialLedger(d)
            self.assertEqual(led.count(), 1)
            self.assertEqual(led.event_count(), 2)  # START + TERMINAL are one logical trial
            self.assertEqual(led.verify(), [])
            ta = out.report["trial_accounting"]
            self.assertEqual(ta["trial_count"], 1)
            self.assertEqual(ta["event_count"], 2)
            self.assertEqual(ta["ledger_head_hash"], led.head_hash())
            self.assertEqual(ta["derived_from"], "verified trial ledger")
            self.assertEqual(ta["trials_by_outcome"], {"COMPLETED": 1})

    def test_failed_and_invalid_and_excluded_runs_are_recorded(self):
        with tmp() as d:
            c = Ctx(d, mode=ExperimentMode.EXPLORATORY)
            bad = config(strategy_configured_through=day(5))
            out = c.run(config=bad)  # contamination: configured after OOS start
            self.assertEqual(out.status, "FAILED")
            self.assertEqual(out.report["research_validity_verdict"], "INVALID")
            self.assertEqual(out.report["criterion_outcome"], "INCONCLUSIVE")
            inv = c.run(config=config(initial_capital="-5", strategy_configured_through=CFG_CUTOFF))
            self.assertEqual(inv.status, "FAILED")
            outcomes = [e.outcome for e in TrialLedger(d).logical_trials()]
            self.assertEqual(outcomes[0], TrialOutcome.EXCLUDED_VALIDITY_FAILURE)
            self.assertIn(outcomes[1], (TrialOutcome.INVALID_CONFIGURATION, TrialOutcome.FAILED))
            self.assertTrue(all(o is not TrialOutcome.STARTED for o in outcomes))
            self.assertTrue((Path(d) / "runs" / out.result.run_id / "failure.json").exists())

    def test_worse_than_baseline_remains_visible(self):
        with tmp() as d:
            c = Ctx(d, mode=ExperimentMode.EXPLORATORY)
            base = ResearchHarness().run(c.cfg, Tier1EqualWeightBuyHold(), c.data, c.uni)
            better = dataclasses.replace(base, metrics=dict(base.metrics, total_return="9.99"))
            out = c.run(baseline_result=better)
            self.assertEqual(
                TrialLedger(d).logical_trials()[0].outcome,
                TrialOutcome.COMPLETED_WORSE_THAN_BASELINE,
            )
            self.assertEqual(
                out.report["trial_accounting"]["trials_by_outcome"],
                {"COMPLETED_WORSE_THAN_BASELINE": 1},
            )

    def test_interrupted_attempt_detected_and_recovered_without_fabrication(self):
        with tmp() as d:
            led = TrialLedger(d, clock=lambda: RUN_TIME)
            led.record(
                protocol_id="p",
                protocol_hash="h",
                strategy_id="s",
                mode="CONFIRMATORY",
                outcome=TrialOutcome.STARTED,
                lifecycle="START",
                attempt_id="attempt_x",
            )  # crash right after START
            reopened = ResearchEvaluationService(d, clock=lambda: RUN_TIME).ledger
            self.assertEqual([e.attempt_id for e in reopened.unresolved()], ["attempt_x"])
            self.assertEqual(reopened.count(), 1)
            svc = ResearchEvaluationService(d, clock=lambda: RUN_TIME)
            self.assertEqual(svc.recover_interrupted(), 1)
            self.assertEqual(svc.recover_interrupted(), 0)
            t = svc.ledger.logical_trials()[0]
            self.assertEqual(t.outcome, TrialOutcome.INTERRUPTED)
            self.assertIsNone(t.run_id)  # no result fabricated
            self.assertEqual((svc.ledger.count(), svc.ledger.event_count()), (1, 2))
            self.assertEqual(svc.ledger.verify(), [])

    def test_keyboard_interrupt_is_recorded_then_propagates(self):
        class Boom:
            def run(self, *a, **k):
                raise KeyboardInterrupt

        with tmp() as d:
            c = Ctx(d, mode=ExperimentMode.EXPLORATORY)
            with self.assertRaises(KeyboardInterrupt):
                c.run(svc=c.service(harness_factory=lambda av: Boom()))
            self.assertEqual(TrialLedger(d).logical_trials()[0].outcome, TrialOutcome.INTERRUPTED)

    def test_lifecycle_rules(self):
        with tmp() as d:
            led = TrialLedger(d)
            from research.trials.ledger import TrialLedgerError

            with self.assertRaises(TrialLedgerError):  # terminal without START
                led.record(
                    protocol_id="p",
                    protocol_hash="h",
                    strategy_id="s",
                    mode="X",
                    outcome=TrialOutcome.FAILED,
                    reason="r",
                    lifecycle="TERMINAL",
                    attempt_id="nope",
                )  # noqa: E501
            led.record(
                protocol_id="p",
                protocol_hash="h",
                strategy_id="s",
                mode="X",
                outcome=TrialOutcome.STARTED,
                lifecycle="START",
                attempt_id="a",
            )
            led.record(
                protocol_id="p",
                protocol_hash="h",
                strategy_id="s",
                mode="X",
                outcome=TrialOutcome.COMPLETED,
                lifecycle="TERMINAL",
                attempt_id="a",
            )
            with self.assertRaises(TrialLedgerError):  # second terminal
                led.record(
                    protocol_id="p",
                    protocol_hash="h",
                    strategy_id="s",
                    mode="X",
                    outcome=TrialOutcome.FAILED,
                    reason="r",
                    lifecycle="TERMINAL",
                    attempt_id="a",
                )  # noqa: E501

    def test_ledger_tampering_blocks_confirmatory_claim(self):
        with tmp() as d:
            c = Ctx(d, historical=True)
            c.register()
            c.run()
            p = Path(d) / "trials" / "ledger.jsonl"
            lines = p.read_text().splitlines()
            p.write_text("\n".join(lines[1:]) + "\n")  # drop the START entry
            self.assertTrue(TrialLedger(d).verify())
            c2 = Ctx(
                d,
                historical=True,
                holdout_reuse_policy=HoldoutReusePolicy.DOWNGRADE_TO_NON_CONFIRMATORY,
            )
            out = c.run()
            self.assertEqual(out.status, "REJECTED_PREFLIGHT")
            self.assertTrue(any("LEDGER_CORRUPT" in r for r in out.reasons))
            del c2


class ReportSemanticsTests(unittest.TestCase):
    def _hist(self, **over):
        d = tempfile.TemporaryDirectory()
        c = Ctx(d.name, historical=True, **over)
        c.register()
        return d, c, c.run()

    def test_valid_methodology_with_unmet_criterion(self):
        d, c, out = self._hist(
            acceptance_criteria=(
                AcceptanceCriterion("net_return", Comparator.GT, "100", "needs >10000%"),
            )
        )
        with d:
            self.assertEqual(out.report["research_validity_verdict"], "CONFIRMATORY_CHECKS_PASSED")
            self.assertEqual(out.report["criterion_outcome"], "CRITERIA_NOT_MET")
            self.assertEqual(out.report["profitability_claim"], "NONE")
            self.assertIn("NOT a statement about returns", out.report["verdict_meaning"])

    def test_adverse_criterion_without_implying_contamination(self):
        d, c, out = self._hist(
            acceptance_criteria=(
                AcceptanceCriterion(
                    "max_drawdown", Comparator.GT, "-1", "any drawdown is adverse", adverse=True
                ),
            )
        )
        with d:
            self.assertEqual(out.report["criterion_outcome"], "ADVERSE")
            self.assertEqual(out.report["research_validity_verdict"], "CONFIRMATORY_CHECKS_PASSED")
            self.assertFalse(any("contamin" in r.lower() for r in out.report["reasons"]))

    def test_criteria_met_is_reported_only_as_met(self):
        d, c, out = self._hist(
            acceptance_criteria=(
                AcceptanceCriterion("net_return", Comparator.GT, "-1", "trivially met"),
            )
        )
        with d:
            self.assertEqual(out.report["criterion_outcome"], "CRITERIA_MET")
            self.assertEqual(out.report["profitability_claim"], "NONE")

    def test_unavailable_primary_metric_is_inconclusive(self):
        d, c, out = self._hist(
            acceptance_criteria=(
                AcceptanceCriterion(
                    "annualised_volatility", Comparator.LT, "1", "needs a convention"
                ),
            )
        )
        with d:
            self.assertEqual(out.report["criterion_outcome"], "INCONCLUSIVE")

    def test_synthetic_stays_infrastructure_only_even_with_attractive_metrics(self):
        with tmp() as d:
            c = Ctx(
                d,
                acceptance_criteria=(
                    AcceptanceCriterion("net_return", Comparator.GT, "-1", "trivially met"),
                ),
            )
            c.register()
            out = c.run()
            self.assertEqual(out.report["criterion_outcome"], "CRITERIA_MET")
            self.assertEqual(out.report["research_validity_verdict"], "INFRASTRUCTURE_ONLY")
            self.assertFalse(out.report["criterion_outcome_admissible_as_evidence"])

    def test_unknown_availability_cannot_yield_clean_verdict(self):
        with tmp() as d:
            c = Ctx(d, historical=True, unknown_obs=True)
            c.register()
            out = c.run()
            self.assertIn(out.status, ("COMPLETED", "FAILED"))
            self.assertNotEqual(
                out.report["research_validity_verdict"], "CONFIRMATORY_CHECKS_PASSED"
            )

    def test_blocking_quality_problem_cannot_yield_clean_verdict(self):
        with tmp() as d:
            c = Ctx(d, historical=True)
            c.prov = dataclasses.replace(c.prov, source_verified=False)
            c.register()
            out = c.run()
            self.assertEqual(out.report["research_validity_verdict"], "UNSUPPORTED")
            self.assertEqual(out.report["evidence_class"], "HISTORICAL_UNVERIFIED")

    def test_report_schema_version_and_no_overwrite(self):
        d, c, out = self._hist()
        with d:
            self.assertEqual(out.report["schema"], "validity-report-v2")
            self.assertTrue(out.report_path.exists())
            self.assertEqual(out.report["evidence_verification"], "VERIFIED")


if __name__ == "__main__":
    unittest.main()
