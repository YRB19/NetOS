"""Frozen experiment specification for the AI-vs-baseline evaluation (Slice 12).

The specification is written and hash-frozen BEFORE any confirmatory run. Every threshold is
supplied by the researcher: nothing here has a default that could be tuned after seeing results.
A frozen spec is write-once; re-freezing a different spec under the same id/version is refused,
and `verify_frozen` detects any silent change.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from research.harness.jsonio import jsonable
from shared.time.clock import ensure_utc
from shared.versioning.content_hash import hash_json_stable

SPEC_SCHEMA_VERSION = "ai-eval-spec-v1"
ARM_ORDER = (
    "TIER1", "TIER2", "TIER2_AI_DISABLED", "TIER2_AI_NEUTRAL", "TIER2_AI_ENABLED", "TIER2_AI_UNAVAILABLE",
)  # fmt: skip
# Evidence classes, weakest first. Only the last may support Outcome A.
EVIDENCE_CLASSES = (
    "SYNTHETIC_DATA_OFFLINE_FIXTURE_SIGNALS",
    "REAL_DATA_OFFLINE_FIXTURE_SIGNALS",
    "REAL_DATA_RETROSPECTIVE_PROVIDER_SIGNALS",
    "REAL_DATA_LIVE_CAPTURED_PROVIDER_SIGNALS",
)
CONFIRMATORY_GRADE = "REAL_DATA_LIVE_CAPTURED_PROVIDER_SIGNALS"


class SpecError(ValueError):
    pass


class SpecTamperedError(SpecError):
    pass


def _dec(v: str, name: str) -> Decimal:
    try:
        d = Decimal(v)
    except (InvalidOperation, TypeError) as e:
        raise SpecError(f"{name} is not a decimal string: {v!r}") from e
    if not d.is_finite():
        raise SpecError(f"{name} must be finite")
    return d


@dataclass(frozen=True)
class AIEvaluationSpec:
    spec_id: str
    version: int
    hypothesis: str
    null_hypothesis: str
    alternative_hypothesis: str
    primary_metric: str  # fixed: see PRIMARY_METRIC
    secondary_metrics: tuple[str, ...]
    dataset_id: str
    dataset_version: str
    evidence_class_declared: str  # what the data + signals actually are; never inflated
    universe_versions: tuple[str, ...]
    development_window: tuple[datetime, datetime]
    configuration_selection_window: tuple[datetime, datetime]
    confirmatory_window: tuple[datetime, datetime]
    rebalance_frequency: str
    cost_schedule_version: str
    strategy_config: dict
    ai_provider: str
    ai_model_requested: str
    prompt_template_id: str
    prompt_hash: str
    output_schema_version: str
    adjustment_config: dict
    adjustment_magnitudes_tested: tuple[str, ...]  # max_delta values; each counts as a comparison
    random_seed: int
    bootstrap_resamples: int
    bootstrap_block_length: int
    confidence_level: str  # family-wise, e.g. "0.95"
    exclusion_criteria: tuple[str, ...]
    statistical_procedure: str
    # --- acceptance / rejection thresholds (researcher-supplied; no defaults) ---
    min_economic_effect: str  # minimum net-return difference (AI - Tier-2) counted as meaningful
    max_drawdown_regression: str  # max allowed increase in max drawdown (AI - Tier-2)
    max_cost_increase_fraction: str  # max allowed relative increase in total costs
    min_signal_coverage: str  # min fraction of BUY/SELL candidates with a valid, eligible signal
    min_valid_signals: int
    min_cycles: int  # minimum decision cycles for adequate power
    frozen_at_or_before: datetime | None = None

    def validate(self) -> list[str]:
        errs: list[str] = []
        for n in ("spec_id", "hypothesis", "null_hypothesis", "alternative_hypothesis", "dataset_id",
                  "dataset_version", "cost_schedule_version", "ai_provider", "ai_model_requested",
                  "prompt_template_id", "prompt_hash", "output_schema_version", "statistical_procedure",
                  "rebalance_frequency"):  # fmt: skip
            v = getattr(self, n)
            if not isinstance(v, str) or not v.strip():
                errs.append(f"{n} must be a non-empty string")
        if self.primary_metric != PRIMARY_METRIC:
            errs.append(f"primary_metric must be {PRIMARY_METRIC!r}")
        if self.evidence_class_declared not in EVIDENCE_CLASSES:
            errs.append(f"evidence_class_declared must be one of {EVIDENCE_CLASSES}")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            errs.append("version must be an integer >= 1")
        if not self.universe_versions:
            errs.append("universe_versions must not be empty")
        if not self.exclusion_criteria:
            errs.append("exclusion_criteria must be declared before the run")
        wins = (("development_window", self.development_window),
                ("configuration_selection_window", self.configuration_selection_window),
                ("confirmatory_window", self.confirmatory_window))  # fmt: skip
        for n, (a, b) in wins:
            if a > b:
                errs.append(f"{n} start is after end")
        # leakage between development, selection and confirmatory periods
        (d0, d1), (s0, s1), (c0, c1) = (w for _, w in wins)
        if not (d1 < s0 and s1 < c0):
            errs.append("windows must be strictly ordered and non-overlapping: "
                        "development < configuration-selection < confirmatory")  # fmt: skip
        try:
            conf = _dec(self.confidence_level, "confidence_level")
            if not (Decimal("0.5") < conf < Decimal(1)):
                errs.append("confidence_level must be within (0.5, 1)")
            if _dec(self.min_economic_effect, "min_economic_effect") < 0:
                errs.append("min_economic_effect must be >= 0")
            if _dec(self.max_drawdown_regression, "max_drawdown_regression") < 0:
                errs.append("max_drawdown_regression must be >= 0")
            if _dec(self.max_cost_increase_fraction, "max_cost_increase_fraction") < 0:
                errs.append("max_cost_increase_fraction must be >= 0")
            cov = _dec(self.min_signal_coverage, "min_signal_coverage")
            if not (Decimal(0) <= cov <= Decimal(1)):
                errs.append("min_signal_coverage must be within [0, 1]")
            for m in self.adjustment_magnitudes_tested:
                _dec(m, "adjustment_magnitudes_tested")
        except SpecError as e:
            errs.append(str(e))
        for n in ("random_seed", "bootstrap_resamples", "bootstrap_block_length", "min_valid_signals", "min_cycles"):
            v = getattr(self, n)
            if isinstance(v, bool) or not isinstance(v, int) or (n != "random_seed" and v < 1):
                errs.append(f"{n} must be an integer{' >= 1' if n != 'random_seed' else ''}")
        if not self.adjustment_magnitudes_tested:
            errs.append("adjustment_magnitudes_tested must list at least the configured max_delta")
        return errs

    @property
    def n_comparisons(self) -> int:
        """Confirmatory comparisons that share the family-wise error budget (one per tested magnitude)."""
        return max(1, len(self.adjustment_magnitudes_tested))

    def payload(self) -> dict:
        p = jsonable(self)
        assert isinstance(p, dict)
        p["__schema__"] = SPEC_SCHEMA_VERSION
        return p

    def spec_hash(self) -> str:
        return hash_json_stable(self.payload())


PRIMARY_METRIC = "net_return_difference_ai_minus_tier2"


class FrozenSpecRegistry:
    """Write-once store of frozen specs (`<root>/ai_eval_specs/<id>.v<N>.json`)."""

    def __init__(self, root: Path | str) -> None:
        self.dir = Path(root) / "ai_eval_specs"

    def _path(self, spec: AIEvaluationSpec) -> Path:
        return self.dir / f"{spec.spec_id}.v{spec.version}.json"

    def freeze(self, spec: AIEvaluationSpec, at: datetime) -> str:
        errs = spec.validate()
        if errs:
            raise SpecError("; ".join(errs))
        at = ensure_utc(at)
        p = self._path(spec)
        h = spec.spec_hash()
        if p.exists():
            existing = json.loads(p.read_text(encoding="utf-8"))
            if existing["spec_hash"] != h:
                raise SpecTamperedError(f"{spec.spec_id} v{spec.version} is already frozen with a different spec")
            return h  # idempotent
        self.dir.mkdir(parents=True, exist_ok=True)
        body = json.dumps({"spec_hash": h, "frozen_at": at.isoformat(), "spec": spec.payload()},
                          sort_keys=True, indent=2, default=str)  # fmt: skip
        fd, tmp = tempfile.mkstemp(dir=self.dir)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, p)
        return h

    def verify_frozen(self, spec: AIEvaluationSpec, started_at: datetime) -> str:
        """Raise unless this exact spec was frozen no later than `started_at`."""
        p = self._path(spec)
        if not p.exists():
            raise SpecTamperedError("spec is not frozen: confirmatory evaluation refused")
        rec = json.loads(p.read_text(encoding="utf-8"))
        if rec["spec_hash"] != spec.spec_hash():
            raise SpecTamperedError("spec differs from the frozen version (silent change refused)")
        if datetime.fromisoformat(rec["frozen_at"]) > ensure_utc(started_at):
            raise SpecTamperedError("spec was frozen AFTER the evaluation started")
        return rec["spec_hash"]
