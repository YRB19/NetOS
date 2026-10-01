"""File-based research artifact persistence (Slice 5, spec §25).

Layout:  <root>/runs/<run_id>/
    experiment.json      deterministic: config + identity + versions + window
    result.json          deterministic: status, metrics, contamination report, failure
    decisions.jsonl      deterministic: one row per decision (incl. HOLD / rejected)
    trades.jsonl         deterministic: one row per simulated fill, with full provenance
    rejections.jsonl     deterministic: rejected / unexecuted orders
    equity_curve.jsonl   deterministic
    decision_records.jsonl   canonical DecisionRecord objects (fills only)
    evaluation_run.json  canonical EvaluationRun (when one exists)
    failure.json         present iff the run FAILED
    meta.json            NON-deterministic metadata only (created_at) — excluded from digests

Run ids are deterministic, so re-running an experiment targets the same directory. If
the directory already holds DIFFERENT deterministic content the write is refused
(`ArtifactConflict`): stored research — including failures — is never overwritten.
No database, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

from research.harness.jsonio import dumps, jsonable
from research.harness.result import ResearchRunResult
from shared.versioning.content_hash import hash_json_stable

DETERMINISTIC_FILES = (
    "experiment.json", "result.json", "decisions.jsonl", "trades.jsonl", "rejections.jsonl",
    "equity_curve.jsonl", "decision_records.jsonl", "evaluation_run.json", "failure.json",
)  # fmt: skip


class ArtifactConflict(RuntimeError):
    pass


def _without_created_at(obj):
    if obj is None:
        return None
    d = jsonable(obj)
    d.pop("created_at", None)
    return d


def _jsonl(rows) -> str:
    return "".join(dumps(r, indent=None) for r in rows)


def _files_for(r: ResearchRunResult) -> dict[str, str]:
    files = {
        "experiment.json": dumps(
            {
                "run_id": r.run_id,
                "experiment_id": r.experiment_id,
                "harness_version": r.harness_version,
                "strategy_version_id": r.strategy_version_id,
                "baseline_strategy_version_ids": r.baseline_strategy_version_ids,
                "feature_set_version": r.feature_set_version,
                "cost_schedule_version": r.cost_schedule_version,
                "data_snapshot_version": r.data_snapshot_version,
                "universe_schedule": r.universe_schedule,
                "window_start": r.window_start,
                "window_end": r.window_end,
                "initial_capital": r.initial_capital,
                "comparison_fingerprint": r.comparison_fingerprint,
                "config": r.config,
                # Experiment.created_at is wall-clock metadata: it lives in meta.json, not here.
                "experiment": _without_created_at(r.experiment),
            }
        ),
        "result.json": dumps(r.deterministic_summary()),
        "decisions.jsonl": _jsonl(r.decisions),
        "trades.jsonl": _jsonl(r.trades),
        "rejections.jsonl": _jsonl(r.rejections),
        "equity_curve.jsonl": _jsonl(r.equity_curve),
        "decision_records.jsonl": _jsonl(r.decision_records),
    }
    if r.evaluation_run is not None:
        files["evaluation_run.json"] = dumps(_without_created_at(r.evaluation_run))
    if r.failure is not None:
        files["failure.json"] = dumps(
            {"run_id": r.run_id, "experiment_id": r.experiment_id, **r.failure.to_dict(),
             "strategy_version_id": r.strategy_version_id,
             "data_snapshot_version": r.data_snapshot_version,
             "cost_schedule_version": r.cost_schedule_version,
             "config": r.config}
        )  # fmt: skip
    return files


def content_digest(files: dict[str, str]) -> str:
    return hash_json_stable({k: files[k] for k in sorted(files) if k != "meta.json"})


def write_run(result: ResearchRunResult, root: Path | str) -> Path:
    run_dir = Path(root) / "runs" / result.run_id
    files = _files_for(result)
    if run_dir.exists():
        existing = {
            p.name: p.read_text(encoding="utf-8")
            for p in run_dir.iterdir()
            if p.is_file() and p.name != "meta.json"
        }
        if existing != files:
            raise ArtifactConflict(
                f"{run_dir} already holds different research content for run {result.run_id}; "
                f"stored research is never overwritten"
            )
    else:
        run_dir.mkdir(parents=True)
        for name, text in files.items():
            (run_dir / name).write_text(text, encoding="utf-8")
    meta = run_dir / "meta.json"
    if not meta.exists():
        meta.write_text(
            dumps(
                {
                    "created_at": result.created_at,
                    "experiment_created_at": result.experiment.created_at
                    if result.experiment
                    else None,
                    "note": "non-deterministic metadata only",
                }
            ),
            encoding="utf-8",
        )
    return run_dir


def read_run_summary(root: Path | str, run_id: str) -> dict:
    return json.loads((Path(root) / "runs" / run_id / "result.json").read_text(encoding="utf-8"))


def list_runs(root: Path | str) -> list[str]:
    base = Path(root) / "runs"
    return sorted(p.name for p in base.iterdir() if p.is_dir()) if base.exists() else []


def digest_of_run_dir(run_dir: Path | str) -> str:
    d = Path(run_dir)
    return content_digest(
        {p.name: p.read_text(encoding="utf-8") for p in d.iterdir() if p.is_file()}
    )
