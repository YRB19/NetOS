"""File-based artifacts for pipeline runs (Slice 6).

The base research artifacts are written by the existing Slice 5 store unchanged.
The execution-pipeline artifacts go in a `pipeline/` SUBDIRECTORY of the run directory
(which the Slice 5 conflict check ignores), with the same never-overwrite rule.
"""

from __future__ import annotations

from pathlib import Path

from research.experiments.store import ArtifactConflict, write_run
from research.harness.jsonio import dumps
from simulation.result import PipelineRunResult


def _jsonl(rows) -> str:  # noqa: ANN001
    return "".join(dumps(r, indent=None) for r in rows)


def pipeline_files(r: PipelineRunResult) -> dict[str, str]:
    return {
        "pipeline.json": dumps({"identity": r.pipeline_identity, "summary": r.summary}),
        "risk_decisions.jsonl": _jsonl(r.risk_decisions),
        "sizing_decisions.jsonl": _jsonl(r.sizing_decisions),
        "orders.jsonl": _jsonl(r.orders),
        "broker_fills.jsonl": _jsonl(r.broker_fills),
        "reconciliation.jsonl": _jsonl(r.reconciliations),
    }


def write_pipeline_run(result: PipelineRunResult, root: Path | str) -> Path:
    run_dir = write_run(result.run, root)
    sub = run_dir / "pipeline"
    files = pipeline_files(result)
    if sub.exists():
        existing = {p.name: p.read_text(encoding="utf-8") for p in sub.iterdir() if p.is_file()}
        if existing != files:
            raise ArtifactConflict(f"{sub} already holds different pipeline content; never overwritten")
    else:
        sub.mkdir()
        for name, text in files.items():
            (sub / name).write_text(text, encoding="utf-8")
    return run_dir
