"""Slice 12 - frozen spec + statistics. SYNTHETIC inputs; infrastructure verification only."""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from research.ai_eval.spec import PRIMARY_METRIC, FrozenSpecRegistry, SpecError, SpecTamperedError
from research.ai_eval.stats import (
    adjusted_confidence_level,
    block_bootstrap_mean_ci,
    cycle_returns,
    paired_differences,
)
from tools.ai_vs_baseline_synthetic import build_scenario, build_spec

T = datetime(2026, 9, 1, 11, 0, tzinfo=UTC)


def curve(vals):
    return [{"timestamp": f"t{i:03d}", "equity": v} for i, v in enumerate(vals)]


class SpecValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scn, _ = build_scenario()
        cls.spec = build_spec(cls.scn)

    def test_valid_spec_has_no_errors_and_stable_hash(self):
        self.assertEqual(self.spec.validate(), [])
        self.assertEqual(self.spec.spec_hash(), build_spec(self.scn).spec_hash())

    def test_primary_metric_cannot_be_changed(self):
        errs = dataclasses.replace(self.spec, primary_metric="sharpe").validate()
        self.assertTrue(any(PRIMARY_METRIC in e for e in errs))

    def test_overlapping_windows_are_rejected(self):
        s = dataclasses.replace(self.spec, configuration_selection_window=(self.spec.development_window[0], self.spec.confirmatory_window[0]))
        self.assertTrue(any("non-overlapping" in e for e in s.validate()))

    def test_confirmatory_before_selection_is_rejected(self):
        s = dataclasses.replace(self.spec, confirmatory_window=(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC)))
        self.assertTrue(s.validate())

    def test_missing_exclusion_criteria_and_bad_thresholds(self):
        self.assertTrue(dataclasses.replace(self.spec, exclusion_criteria=()).validate())
        self.assertTrue(dataclasses.replace(self.spec, min_economic_effect="-1").validate())
        self.assertTrue(dataclasses.replace(self.spec, confidence_level="1.2").validate())
        self.assertTrue(dataclasses.replace(self.spec, min_economic_effect="NaN").validate())
        self.assertTrue(dataclasses.replace(self.spec, evidence_class_declared="REAL").validate())

    def test_n_comparisons_follows_tested_magnitudes(self):
        self.assertEqual(self.spec.n_comparisons, 3)


class Freezing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scn, _ = build_scenario()
        cls.spec = build_spec(cls.scn)

    def test_unfrozen_spec_is_refused(self):
        with self.assertRaises(SpecTamperedError):
            FrozenSpecRegistry(tempfile.mkdtemp()).verify_frozen(self.spec, T)

    def test_freeze_verify_and_idempotent(self):
        reg = FrozenSpecRegistry(tempfile.mkdtemp())
        h = reg.freeze(self.spec, T)
        self.assertEqual(reg.freeze(self.spec, T + timedelta(days=1)), h)
        self.assertEqual(reg.verify_frozen(self.spec, T + timedelta(hours=1)), h)

    def test_changed_spec_cannot_be_refrozen_or_verified(self):
        reg = FrozenSpecRegistry(tempfile.mkdtemp())
        reg.freeze(self.spec, T)
        changed = dataclasses.replace(self.spec, min_economic_effect="0.0")
        with self.assertRaises(SpecTamperedError):
            reg.freeze(changed, T)
        with self.assertRaises(SpecTamperedError):
            reg.verify_frozen(changed, T + timedelta(hours=1))

    def test_spec_frozen_after_evaluation_start_is_refused(self):
        reg = FrozenSpecRegistry(tempfile.mkdtemp())
        reg.freeze(self.spec, T + timedelta(days=1))
        with self.assertRaises(SpecTamperedError):
            reg.verify_frozen(self.spec, T)

    def test_invalid_spec_cannot_be_frozen(self):
        with self.assertRaises(SpecError):
            FrozenSpecRegistry(tempfile.mkdtemp()).freeze(dataclasses.replace(self.spec, exclusion_criteria=()), T)


class Statistics(unittest.TestCase):
    def test_bonferroni_adjustment(self):
        self.assertEqual(adjusted_confidence_level(Decimal("0.95"), 1), Decimal("0.95"))
        self.assertEqual(adjusted_confidence_level(Decimal("0.95"), 5), Decimal("0.99"))
        with self.assertRaises(ValueError):
            adjusted_confidence_level(Decimal("0.95"), 0)

    def test_identical_paths_are_zero_variance_not_significant(self):
        ci = block_bootstrap_mean_ci([0.0] * 30, confidence=Decimal("0.95"), resamples=200, block_length=3, seed=1)
        self.assertEqual(ci.status, "ZERO_VARIANCE_IDENTICAL_PATHS")
        self.assertEqual((ci.lower, ci.upper), (0.0, 0.0))

    def test_insufficient_sample(self):
        self.assertEqual(block_bootstrap_mean_ci([0.1], confidence=Decimal("0.95"), resamples=100, block_length=1, seed=1).status, "INSUFFICIENT_SAMPLE")

    def test_bootstrap_is_deterministic_and_brackets_the_mean(self):
        xs = [0.01 * ((i * 7) % 5 - 2) + 0.002 for i in range(60)]
        a = block_bootstrap_mean_ci(xs, confidence=Decimal("0.95"), resamples=500, block_length=4, seed=7)
        b = block_bootstrap_mean_ci(xs, confidence=Decimal("0.95"), resamples=500, block_length=4, seed=7)
        c = block_bootstrap_mean_ci(xs, confidence=Decimal("0.95"), resamples=500, block_length=4, seed=8)
        self.assertEqual(a, b)
        self.assertNotEqual((a.lower, a.upper), (c.lower, c.upper))
        self.assertLessEqual(a.lower, a.mean)
        self.assertGreaterEqual(a.upper, a.mean)

    def test_clear_positive_effect_has_positive_lower_bound(self):
        xs = [0.01 + 0.001 * (i % 3) for i in range(40)]
        self.assertGreater(block_bootstrap_mean_ci(xs, confidence=Decimal("0.95"), resamples=500, block_length=3, seed=3).lower, 0)

    def test_paired_differences_and_misalignment(self):
        a, b = curve([100, 110, 121]), curve([100, 105, 110])
        d = paired_differences(a, b)
        self.assertEqual(len(d), 2)
        self.assertAlmostEqual(d[0], 0.10 - 0.05)
        self.assertEqual(len(cycle_returns(a)), 2)
        with self.assertRaises(ValueError):
            paired_differences(a, curve([100, 105]))


if __name__ == "__main__":
    unittest.main()
