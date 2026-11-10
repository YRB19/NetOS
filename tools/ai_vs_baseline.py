"""Slice 12 orchestrator: runs the evaluation arms through the real simulated pipeline and assembles the
evaluation artifact. Lives OUTSIDE the architectural planes (like `simulation/`'s callers) because it must
touch both the research analysis layer and the execution simulation. Nothing imports this module.

No network: signals come from the provider object supplied by the caller (a RecordingProvider around a
real/stub provider on a recording run; a ReplayProvider on a reproduction run).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from data.disclosures.store import ContextConfig, DisclosureStore
from domain.models.enums import Action
from intelligence.llm_component.model_version import CutoffDeclaration, build_model_version
from intelligence.llm_component.overlay import ConfidenceAdjustmentConfig, DisclosureOverlayStrategy
from intelligence.llm_component.prompt import PROMPT_TEMPLATE_ID, prompt_hash
from intelligence.llm_component.provider import ProviderUnavailable
from intelligence.llm_component.schema import OUTPUT_SCHEMA_VERSION
from intelligence.llm_component.signals import SignalConfig, SignalService, SignalStore
from observability.decision_log.events import EventType as ET
from observability.decision_log.journal import InMemoryJournal
from observability.decision_log.query import JournalReader
from research.ai_eval.attribution import incremental_trades, information_content, signal_metrics
from research.ai_eval.decision import DecisionInputs, classify_outcome
from research.ai_eval.pit_audit import Provenance, applied_but_ineligible, audit_signals
from research.ai_eval.report import finalize_artifact, write_artifact
from research.ai_eval.spec import (
    CONFIRMATORY_GRADE,
    EVIDENCE_CLASSES,
    AIEvaluationSpec,
    FrozenSpecRegistry,
    SpecError,
)
from research.ai_eval.stats import (
    adjusted_confidence_level,
    block_bootstrap_mean_ci,
    cycle_returns,
    paired_differences,
)
from research.contamination.model_cutoff import assess_ai_model
from research.protocol.protocol import HoldoutReusePolicy
from research.stats.pbo import compute_pbo
from research.trials.holdout import HoldoutRegistry, HoldoutReuseError, holdout_id_for
from research.trials.ledger import TrialLedger, TrialOutcome
from research.validity.metrics import compute_extended_metrics, final_marks_from_market_data
from research.validity.service import compute_dataset_hash
from shared.costs import CostModel
from shared.time.clock import ensure_utc
from shared.versioning.content_hash import hash_json_stable
from simulation import PipelineHarness

EVALUATION_VERSION = "ai-vs-baseline-eval-v1"
AI_ARMS = ("TIER2_AI_DISABLED", "TIER2_AI_NEUTRAL", "TIER2_AI_ENABLED", "TIER2_AI_UNAVAILABLE")


class EvaluationConfigError(ValueError):
    pass


@dataclass
class Scenario:
    data_origin: str  # "SYNTHETIC" | "REAL"
    evidence_label: str
    bars: list
    universe: object
    run_config: object
    make_pipeline: Callable  # builder -> PipelineConfig
    make_tier1: Callable  # () -> (strategy, builder)
    make_tier2: Callable  # () -> (strategy, builder)
    disclosures: DisclosureStore
    context_config: ContextConfig
    model_cutoff: CutoffDeclaration
    enabled_provider: object  # provider producing the AI-ENABLED signals (stub/real/recording/replay)
    neutral_provider: object
    clock: Callable[[], datetime]
    disclosure_status_counts: dict | None = None


class _Recorder:
    def __init__(self, base) -> None:  # noqa: ANN001
        self.base = base
        self.strategy_version_id = base.strategy_version_id
        self.expected_feature_set_id = getattr(base, "expected_feature_set_id", None)
        self.seen: list = []

    def generate_candidate_trades(self, *a):  # noqa: ANN002
        out = self.base.generate_candidate_trades(*a)
        self.seen.extend(out)
        return out


class _Unavailable:
    provider_name, model_identifier, is_real_provider = "UNAVAILABLE_SIMULATION", "none", False

    def complete(self, request):  # noqa: ANN001, ANN201
        raise ProviderUnavailable("simulated provider outage")


def _f(x) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _mv(m: dict, k: str) -> float | None:
    return _f((m.get(k) or {}).get("value"))


def _run(scn: Scenario, strat, builder, label: str):  # noqa: ANN001, ANN202
    box: dict = {}

    def jf(rid):  # noqa: ANN001, ANN202
        box["j"] = InMemoryJournal(rid)
        return box["j"]

    res = PipelineHarness().run(scn.run_config, strat, scn.bars, [scn.universe], scn.make_pipeline(builder),
                                journal_factory=jf, evidence_class=scn.evidence_label)  # fmt: skip
    return res, JournalReader.from_journal(box["j"]), box["j"]


def _close_at(bars_by_inst: dict, inst: str, ts: datetime) -> float | None:
    last = None
    for b in bars_by_inst.get(inst, ()):
        if ensure_utc(b.timestamp) <= ts:
            last = float(b.close)
        else:
            break
    return last


def _holding_days(fills: list[dict]) -> float | None:
    lots: dict[str, list[list]] = {}
    spans: list[float] = []
    for f in sorted(fills, key=lambda f: f["fill_timestamp"]):
        i, q, t = f["instrument_id"], int(f["quantity"]), f["fill_timestamp"]
        if f["side"] == "BUY":
            lots.setdefault(i, []).append([q, t])
        else:
            rem = q
            while rem > 0 and lots.get(i):
                lot = lots[i][0]
                take = min(rem, lot[0])
                spans.append((t - lot[1]).total_seconds() / 86400.0 * take)
                lot[0] -= take
                rem -= take
                if lot[0] == 0:
                    lots[i].pop(0)
    qty = sum(int(f["quantity"]) for f in fills if f["side"] == "SELL")
    return (sum(spans) / qty) if spans and qty else None


def arm_metrics(res, scn: Scenario) -> dict:  # noqa: ANN001
    run = res.run
    ext = compute_extended_metrics(run, cost_model=CostModel(), final_marks=final_marks_from_market_data(run, scn.bars),
                                   assumptions=None, baseline=None, unique_trial_count=1)  # fmt: skip
    rets = [r for _, r in cycle_returns(run.equity_curve)]
    n = len(rets)
    mean = math.fsum(rets) / n if n else None
    sd = math.sqrt(math.fsum((r - mean) ** 2 for r in rets) / (n - 1)) if n > 1 and mean is not None else None
    peak, longest, cur = None, 0, 0
    for p in run.equity_curve:
        eq = float(p["equity"])
        peak = eq if peak is None or eq > peak else peak
        cur = cur + 1 if eq < peak else 0
        longest = max(longest, cur)
    by_inst: dict[str, list] = {}
    for b in scn.bars:
        by_inst.setdefault(b.instrument_id, []).append(b)
    maxw = 0.0
    for p in run.equity_curve:
        eq = float(p["equity"])
        ts = ensure_utc(p["timestamp"])
        for pos in p.get("positions", ()):
            c = _close_at(by_inst, pos["instrument_id"], ts)
            if c and eq > 0:
                maxw = max(maxw, int(pos["quantity"]) * c / eq)
    fills = list(res.broker_fills)
    return {
        "net_return": _mv(ext, "net_return"), "net_pnl": _mv(ext, "net_pnl"), "gross_pnl": _mv(ext, "gross_pnl"),
        "total_costs": _mv(ext, "total_actual_costs"), "cost_drag": _mv(ext, "cost_drag"),
        "turnover_to_capital": _mv(ext, "turnover_to_capital"), "transactions": int(_mv(ext, "transactions") or 0),
        "max_drawdown": _mv(ext, "max_drawdown"), "average_exposure": _mv(ext, "average_exposure"),
        "periodic_volatility": _mv(ext, "periodic_volatility"),
        "annualised_return": None, "annualised_volatility": None, "calmar": None,
        "annualisation_note": "UNSUPPORTED: irregular cycle spacing and short sample; no annualisation justification supplied",
        "cycle_sharpe": (mean / sd) if mean is not None and sd else None,
        "downside_deviation": math.sqrt(math.fsum(min(r, 0.0) ** 2 for r in rets) / n) if n else None,
        "worst_cycle_return": min(rets) if rets else None, "drawdown_duration_cycles": longest,
        "max_position_weight": maxw, "gross_exposure_note": "long-only: net exposure == gross exposure",
        "sector_concentration": "UNAVAILABLE (no sector classification in repository data)",
        "avg_holding_period_days": _holding_days(fills),
        "risk_vetoes": int(res.summary.get("risk_vetoes", 0)),
        "rejected_orders": int(_mv(ext, "rejected_orders") or 0), "decision_cycles": int(_mv(ext, "decision_cycles") or 0),
        "final_equity": _mv(ext, "final_equity"),
    }  # fmt: skip


def _candidate_rows(reader) -> list[dict]:  # noqa: ANN001
    return [e.payload for e in reader.events() if e.event_type is ET.CANDIDATE_EMITTED]


def _authority_checks(base_reader, base_res, arm_reader, arm_res, universe_ids: set[str]) -> dict:  # noqa: ANN001
    def key(p):  # noqa: ANN001, ANN202
        return (p["candidate_timestamp"], p["action"], str(p["size_hint"]), p["input_snapshot_id"])

    b, a = {key(p) for p in _candidate_rows(base_reader)}, {key(p) for p in _candidate_rows(arm_reader)}
    ver = lambda r: sorted((str(d["decision_timestamp"]), d["instrument_id"], str(d["verdict"])) for d in r.risk_decisions)  # noqa: E731
    return {
        "actions_and_size_hints_identical_to_baseline": a == b,
        "all_fills_within_permitted_universe": all(f["instrument_id"] in universe_ids for f in arm_res.broker_fills),
        "every_order_carries_a_risk_decision": all(o.get("risk_decision_id") for o in arm_res.orders),
        "risk_verdicts_identical_to_baseline": ver(arm_res) == ver(base_res),
        "no_order_without_candidate": all(o.get("candidate_id") for o in arm_res.orders),
    }


def run_evaluation(root: Path | str, spec: AIEvaluationSpec, scn: Scenario, *, started_at: datetime) -> dict:
    root = Path(root)
    started_at = ensure_utc(started_at)
    # ---- 0. frozen-spec gate: nothing runs against a spec that is not frozen exactly as given ----
    errs = spec.validate()
    if errs:
        raise SpecError("; ".join(errs))
    spec_hash = FrozenSpecRegistry(root).verify_frozen(spec, started_at)
    split = scn.run_config.split
    conf0, conf1 = ensure_utc(spec.confirmatory_window[0]), ensure_utc(spec.confirmatory_window[1])
    if (ensure_utc(split.test_start), ensure_utc(split.test_end)) != (conf0, conf1):
        raise EvaluationConfigError("run configuration test window differs from the frozen confirmatory window")
    if scn.run_config.cost_schedule_version != spec.cost_schedule_version:
        raise EvaluationConfigError("cost schedule differs from the frozen spec")
    t2_probe, _ = scn.make_tier2()
    if t2_probe.config.payload() != spec.strategy_config:
        raise EvaluationConfigError("Tier-2 configuration differs from the frozen spec (strategy_config)")
    cfg_payload = ConfidenceAdjustmentConfig(**{k: v for k, v in spec.adjustment_config.items()
                                                if k in ("max_delta", "min_model_confidence")})  # fmt: skip
    if cfg_payload.payload() != spec.adjustment_config:
        raise EvaluationConfigError("adjustment_config differs from ConfidenceAdjustmentConfig defaults/payload")
    if (spec.prompt_template_id, spec.prompt_hash, spec.output_schema_version) != (PROMPT_TEMPLATE_ID, prompt_hash(), OUTPUT_SCHEMA_VERSION):
        raise EvaluationConfigError("prompt template/hash or output schema differs from the frozen spec")
    if str(cfg_payload.max_delta) not in {str(Decimal(m)) for m in spec.adjustment_magnitudes_tested} and \
            str(cfg_payload.max_delta) not in spec.adjustment_magnitudes_tested:  # fmt: skip
        raise EvaluationConfigError("configured max_delta must be among adjustment_magnitudes_tested")

    # ---- 1. ledger + holdout exposure (failed arms are first-class trials) ----
    ledger, holdouts = TrialLedger(root, lambda: started_at), HoldoutRegistry(root, lambda: started_at)
    dataset_hash = compute_dataset_hash(list(scn.bars))
    hid = holdout_id_for(dataset_id=spec.dataset_id, dataset_hash=dataset_hash, universe_versions=spec.universe_versions,
                         test_start=conf0, test_end=conf1)  # fmt: skip
    findings: list[str] = []
    try:
        hstatus = holdouts.expose(holdout_id=hid, protocol_id=spec.spec_id, protocol_hash=spec_hash,
                                  run_id=f"ai_eval_{spec_hash[:12]}", mode="CONFIRMATORY",
                                  policy=HoldoutReusePolicy.DOWNGRADE_TO_NON_CONFIRMATORY).value  # fmt: skip
    except HoldoutReuseError as e:  # pragma: no cover - policy above never rejects
        raise EvaluationConfigError(str(e)) from e
    if hstatus != "UNTOUCHED":
        findings.append("HOLDOUT_REUSED: confirmatory window was exposed before; evaluation is non-confirmatory")
    base_kw = dict(protocol_id=spec.spec_id, protocol_hash=spec_hash, mode="CONFIRMATORY", dataset_hash=dataset_hash,
                   window=f"{conf0.isoformat()}..{conf1.isoformat()}", universe=",".join(sorted(spec.universe_versions)),
                   cost_schedule_version=spec.cost_schedule_version, holdout_id=hid)  # fmt: skip
    attempts: dict[str, str] = {}

    def start(arm: str) -> None:
        aid = "attempt_" + hash_json_stable([spec_hash, arm, ledger.head_hash()])[:24]
        attempts[arm] = aid
        ledger.record(strategy_id=arm, outcome=TrialOutcome.STARTED, lifecycle="START", attempt_id=aid, **base_kw)

    def finish(arm: str, outcome: TrialOutcome, reason: str | None = None) -> None:
        ledger.record(strategy_id=arm, outcome=outcome, lifecycle="TERMINAL", attempt_id=attempts[arm],
                      reason=reason, **base_kw)  # fmt: skip

    # ---- 2. baselines (Tier-1, Tier-2). Tier-2 is wrapped to record the exact candidates ----
    arm_res: dict = {}
    arm_reader: dict = {}
    failures: dict[str, str] = {}

    def run_arm(label: str, strat, builder) -> None:  # noqa: ANN001
        start(label)
        try:
            r, rd, _j = _run(scn, strat, builder, label)
        except Exception as e:  # noqa: BLE001 - recorded, never swallowed silently
            failures[label] = f"{type(e).__name__}: {e}"[:300]
            finish(label, TrialOutcome.FAILED, failures[label])
            return
        if r.run.status.value != "COMPLETED":
            failures[label] = f"run status {r.run.status.value}: {r.run.failure}"[:300]
            finish(label, TrialOutcome.FAILED, failures[label])
            return
        arm_res[label], arm_reader[label] = r, rd
        finish(label, TrialOutcome.COMPLETED)

    t1, b1 = scn.make_tier1()
    run_arm("TIER1", t1, b1)
    t2, b2 = scn.make_tier2()
    rec = _Recorder(t2)
    run_arm("TIER2", rec, b2)
    if "TIER2" not in arm_res:
        raise EvaluationConfigError(f"Tier-2 baseline failed; evaluation cannot proceed: {failures.get('TIER2')}")
    cands = rec.seen
    expected = {(c.instrument_id, ensure_utc(c.timestamp).isoformat()): c.input_snapshot_id for c in cands}
    n_trade_cands = sum(1 for c in cands if c.action is not Action.HOLD)
    trade_keys = frozenset((c.instrument_id, ensure_utc(c.timestamp).isoformat()) for c in cands if c.action is not Action.HOLD)
    decision_ts = sorted({ensure_utc(c.timestamp) for c in cands})

    # ---- 3. signals per ablation arm, then the point-in-time gate ----
    def signals_for(provider, enabled: bool = True) -> list:  # noqa: ANN001
        svc = SignalService(provider if enabled else None, SignalConfig(enabled=enabled, max_requests=10**6),
                            clock=scn.clock, sleep=lambda s: None)  # fmt: skip
        return [svc.evaluate(scn.disclosures.build_context(c.instrument_id, c.timestamp, scn.context_config,
                                                           c.input_snapshot_id)) for c in cands]  # fmt: skip

    sig_sets = {
        "TIER2_AI_ENABLED": signals_for(scn.enabled_provider),
        "TIER2_AI_NEUTRAL": signals_for(scn.neutral_provider),
        "TIER2_AI_UNAVAILABLE": signals_for(_Unavailable()),
        "TIER2_AI_DISABLED": signals_for(None, enabled=False),
    }
    docs = {d.document_id: d for d in scn.disclosures.records()}
    cutoff_dt = scn.model_cutoff.cutoff
    audits = {a: audit_signals([s.to_payload() for s in recs], documents=docs, expected_snapshot_ids=expected,
                               model_cutoff=cutoff_dt, window=(conf0, conf1), expected_schema_version=spec.output_schema_version,
                               expected_prompt_hash=spec.prompt_hash) for a, recs in sig_sets.items()}  # fmt: skip
    findings += [f"{a}: {f}" for a, au in audits.items() for f in au.run_level_findings]

    mv = build_model_version(scn.enabled_provider.provider_name, spec.ai_model_requested, scn.model_cutoff,
                             t2.strategy_version_id)  # fmt: skip

    def overlay_arm(label: str, sigs_label: str, max_delta: float, arm_name: str | None = None) -> DisclosureOverlayStrategy:
        eligible = audits[sigs_label].eligible_keys
        store = SignalStore()
        for s in sig_sets[sigs_label]:
            if (s.instrument_id, ensure_utc(s.decision_timestamp).isoformat()) in eligible:
                store.put(s)
        cfg = ConfidenceAdjustmentConfig(max_delta=max_delta, min_model_confidence=cfg_payload.min_model_confidence)
        t2b, bld = scn.make_tier2()
        ov = DisclosureOverlayStrategy(t2b, lambda i, t: store.get(i, t), cfg, mv, cutoff=scn.model_cutoff)
        run_arm(arm_name or label, ov, bld)
        return ov

    overlays: dict = {}
    for lab in AI_ARMS:
        overlays[lab] = overlay_arm(lab, lab, cfg_payload.max_delta)
    magnitude_arms: list[str] = []
    for m in spec.adjustment_magnitudes_tested:
        name = f"TIER2_AI_ENABLED@max_delta={Decimal(m).normalize():f}"
        magnitude_arms.append(name)
        overlays[name] = overlay_arm("TIER2_AI_ENABLED", "TIER2_AI_ENABLED", float(m), name)

    # ---- 4. integrity: applied-but-ineligible detection from the journal ----
    breaches: list[dict] = []
    for lab in [*AI_ARMS, *magnitude_arms]:
        if lab not in arm_reader:
            continue
        evs = [e.payload for e in arm_reader[lab].events() if e.event_type is ET.AI_SIGNAL_EVALUATED]
        key_lab = "TIER2_AI_ENABLED" if lab.startswith("TIER2_AI_ENABLED") else lab
        breaches += applied_but_ineligible(evs, audits[key_lab].eligible_keys)

    # ---- 5. metrics and comparisons ----
    metrics = {lab: arm_metrics(arm_res[lab], scn) for lab in ("TIER1", "TIER2", *AI_ARMS, *magnitude_arms) if lab in arm_res}
    t2_curve = arm_res["TIER2"].run.equity_curve
    base_fills = list(arm_res["TIER2"].broker_fills)
    inc = {lab: incremental_trades(base_fills, arm_res[lab].broker_fills) for lab in [*AI_ARMS, *magnitude_arms] if lab in arm_res}
    ablation = []
    for lab in ("TIER2", *AI_ARMS, *magnitude_arms):
        if lab not in arm_res:
            ablation.append({"arm": lab, "net_return": None, "delta_vs_tier2": None, "identical_path_to_tier2": None,
                             "status": f"FAILED: {failures.get(lab)}"})  # fmt: skip
            continue
        d = paired_differences(arm_res[lab].run.equity_curve, t2_curve)
        nr, nr2 = metrics[lab]["net_return"], metrics["TIER2"]["net_return"]
        ablation.append({"arm": lab, "net_return": nr, "delta_vs_tier2": (nr - nr2) if nr is not None and nr2 is not None else None,
                         "identical_path_to_tier2": all(x == 0.0 for x in d), "status": "COMPLETED"})  # fmt: skip

    fam = Decimal(spec.confidence_level)
    adj = adjusted_confidence_level(fam, spec.n_comparisons)
    stats: dict = {"family_confidence_level": str(fam), "n_comparisons": spec.n_comparisons,
                   "per_comparison_confidence_level": str(adj), "method": "paired circular block bootstrap of per-cycle "
                   "return differences (AI arm - Tier-2), Bonferroni-adjusted level; no p-values are reported",
                   "comparisons": {}}  # fmt: skip
    cis: dict = {}
    for lab in [*magnitude_arms]:
        if lab in arm_res:
            ci = block_bootstrap_mean_ci(paired_differences(arm_res[lab].run.equity_curve, t2_curve), confidence=adj,
                                         resamples=spec.bootstrap_resamples, block_length=spec.bootstrap_block_length,
                                         seed=spec.random_seed, min_n=spec.min_cycles // 2 or 2)  # fmt: skip
            cis[lab] = ci
            stats["comparisons"][lab] = ci.to_dict()
    pbo_series = {lab: [Decimal(str(r)) for _, r in cycle_returns(arm_res[lab].run.equity_curve)] for lab in magnitude_arms
                  if lab in arm_res}  # fmt: skip
    n_per = len(next(iter(pbo_series.values()), []))
    parts = max([k for k in range(2, min(16, n_per) + 1, 2) if n_per % k == 0], default=0)
    try:
        stats["pbo"] = compute_pbo(pbo_series, parts).to_dict() if len(pbo_series) >= 2 else {"status": "UNAVAILABLE", "reason": "fewer than 2 variants"}  # noqa: E501
    except Exception as e:  # noqa: BLE001
        stats["pbo"] = {"status": "UNAVAILABLE", "reason": f"{type(e).__name__}: {e}"[:200]}
    stats["walk_forward"] = {"status": "NOT_PERFORMED", "reason": "no model fitting or configuration selection occurs in this "
                             "evaluation (defaults frozen before the run); Slice 9 split/purge utilities are not engaged"}  # fmt: skip
    stats["regimes"] = {"status": "NOT_PERFORMED_ON_AI_COMPARISON", "reason": "AI and Tier-2 paths are compared across the whole "
                        "confirmatory window; segmenting identical or near-identical paths by regime adds no information"}  # fmt: skip

    ai_primary = "TIER2_AI_ENABLED"
    ai_ev = [e.payload for e in arm_reader[ai_primary].events() if e.event_type is ET.AI_SIGNAL_EVALUATED] if ai_primary in arm_reader else []
    ai_metrics = signal_metrics([s.to_payload() for s in sig_sets[ai_primary]], audits[ai_primary], ai_ev, trade_keys,
                                scn.disclosure_status_counts or scn.disclosures.counts_by_status())  # fmt: skip
    rows = []
    for c in cands:
        if c.action is Action.HOLD:
            continue
        k = (c.instrument_id, ensure_utc(c.timestamp).isoformat())
        ev = next((p for p in ai_ev if p.get("signal") and (p["signal"]["instrument_id"], ensure_utc(
            datetime.fromisoformat(str(p["signal"]["decision_timestamp"]))).isoformat()) == k), None)  # fmt: skip
        adjd = (((ev or {}).get("signal") or {}).get("interpretation") or {}).get("confidence_adjustment")
        rows.append({"instrument_id": c.instrument_id, "decision_timestamp": c.timestamp,
                     "direction": {"INCREASE": 1, "DECREASE": -1}.get(adjd, 0),
                     "applied": bool(ev and str(ev.get("applied")).lower() == "true")})  # fmt: skip
    ic = information_content(rows, scn.bars, decision_ts, confidence=adj, resamples=spec.bootstrap_resamples,
                             seed=spec.random_seed, min_n=spec.min_valid_signals)  # fmt: skip

    # ---- 6. authority checks, evidence class, decision ----
    uid = set(scn.universe.instrument_ids)
    auth = {lab: _authority_checks(arm_reader["TIER2"], arm_res["TIER2"], arm_reader[lab], arm_res[lab], uid)
            for lab in [*AI_ARMS, *magnitude_arms] if lab in arm_res}  # fmt: skip
    provs = {e.provenance for e in audits[ai_primary].entries if e.provenance is not Provenance.NO_PROVIDER_OUTPUT}
    if scn.data_origin != "REAL":
        measured = EVIDENCE_CLASSES[0]
    elif not provs or provs == {Provenance.OFFLINE_FIXTURE}:
        measured = EVIDENCE_CLASSES[1]
    elif Provenance.OFFLINE_FIXTURE in provs or Provenance.RETROSPECTIVE_REPLAY in provs:
        measured = EVIDENCE_CLASSES[2]
    else:
        measured = EVIDENCE_CLASSES[3]
    if EVIDENCE_CLASSES.index(spec.evidence_class_declared) > EVIDENCE_CLASSES.index(measured):
        findings.append(f"DECLARED_CLASS_NOT_SUPPORTED: spec declared {spec.evidence_class_declared}, measured {measured}")
    assessment = assess_ai_model(mv, overlays[ai_primary].model_provenance, split)
    findings += [f"AI_MODEL: {r}" for r in assessment.reasons]
    eff_conf = (measured == CONFIRMATORY_GRADE and not findings and not breaches and not failures
                and assessment.evaluation_class.value == "CONFIRMATORY_ELIGIBLE")  # fmt: skip
    ai_m, t2_m = metrics.get(ai_primary), metrics["TIER2"]
    ci = cis.get(f"TIER2_AI_ENABLED@max_delta={Decimal(str(cfg_payload.max_delta)).normalize():f}")
    identical = bool(next((r["identical_path_to_tier2"] for r in ablation if r["arm"] == ai_primary), False))
    dec = classify_outcome(spec, DecisionInputs(
        evidence_class=measured, effective_confirmatory=eff_conf, integrity_breaches=len(breaches),
        n_valid_signals=ai_metrics["valid_ai_signals"], signal_coverage=ai_metrics["signal_coverage"]["value"],
        n_cycles=t2_m["decision_cycles"], arm_paths_identical=identical,
        incremental_trades=inc.get(ai_primary, {}).get("trades_only_in_ai_arm", 0) + inc.get(ai_primary, {}).get("trades_only_in_baseline_arm", 0),
        delta_net_return=(ai_m["net_return"] - t2_m["net_return"]) if ai_m else None,
        ci_lower=ci.lower if ci else None, ci_upper=ci.upper if ci else None, ci_status=ci.status if ci else "UNAVAILABLE",
        drawdown_regression=(ai_m["max_drawdown"] - t2_m["max_drawdown"]) if ai_m and ai_m["max_drawdown"] is not None else None,
        cost_increase_fraction=((ai_m["total_costs"] - t2_m["total_costs"]) / t2_m["total_costs"]) if ai_m and t2_m["total_costs"] else None,
    ))  # fmt: skip

    applied_n = ai_metrics["adjustments_applied"]
    consumed = inc.get(ai_primary, {}).get("identical") is False
    def nr(lab: str) -> str:
        v = (metrics.get(lab) or {}).get("net_return")
        return "n/a (arm failed)" if v is None else f"{v:.6f}"

    headline = [
        f"Net return: AI-enabled Tier-2 {nr(ai_primary)}, Tier-2 {nr('TIER2')}, Tier-1 {nr('TIER1')} "
        "(all net of the same verified cost schedule).",
        f"{applied_n} confidence adjustment(s) were applied; trades differing from Tier-2: "
        f"{inc.get(ai_primary, {}).get('trades_only_in_ai_arm', 'n/a')} added, {inc.get(ai_primary, {}).get('trades_only_in_baseline_arm', 'n/a')} removed.",
        ("No confidence adjustment was applied in the AI-enabled arm: the arm exercised nothing (see signal coverage)."
         if not applied_n else
         "Confidence adjustments reached no sizing/risk input in this repository, so the AI arm is mechanically unable to "
         "change simulated outcomes; the equity paths are identical by construction." if not consumed else
         "AI adjustments changed at least one simulated trade."),
        f"Evidence class measured: {measured}. This is {'confirmatory-grade' if eff_conf else 'NOT confirmatory-grade'} evidence.",
    ]
    rec_text = {
        "A": "Continue to controlled PAPER evaluation under Slice 13 governance. This is not permission for live trading.",
        "B": "Keep the AI component experimental and disabled in any decision path. Obtain confirmatory-grade evidence "
             "(real market data, live-captured provider signals recorded at decision time, cutoff-clean window) and, "
             "before that, decide through a governed ADR whether confidence should ever reach sizing; today it cannot.",
        "C": "Retain the deterministic baseline. Do not promote the AI component.",
        "D": "Disable the experimental signal and redesign; investigate the harm or integrity finding before any further use.",
    }[dec.outcome]
    trial_terms = Counter(e.outcome.value for e in ledger.entries() if e.lifecycle == "TERMINAL" and e.attempt_id in attempts.values())
    limitations = [
        "Synthetic prices rise monotonically, so drawdown, downside deviation and worst-cycle metrics are degenerate and cycle Sharpe is not meaningful." if scn.data_origin != "REAL" else "",
        "Synthetic/offline-fixture evidence cannot support a claim about markets or about any AI model." if measured != CONFIRMATORY_GRADE else "",
        "AI-enabled and Tier-2 runs share the run id by Slice 11 design (run-facing strategy id stays the baseline id); arms are "
        "distinguished here by arm label, overlay version id and journal AI events.",
        "Sharpe is per-cycle and not annualised; annualised return/volatility/Calmar are UNSUPPORTED (irregular cycle spacing, short sample).",
        "Sector concentration is unavailable (no sector classification in repository data).",
        "Simulated execution: NEXT_BAR_OPEN fills with a deterministic simulated broker; no market-impact or queue model.",
        "Information-content diagnostic uses cross-sectional observations that are not independent; its interval is optimistic.",
        "Walk-forward and regime segmentation were not performed because no model fitting or selection occurs and the compared paths are identical or near-identical.",
        "No real provider call has been made in this evaluation; fixture signals are not model outputs.",
    ]
    artifact = {
        "evaluation_version": EVALUATION_VERSION, "spec": spec.payload(), "spec_hash": spec_hash,
        "experiment_id": "aiexp_" + spec_hash[:16], "evaluation_run_id": "aieval_" + hash_json_stable([spec_hash, dataset_hash])[:16],
        "evidence_class": measured, "effective_confirmatory": eff_conf, "data_origin": scn.data_origin,
        "dataset_hash": dataset_hash, "holdout": {"id": hid, "status_at_exposure": hstatus},
        "data_quality": {"bars": len(scn.bars), "instruments": len({b.instrument_id for b in scn.bars}),
                         "first_bar": min(b.timestamp for b in scn.bars).isoformat(), "last_bar": max(b.timestamp for b in scn.bars).isoformat(),
                         "sources": sorted({b.source for b in scn.bars}), "origin": scn.data_origin,
                         "survivorship_and_revision_data": "UNAVAILABLE for the synthetic dataset"},  # fmt: skip
        "point_in_time": {**audits[ai_primary].to_dict(), "exclusion_log": audits[ai_primary].exclusion_log,
                          "integrity_breaches": len(breaches), "integrity_breach_detail": breaches,
                          "other_arm_audit_counts": {k: v.counts() for k, v in audits.items() if k != ai_primary},
                          "provider_status_by_arm": {k: dict(Counter(str(x.provider_status.value) if hasattr(x.provider_status, "value") else str(x.provider_status) for x in v)) for k, v in sig_sets.items()}},  # fmt: skip
        "arms": metrics, "arm_failures": failures, "ablation": ablation, "incremental_trades": inc,
        "authority_checks": auth, "ai_metrics": ai_metrics, "information_content": ic, "statistics": stats,
        "ai_model_provenance": assessment.provenance, "findings": findings,
        "signal_sources": {"enabled_provider": scn.enabled_provider.provider_name,
                           "replayed_from_recorded_captures": bool(getattr(scn.enabled_provider, "replayed", False))},
        "journal_digests": {lab: arm_res[lab].journal_ref for lab in arm_res},
        "trial_ledger": {"attempts": len(attempts), "terminal_outcomes": dict(trial_terms)},
        "decision": dec.to_dict(), "headline_findings": headline, "limitations": [x for x in limitations if x],
        "recommendation": rec_text, "promotion": "NOT_PERMITTED_BY_THIS_SLICE",
        "cost_schedule_version": spec.cost_schedule_version, "dataset_id": spec.dataset_id,
    }
    art = finalize_artifact(artifact)
    jp, mp = write_artifact(art, root, art["evaluation_run_id"])
    art["_paths"] = {"json": str(jp), "markdown": str(mp)}
    return art
