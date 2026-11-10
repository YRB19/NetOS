"""Slice 12 - outcome classifier, attribution, replay provider, artifact hygiene. SYNTHETIC fixtures."""

from __future__ import annotations

import dataclasses
import json
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from intelligence.llm_component.prompt import render_request
from intelligence.llm_component.provider import ProviderResponse, ProviderUnavailable, StubProvider
from model_providers.replay import RecordingProvider, ReplayProvider, request_key
from research.ai_eval.attribution import canonical_trades, incremental_trades, information_content
from research.ai_eval.decision import DecisionInputs, classify_outcome
from research.ai_eval.report import SecretLeakError, assert_no_secrets, finalize_artifact
from research.ai_eval.spec import CONFIRMATORY_GRADE
from tools.ai_vs_baseline_synthetic import build_scenario, build_spec
from tests.unit._slice11_helpers import context, item, load

SCN, _ = build_scenario()
SPEC = build_spec(SCN)
GOOD = DecisionInputs(evidence_class=CONFIRMATORY_GRADE, effective_confirmatory=True, integrity_breaches=0, n_valid_signals=100,
                      signal_coverage=0.95, n_cycles=60, arm_paths_identical=False, incremental_trades=4, delta_net_return=0.01,
                      ci_lower=0.005, ci_upper=0.015, ci_status="OK", drawdown_regression=0.0, cost_increase_fraction=0.01)  # fmt: skip


def out(**kw):
    return classify_outcome(SPEC, dataclasses.replace(GOOD, **kw)).outcome


class DecisionRules(unittest.TestCase):
    def test_a_requires_every_condition(self):
        self.assertEqual(out(), "A")

    def test_integrity_breach_is_harm_regardless_of_evidence_class(self):
        self.assertEqual(out(integrity_breaches=1, evidence_class="SYNTHETIC_DATA_OFFLINE_FIXTURE_SIGNALS"), "D")

    def test_weak_evidence_class_caps_at_b_even_with_great_numbers(self):
        for ec in ("SYNTHETIC_DATA_OFFLINE_FIXTURE_SIGNALS", "REAL_DATA_OFFLINE_FIXTURE_SIGNALS", "REAL_DATA_RETROSPECTIVE_PROVIDER_SIGNALS"):
            self.assertEqual(out(evidence_class=ec), "B")
        self.assertEqual(out(effective_confirmatory=False), "B")

    def test_power_and_coverage_thresholds(self):
        self.assertEqual(out(n_valid_signals=1), "B")
        self.assertEqual(out(n_cycles=3), "B")
        self.assertEqual(out(signal_coverage=0.1), "B")
        self.assertEqual(out(signal_coverage=None), "B")

    def test_identical_paths_with_no_incremental_trades_is_c(self):
        self.assertEqual(out(arm_paths_identical=True, incremental_trades=0), "C")

    def test_harm_criteria(self):
        self.assertEqual(out(ci_lower=-0.02, ci_upper=-0.01, delta_net_return=-0.015), "D")
        self.assertEqual(out(drawdown_regression=0.5), "D")
        self.assertEqual(out(cost_increase_fraction=0.9), "D")

    def test_straddling_and_small_effects(self):
        self.assertEqual(out(ci_lower=-0.01, ci_upper=0.02), "B")
        self.assertEqual(out(ci_lower=-0.001, ci_upper=0.001), "C")
        self.assertEqual(out(ci_status="ZERO_VARIANCE_IDENTICAL_PATHS"), "B")

    def test_rule_trace_records_the_frozen_spec_hash(self):
        self.assertIn(SPEC.spec_hash()[:16], classify_outcome(SPEC, GOOD).rule_trace[0])


class Attribution(unittest.TestCase):
    def test_identical_trades_ignoring_identity_and_ai_provenance_keys(self):
        a = [{"instrument_id": "X", "side": "BUY", "quantity": 5, "price": "10", "order_id": "o1", "candidate_id": "c1"}]
        b = [{"instrument_id": "X", "side": "BUY", "quantity": 5, "price": "10", "order_id": "o9", "candidate_id": "c9"}]
        self.assertTrue(incremental_trades(a, b)["identical"])
        self.assertEqual(canonical_trades(a), canonical_trades(b))

    def test_difference_is_counted_both_ways(self):
        a = [{"instrument_id": "X", "side": "BUY", "quantity": 5}]
        b = [{"instrument_id": "X", "side": "BUY", "quantity": 6}, {"instrument_id": "Y", "side": "BUY", "quantity": 1}]
        r = incremental_trades(a, b)
        self.assertEqual((r["trades_only_in_ai_arm"], r["trades_only_in_baseline_arm"], r["identical"]), (2, 1, False))

    def test_information_content_known_answer_and_insufficient_sample(self):
        t0, t1, t2 = (datetime(2026, 4, 1, 10, tzinfo=UTC) + timedelta(days=7 * k) for k in range(3))
        bars = [SimpleNamespace(instrument_id="X", timestamp=t + timedelta(days=1), open=o) for t, o in ((t0, 100.0), (t1, 110.0), (t2, 99.0))]
        rows = [{"instrument_id": "X", "decision_timestamp": t0, "direction": 1, "applied": True},
                {"instrument_id": "X", "decision_timestamp": t1, "direction": -1, "applied": True}]  # fmt: skip
        from decimal import Decimal

        r = information_content(rows, bars, [t0, t1, t2], confidence=Decimal("0.95"), resamples=100, seed=1, min_n=5)
        self.assertEqual(r["n_influenced"], 2)
        self.assertEqual(r["hit_rate_direction_aligned"], 1.0)  # +10% with long call, -10% with short call: both aligned
        self.assertEqual(r["direction_aligned_return"]["status"], "INSUFFICIENT_SAMPLE")


class ReplayProviderTests(unittest.TestCase):
    def setUp(self):
        store, _ = load([item()])
        self.req = render_request(context(store))
        self.inner = StubProvider(lambda r: '{"ok": true}')

    def test_record_then_replay_without_inner_provider(self):
        rec = RecordingProvider(self.inner)
        r1 = rec.complete(self.req)
        rp = ReplayProvider.from_jsonl(rec.dump_jsonl())
        r2 = rp.complete(self.req)
        self.assertEqual((r1.text, r1.model_identifier), (r2.text, r2.model_identifier))
        self.assertEqual(rp.provider_name, "STUB")  # replay never relabels the original provider
        self.assertFalse(rp.is_real_provider)

    def test_unrecorded_request_never_invents_a_response(self):
        rp = ReplayProvider({}, provider_name="X", model_identifier="m", is_real_provider=True)
        with self.assertRaises(ProviderUnavailable):
            rp.complete(self.req)

    def test_provider_errors_propagate_and_are_not_captured(self):
        class Boom:
            provider_name, model_identifier = "B", "m"

            def complete(self, r):  # noqa: ANN001
                raise ProviderUnavailable("down")

        rec = RecordingProvider(Boom())
        with self.assertRaises(ProviderUnavailable):
            rec.complete(self.req)
        self.assertEqual(rec.captures, {})
        self.assertIsInstance(request_key(self.req), str)
        self.assertIsInstance(ProviderResponse, type)


class ArtifactHygiene(unittest.TestCase):
    def test_credential_like_keys_and_values_are_refused(self):
        for bad in ({"api_key": "abc"}, {"x": {"Authorization": "Bearer abcdefghijklmnop"}}, {"note": "key sk-abcdefghijklmnopqrstuv"},
                    {"nested": [{"password": "p"}]}):  # fmt: skip
            with self.assertRaises(SecretLeakError):
                assert_no_secrets(bad)
        assert_no_secrets({"api_key": None, "usage_input_units": 5, "note": "clean"})

    def test_artifact_hash_is_deterministic_and_content_bound(self):
        a, b = finalize_artifact({"x": 1}), finalize_artifact({"x": 1})
        self.assertEqual(a["artifact_hash"], b["artifact_hash"])
        self.assertNotEqual(a["artifact_hash"], finalize_artifact({"x": 2})["artifact_hash"])
        json.dumps(a)


if __name__ == "__main__":
    unittest.main()
