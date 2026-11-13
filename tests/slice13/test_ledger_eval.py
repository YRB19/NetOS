import json
import tempfile
import unittest
from datetime import timedelta

from data.live.quality import QualityEngine
from data.live.reader import ObservationReader
from data.live.store import ObservationStore
from markets.lane import DataProvenance, MarketLane
from observability.prediction_ledger.ledger import LedgerError, PredictionLedger
from prediction_ledger.models import (
    ConfidenceSemantics, Direction, PredictionEventType, PredictionRecord, PredictionStatus,
)  # fmt: skip
from prediction_ledger.reader import LedgerReader, LedgerReadError, verify_ledger
from research.prediction_eval.claims import Claim, ClaimKind, ClaimStatus, check_claim
from research.prediction_eval.evaluator import (
    CoverageInputs, OutcomeEvaluator, Unscored, coverage_report, evidence_class, summarize,
)  # fmt: skip
from research.prediction_eval.metrics import brier, spearman_ic, wilson_interval
from tests.slice13.helpers import T0, obs, policy, pred

L = MarketLane.US_EQUITIES
REC = T0 + timedelta(seconds=30)  # commit before valid_from (T0+1m)


def feed(root, rows, provider="SYNTH_A", prov=DataProvenance.SYNTHETIC):
    s, q = ObservationStore(root, L), QualityEngine(policy())
    for inst, t, c in rows:
        o = obs(inst=inst, t=t, close=c, provider=provider, prov=prov)
        s.append(o, q.assess(o))


class LedgerTests(unittest.TestCase):
    def test_record_and_read(self):
        with tempfile.TemporaryDirectory() as d:
            led = PredictionLedger(d, L)
            self.assertEqual(led.record(pred(), REC), PredictionEventType.RECORDED)
            v = LedgerReader(d, L).views()
            self.assertEqual(len(v), 1)
            self.assertTrue(v[0].scoreable)

    def test_late_commit_preserved_but_not_scoreable(self):
        with tempfile.TemporaryDirectory() as d:
            led = PredictionLedger(d, L)
            self.assertEqual(led.record(pred(), T0 + timedelta(minutes=5)), PredictionEventType.REJECTED_LATE)
            v = LedgerReader(d, L).views()[0]
            self.assertTrue(v.late_rejected)
            self.assertFalse(v.scoreable)

    def test_non_issued_statuses_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            led = PredictionLedger(d, L)
            for i, st in enumerate(PredictionStatus):
                led.record(pred(pid=f"p{i}", status=st), REC)
            r = LedgerReader(d, L)
            self.assertEqual(len(r.views()), len(PredictionStatus))
            self.assertEqual(sum(v.scoreable for v in r.views()), 1)

    def test_duplicate_id_refused_correction_is_linked_event(self):
        with tempfile.TemporaryDirectory() as d:
            led = PredictionLedger(d, L)
            led.record(pred(), REC)
            with self.assertRaises(LedgerError):
                led.record(pred(), REC)
            led.correct(pred(direction=Direction.DOWN), REC, "typo")
            v = LedgerReader(d, L).views()[0]
            self.assertEqual((v.original.direction, v.record.direction, v.corrections),
                             (Direction.UP, Direction.DOWN, 1))
            self.assertEqual(verify_ledger(led.path).count, 2)

    def test_no_hindsight_corrections(self):
        with tempfile.TemporaryDirectory() as d:
            led = PredictionLedger(d, L)
            led.record(pred(), REC)
            with self.assertRaises(LedgerError):
                led.correct(pred(direction=Direction.DOWN), T0 + timedelta(hours=3), "hindsight")

    def test_invalidation_keeps_history(self):
        with tempfile.TemporaryDirectory() as d:
            led = PredictionLedger(d, L)
            led.record(pred(), REC)
            led.invalidate("p1", T0 + timedelta(hours=3), "bad input")
            v = LedgerReader(d, L).views()[0]
            self.assertTrue(v.invalidated)
            self.assertFalse(v.scoreable)
            self.assertEqual(v.original.direction, Direction.UP)

    def test_lane_mismatch_and_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            led = PredictionLedger(d, L)
            with self.assertRaises(LedgerError):
                led.record(pred(lane=MarketLane.IN_EQUITIES), REC)
            led.record(pred(), REC)
            led.record(pred(pid="p2"), REC)
            lines = led.path.read_text().splitlines()
            rec = json.loads(lines[0])
            rec["body"]["record"]["direction"] = "DOWN"
            lines[0] = json.dumps(rec, sort_keys=True)
            led.path.write_text("\n".join(lines) + "\n")
            with self.assertRaises(LedgerReadError):
                LedgerReader(d, L)

    def test_record_validation(self):
        with self.assertRaises(ValueError):
            pred(confidence=1.5)
        with self.assertRaises(ValueError):
            pred(confidence_semantics=ConfidenceSemantics.CALIBRATED_PROBABILITY_CLAIMED)
        with self.assertRaises(ValueError):
            PredictionRecord.from_dict({**pred().to_dict(), "direction": None})


class EvaluatorTests(unittest.TestCase):
    def mk(self, d, rows, **kw):
        feed(d, rows, **kw)
        PredictionLedger(d, L).record(pred(), REC)
        return OutcomeEvaluator(L, LedgerReader(d, L), ObservationReader(d, L))

    @staticmethod
    def rows(inst_end=103.0, bench_end=100.0):
        t1, t2 = T0 + timedelta(minutes=1), T0 + timedelta(minutes=61)
        return [("AAA", t1, 100.0), ("AAA", t2, inst_end), ("SPY", t1, 100.0), ("SPY", t2, bench_end)]

    def test_scored_hit_up_vs_benchmark(self):
        with tempfile.TemporaryDirectory() as d:
            ev = self.mk(d, self.rows())
            o = ev.evaluate(T0 + timedelta(hours=2))[0]
            self.assertTrue(o.scored)
            self.assertTrue(o.hit)
            self.assertAlmostEqual(o.relative_return, 0.03)
            self.assertEqual(o.provenances, ("SYNTHETIC",))

    def test_miss_when_benchmark_outruns(self):
        with tempfile.TemporaryDirectory() as d:
            o = self.mk(d, self.rows(103, 110)).evaluate(T0 + timedelta(hours=2))[0]
            self.assertFalse(o.hit)
            self.assertEqual(o.realized_direction, Direction.DOWN)

    def test_not_matured(self):
        with tempfile.TemporaryDirectory() as d:
            o = self.mk(d, self.rows()).evaluate(T0 + timedelta(minutes=10))[0]
            self.assertEqual((o.scored, o.reason), (False, Unscored.NOT_MATURED))

    def test_missing_data_unscored_not_guessed(self):
        with tempfile.TemporaryDirectory() as d:
            rows = [r for r in self.rows() if r[0] != "SPY"]
            o = self.mk(d, rows).evaluate(T0 + timedelta(hours=2))[0]
            self.assertEqual(o.reason, Unscored.NO_BENCHMARK_DATA)

    def test_availability_time_respected(self):
        with tempfile.TemporaryDirectory() as d:
            ev = self.mk(d, self.rows())
            # as_of before the end observation became available cannot score it
            self.assertFalse(ev.evaluate(T0 + timedelta(minutes=30))[0].scored)

    def test_corporate_action_unscored(self):
        with tempfile.TemporaryDirectory() as d:
            ev = self.mk(d, self.rows())
            ev.corporate_actions = lambda inst, a, b: inst == "AAA"
            self.assertEqual(ev.evaluate(T0 + timedelta(hours=2))[0].reason, Unscored.CORPORATE_ACTION_IN_WINDOW)

    def test_second_source_cross_check(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as d2:
            ev = self.mk(d, self.rows())
            ev2 = self.rows()
            feed(d2, ev2, provider="SYNTH_B")
            ev.second_source = ObservationReader(d2, L)
            o = ev.evaluate(T0 + timedelta(hours=2))[0]
            self.assertEqual((o.cross_check, o.independence), ("MATCH", "TWO_SOURCES"))

    def test_second_source_disagreement_unscored(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as d2:
            ev = self.mk(d, self.rows())
            feed(d2, self.rows(inst_end=120.0), provider="SYNTH_B")
            ev.second_source = ObservationReader(d2, L)
            self.assertEqual(ev.evaluate(T0 + timedelta(hours=2))[0].reason, Unscored.SOURCE_DISAGREEMENT)

    def test_same_provider_not_independent(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as d2:
            ev = self.mk(d, self.rows())
            feed(d2, self.rows())
            ev.second_source = ObservationReader(d2, L)
            self.assertEqual(ev.evaluate(T0 + timedelta(hours=2))[0].cross_check, "NOT_INDEPENDENT")

    def test_evaluator_lane_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            feed(d, [])
            with self.assertRaises(ValueError):
                OutcomeEvaluator(MarketLane.IN_EQUITIES, LedgerReader(d, L), ObservationReader(d, L))

    def test_evaluator_imports_no_writers(self):
        from pathlib import Path

        import research.prediction_eval.evaluator as m

        imports = [ln for ln in Path(m.__file__).read_text().splitlines() if ln.startswith(("from ", "import "))]
        text = "\n".join(imports)
        for banned in ("PredictionLedger", "ObservationStore", "external_paper", "broker", "prediction_ledger.ledger"):
            self.assertNotIn(banned, text)

    def test_evidence_class_requires_live_and_verified_source(self):
        with tempfile.TemporaryDirectory() as d:
            outs = self.mk(d, self.rows()).evaluate(T0 + timedelta(hours=2))
            self.assertEqual(evidence_class(outs, True), "SYNTHETIC_ENGINEERING")
        with tempfile.TemporaryDirectory() as d:
            outs = self.mk(d, self.rows(), prov=DataProvenance.LIVE).evaluate(T0 + timedelta(hours=2))
            self.assertEqual(evidence_class(outs, False), "ENGINEERING_REPLAY_OR_UNVERIFIED_SOURCE")
            self.assertEqual(evidence_class(outs, True), "LIVE_DATA_SHADOW")

    def test_coverage_denominators_and_summary_insufficient(self):
        with tempfile.TemporaryDirectory() as d:
            feed(d, self.rows())
            led = PredictionLedger(d, L)
            led.record(pred(), REC)
            led.record(pred(pid="n", status=PredictionStatus.NO_SIGNAL), REC)
            led.record(pred(pid="f", status=PredictionStatus.PROVIDER_FAILED), REC)
            ev = OutcomeEvaluator(L, LedgerReader(d, L), ObservationReader(d, L))
            outs = ev.evaluate(T0 + timedelta(hours=2))
            cov = coverage_report(L, ev.ledger, outs, CoverageInputs(eligible_opportunities=10))
            self.assertEqual((cov["eligible_opportunities"], cov["predictions_generated"], cov["no_signal"],
                              cov["provider_failures"], cov["matured_scored"]), (10, 1, 1, 1, 1))
            s = summarize(L, ev.ledger, outs, min_n=30)
            self.assertEqual(s["status"], "INSUFFICIENT_SAMPLE")
            self.assertNotIn("hit_rate", s)

    def test_probabilistic_metrics_only_when_semantics_claimed(self):
        with tempfile.TemporaryDirectory() as d:
            feed(d, self.rows())
            led = PredictionLedger(d, L)
            led.record(pred(pid="a", confidence=0.7), REC)
            led.record(pred(pid="b", confidence=0.9,
                            confidence_semantics=ConfidenceSemantics.CALIBRATED_PROBABILITY_CLAIMED), REC)
            ev = OutcomeEvaluator(L, LedgerReader(d, L), ObservationReader(d, L))
            s = summarize(L, ev.ledger, ev.evaluate(T0 + timedelta(hours=2)), min_n=1)
            self.assertEqual(s["probabilistic_n"], 1)
            self.assertAlmostEqual(s["brier"], 0.01)


class MetricsAndClaims(unittest.TestCase):
    def test_wilson_and_spearman_and_brier(self):
        lo, hi = wilson_interval(5, 10)
        self.assertTrue(lo < 0.5 < hi)
        self.assertAlmostEqual(spearman_ic([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertIsNone(spearman_ic([1, 1, 1], [1, 2, 3]))
        self.assertAlmostEqual(brier([1.0, 0.0], [1, 0]), 0.0)

    def test_fact_vs_inference(self):
        idx = {"d1": T0}
        self.assertEqual(check_claim(Claim("c1", ClaimKind.FACT, "x", "d1", T0), idx), ClaimStatus.VERIFIED_AGAINST_SOURCE)
        self.assertEqual(check_claim(Claim("c2", ClaimKind.FACT, "x", "zz"), idx), ClaimStatus.UNSUPPORTED)
        self.assertEqual(check_claim(Claim("c3", ClaimKind.FACT, "x"), idx), ClaimStatus.UNSUPPORTED)
        self.assertEqual(check_claim(Claim("c4", ClaimKind.INFERENCE, "will rise", "d1"), idx), ClaimStatus.HYPOTHESIS)
        self.assertEqual(check_claim(Claim("c5", ClaimKind.FACT, "x", "d1", T0 + timedelta(days=1)), idx),
                         ClaimStatus.UNSUPPORTED)


if __name__ == "__main__":
    unittest.main()
