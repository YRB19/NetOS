"""Validity evaluation: protocol + trial ledger + holdout + contamination + quality + stats.

Produces an immutable, hash-linked report. It NEVER labels a strategy profitable and is not
a promotion mechanism. Verdicts: INVALID, UNSUPPORTED, EXPLORATORY_ONLY, INCONCLUSIVE,
INFRASTRUCTURE_ONLY (synthetic data), CONFIRMATORY_CHECKS_PASSED (historical-verified only).
Research cannot import observability, so Slice 8 journal links are plain string references.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from research.experiments.store import ArtifactConflict, content_digest, _files_for
from research.harness.jsonio import dumps, jsonable
from research.harness.result import ResearchRunResult
from research.protocol.protocol import Comparator, ExperimentMode, ExperimentProtocol
from shared.versioning.content_hash import hash_json_stable

REPORT_SCHEMA = "validity-report-v1"
_CMP = {Comparator.GT: lambda a, b: a > b, Comparator.GE: lambda a, b: a >= b,
        Comparator.LT: lambda a, b: a < b, Comparator.LE: lambda a, b: a <= b}  # fmt: skip


def assess_criteria(protocol: ExperimentProtocol, extended_metrics: dict) -> dict:
    """Assess ONLY structured criteria against computed metrics. Unavailable metric ->
    INCONCLUSIVE for that criterion. Free-text rationale is never assessed."""
    rows, any_adverse, any_inconclusive, all_pass = [], False, False, True
    for c in protocol.acceptance_criteria:
        m = extended_metrics.get(c.metric)
        if not isinstance(m, dict) or m.get("value") is None or m.get("status") != "OK":
            rows.append({"metric": c.metric, "result": "INCONCLUSIVE", "reason": "metric unavailable or unsupported"})
            any_inconclusive, all_pass = True, False
            continue
        met = _CMP[c.comparator](Decimal(m["value"]), Decimal(c.threshold))
        rows.append({"metric": c.metric, "comparator": c.comparator.value, "threshold": c.threshold,
                     "observed": m["value"], "satisfied": met, "adverse": c.adverse})  # fmt: skip
        if c.adverse and met:
            any_adverse = True
        if not c.adverse and not met:
            all_pass = False
    overall = ("ADVERSE" if any_adverse else "INCONCLUSIVE" if any_inconclusive
               else "CRITERIA_MET" if (all_pass and rows) else "CRITERIA_NOT_MET")  # fmt: skip
    return {"overall": overall, "criteria": rows, "free_text_assessed": False}


def build_report(*, protocol: ExperimentProtocol, protocol_hash: str, protocol_registered_at: str | None,
                 result: ResearchRunResult, extended_metrics: dict, quality: dict,
                 holdout_status: str, trial_count: int, ledger_head_hash: str,
                 pbo: dict | None, regimes: dict | None, walk_forward: dict | None,
                 purge: dict | None, journal_refs: dict | None = None,
                 additional_reasons: list[str] | None = None) -> dict:  # fmt: skip
    reasons: list[str] = list(additional_reasons or [])
    contamination = result.contamination_report
    pit = contamination.get("point_in_time", {})
    verdict = "INCONCLUSIVE"
    if result.status.value != "COMPLETED" if hasattr(result.status, "value") else str(result.status) != "COMPLETED":
        verdict = "INVALID" if result.failure and result.failure.category.value == "CONTAMINATION" else "UNSUPPORTED"
        reasons.append(f"run did not complete: {result.failure.message if result.failure else 'unknown'}")
    else:
        if protocol.mode is not ExperimentMode.CONFIRMATORY:
            reasons.append("exploratory protocol")
            verdict = "EXPLORATORY_ONLY"
        elif holdout_status != "UNTOUCHED":
            reasons.append("holdout previously exposed; cannot be confirmatory")
            verdict = "EXPLORATORY_ONLY"
        elif protocol_registered_at is None:
            reasons.append("protocol not registered before evaluation")
            verdict = "UNSUPPORTED"
        elif quality["evidence_class"] == "SYNTHETIC_INFRASTRUCTURE":
            verdict = "INFRASTRUCTURE_ONLY"
            reasons.append("synthetic data: not market evidence")
        elif not pit.get("clean_point_in_time_claim") or quality["blocking_errors"]:
            verdict = "UNSUPPORTED"
            reasons.append("point-in-time provenance or dataset quality insufficient for a clean claim")
        elif purge is not None and any(b["status"] == "NOT_DECLARED" for b in purge.values()):
            verdict = "UNSUPPORTED"
            reasons.append("information horizon not declared")
        else:
            verdict = "CONFIRMATORY_CHECKS_PASSED"
    body = {
        "schema": REPORT_SCHEMA, "run_id": result.run_id, "experiment_id": result.experiment_id,
        "protocol": {"id": protocol.protocol_id, "version": protocol.version, "hash": protocol_hash,
                     "registered_at": protocol_registered_at, "mode": protocol.mode.value},  # fmt: skip
        "verdict": verdict, "reasons": reasons, "profitability_claim": "NONE",
        "evidence_class": quality["evidence_class"],
        "trial_accounting": {"trials_recorded_for_protocol_family": trial_count, "ledger_head_hash": ledger_head_hash},
        "holdout": {"id": protocol.holdout_id, "status": holdout_status},
        "contamination": contamination, "dataset_quality": quality,
        "criteria_assessment": assess_criteria(protocol, extended_metrics),
        "metrics": extended_metrics, "statistical_validation": {"cscv_pbo": pbo},
        "regimes": regimes, "walk_forward": walk_forward, "purge_embargo": purge,
        "links": {"data_snapshot_version": result.data_snapshot_version,
                  "cost_schedule_version": result.cost_schedule_version,
                  "strategy_version_id": result.strategy_version_id,
                  "baseline_strategy_version_ids": list(result.baseline_strategy_version_ids),
                  "universe_schedule": [list(u) for u in result.universe_schedule],
                  "run_artifact_digest": content_digest(_files_for(result)),
                  "journal_refs": journal_refs or {}, "journal_link_note": "string references only; research cannot import or write the journal (ADR-6)"},  # fmt: skip
        "uncertainty_notice": "Passing checks, PBO or a positive return is not evidence of sustainable future profit.",
    }
    body["report_hash"] = hash_json_stable(jsonable(body))
    return body


def write_report(report: dict, root: Path | str) -> Path:
    d = Path(root) / "validity" / report["run_id"]
    path = d / "report.json"
    text = dumps(report)
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ArtifactConflict(f"{path} holds a different validity report; never overwritten")
        return path
    d.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ReproducibilityFailure(RuntimeError):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind


def verify_stored_run(root: Path | str, run_id: str, expected_digest: str) -> None:
    run_dir = Path(root) / "runs" / run_id
    if not run_dir.is_dir():
        raise ReproducibilityFailure("MISSING_ARTIFACT", f"{run_dir} not found; not recreated from current sources")
    files = {p.name: p.read_text(encoding="utf-8") for p in run_dir.iterdir() if p.is_file() and p.name != "meta.json"}
    if content_digest(files) != expected_digest:
        raise ReproducibilityFailure("CORRUPT_ARTIFACT", f"{run_dir} digest differs from recorded digest")


def reproduce_run(root: Path | str, report_path: Path | str, *, harness, config, strategy,
                  market_data, universe_schedule, baseline_ids=None) -> dict:  # fmt: skip
    """Recompute a run from caller-supplied stored inputs and compare artifact digests.

    Missing inputs (None) are a reproducibility failure; nothing is fetched from today's data."""
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    for name, v in (("market_data", market_data), ("universe_schedule", universe_schedule),
                    ("config", config), ("strategy", strategy)):  # fmt: skip
        if v is None:
            raise ReproducibilityFailure("MISSING_INPUT", f"{name} not supplied")
    verify_stored_run(root, report["run_id"], report["links"]["run_artifact_digest"])
    r = harness.run(config, strategy, market_data, universe_schedule, baseline_ids)
    if r.data_snapshot_version != report["links"]["data_snapshot_version"]:
        raise ReproducibilityFailure("INPUT_MISMATCH", "supplied market data differs from the stored data snapshot version")
    new = content_digest(_files_for(r))
    ok = new == report["links"]["run_artifact_digest"]
    return {"reproduced": ok, "recomputed_digest": new, "stored_digest": report["links"]["run_artifact_digest"]}
