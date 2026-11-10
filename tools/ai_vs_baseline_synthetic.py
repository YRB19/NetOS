"""SYNTHETIC scenario for the Slice 12 evaluation harness (infrastructure verification only).

Builds on the repository's synthetic test fixtures (weekly bars, 10 synthetic ISINs). Every disclosure and
every AI signal here is generated locally: the signals are a seeded pseudo-random label that carries NO
information about returns, by construction. Results from this scenario say nothing about markets or models.
Run: `python3 -m tools.ai_vs_baseline_synthetic <output_root>`.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from data.adapters.disclosure_local_import import InstrumentMap, LocalDisclosureImport
from data.disclosures.store import ContextConfig, DisclosureStore
from intelligence.llm_component.model_version import CutoffBasis, CutoffDeclaration
from intelligence.llm_component.overlay import ConfidenceAdjustmentConfig
from intelligence.llm_component.prompt import PROMPT_TEMPLATE_ID, prompt_hash
from intelligence.llm_component.provider import StubProvider, stub_signal
from intelligence.llm_component.schema import OUTPUT_SCHEMA_VERSION
from model_providers.replay import RecordingProvider, ReplayProvider
from research.ai_eval.spec import AIEvaluationSpec, FrozenSpecRegistry
from tests.unit._pipeline_helpers import HIST_START, ISINS, TEST_START, config, pipeline, tier2, universe, weekly_bars
from tools.ai_vs_baseline import Scenario, run_evaluation

INGEST_DELAY = timedelta(hours=1)
CLOCK_T = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
CUTOFF = CutoffDeclaration(CutoffBasis.PROVIDER_DOCUMENTED, datetime(2023, 6, 30, tzinfo=UTC),
                           "SYNTHETIC TEST DECLARATION - not a real provider statement")  # fmt: skip
SEED = 20260901


def synthetic_disclosures(weeks: int = 78) -> DisclosureStore:
    """One synthetic announcement per ISIN per week, each ingested INGEST_DELAY after its own publication."""
    st = DisclosureStore()
    imap = InstrumentMap({i: i for i in ISINS}, {("NSE", f"S{k}"): i for k, i in enumerate(ISINS)})
    tmp = Path(tempfile.mkdtemp())
    for k in range(weeks):
        pub_dt = HIST_START + timedelta(weeks=k) - timedelta(days=2)
        items = [{"source_document_id": f"SYN-{k}-{i}", "exchange": "NSE", "symbol": f"S{i}", "isin": isin,
                  "published_at": pub_dt.isoformat(), "title": "Synthetic announcement",
                  "text": f"SYNTHETIC announcement {k} for {isin}."} for i, isin in enumerate(ISINS)]  # fmt: skip
        p = tmp / f"d{k}.jsonl"
        p.write_text("\n".join(map(json.dumps, items)), encoding="utf-8")
        LocalDisclosureImport(p, clock=lambda d=pub_dt + INGEST_DELAY: d).load_into(st, imap)
    return st


def _responder(mode: str | None):
    def r(req):  # noqa: ANN001, ANN202
        ids = tuple(ln.split('"')[1] for ln in req.user.split("\n") if ln.startswith("<document id="))
        ctx = type("C", (), {"document_ids": ids})()
        if mode:
            return json.dumps(stub_signal(ctx, mode))
        h = hashlib.sha256(f"{SEED}|{req.user}".encode()).digest()[0] % 3  # uninformative by construction
        return json.dumps(stub_signal(ctx, ("POSITIVE", "NEGATIVE", "NEUTRAL")[h]))

    return r


def build_scenario(captures_jsonl: str | None = None):
    """Returns (scenario, recording_provider_or_None). With captures_jsonl, signals come ONLY from the recording."""
    if captures_jsonl is None:
        rec = RecordingProvider(StubProvider(_responder(None)))
        enabled = rec
    else:
        rec, enabled = None, ReplayProvider.from_jsonl(captures_jsonl)
    scn = Scenario(
        data_origin="SYNTHETIC", evidence_label="SYNTHETIC_AI_EVAL", bars=weekly_bars(), universe=universe(),
        run_config=config(), make_pipeline=lambda b: pipeline(b), make_tier1=lambda: _tier1(), make_tier2=lambda: tier2(0.3),
        disclosures=synthetic_disclosures(), context_config=ContextConfig(lookback_days=7), model_cutoff=CUTOFF,
        enabled_provider=enabled, neutral_provider=StubProvider(_responder("NEUTRAL")), clock=lambda: CLOCK_T,
    )  # fmt: skip
    return scn, rec


def _tier1():
    from tests.unit._pipeline_helpers import ContextFeatureBuilder
    from intelligence.baseline.tier1_equal_weight import Tier1EqualWeightBuyHold

    return Tier1EqualWeightBuyHold(), ContextFeatureBuilder()


def build_spec(scn: Scenario, *, version: int = 1, **over) -> AIEvaluationSpec:
    t2, _ = scn.make_tier2()
    args = dict(
        spec_id="slice12-synthetic-ai-vs-tier2", version=version,
        hypothesis="SYNTHETIC infrastructure check: the bounded AI confidence adjustment yields a net-of-cost return "
                   "difference vs Tier-2 whose adjusted confidence interval lies above the minimum economic effect.",
        null_hypothesis="The AI component does not provide statistically or economically meaningful incremental value over Tier-2.",
        alternative_hypothesis="The AI-augmented Tier-2 has a higher net return than Tier-2 by more than the minimum economic effect.",
        primary_metric="net_return_difference_ai_minus_tier2",
        secondary_metrics=("max_drawdown", "total_costs", "turnover_to_capital", "cycle_sharpe", "incremental_trades"),
        dataset_id="synthetic-weekly-bars-v1", dataset_version="repository synthetic fixture",
        evidence_class_declared="SYNTHETIC_DATA_OFFLINE_FIXTURE_SIGNALS", universe_versions=("synthetic-10-isin-universe",),
        development_window=(HIST_START, datetime(2025, 12, 31, 10, 0, tzinfo=UTC)),
        configuration_selection_window=(datetime(2026, 1, 1, 10, 0, tzinfo=UTC), TEST_START - timedelta(days=2)),
        confirmatory_window=(TEST_START, TEST_START + timedelta(days=150)), rebalance_frequency="monthly (Tier-2 default)",
        cost_schedule_version=scn.run_config.cost_schedule_version, strategy_config=t2.config.payload(),
        ai_provider="STUB", ai_model_requested="stub-model-v1", prompt_template_id=PROMPT_TEMPLATE_ID,
        prompt_hash=prompt_hash(), output_schema_version=OUTPUT_SCHEMA_VERSION,
        adjustment_config=ConfidenceAdjustmentConfig().payload(),
        adjustment_magnitudes_tested=("0.05", "0.1", "0.2"), random_seed=SEED, bootstrap_resamples=2000,
        bootstrap_block_length=3, confidence_level="0.95",
        exclusion_criteria=("any blocking point-in-time/provenance failure excludes that signal; nothing is repaired",),
        statistical_procedure="paired circular block bootstrap of per-cycle return differences, Bonferroni-adjusted level",
        min_economic_effect="0.002", max_drawdown_regression="0.01", max_cost_increase_fraction="0.10",  # EXAMPLE values
        min_signal_coverage="0.8", min_valid_signals=30, min_cycles=26,
    )  # fmt: skip
    args.update(over)
    return AIEvaluationSpec(**args)


def main(root: str) -> None:
    scn, rec = build_scenario()
    spec = build_spec(scn)
    FrozenSpecRegistry(root).freeze(spec, datetime(2026, 9, 1, 11, 0, tzinfo=UTC))
    art = run_evaluation(root, spec, scn, started_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC))
    cap = Path(root) / "ai_eval_reports" / f"{art['evaluation_run_id']}.captures.jsonl"
    cap.write_text(rec.dump_jsonl(), encoding="utf-8")
    print(json.dumps({"outcome": art["decision"]["outcome"], "evidence_class": art["evidence_class"],
                      "artifact_hash": art["artifact_hash"], **art["_paths"], "captures": str(cap)}, indent=2))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
