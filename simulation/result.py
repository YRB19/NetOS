"""PipelineRunResult — a ResearchRunResult plus the execution-pipeline artifacts (Slice 6)."""

from __future__ import annotations

from dataclasses import dataclass

from research.harness.result import ResearchRunResult


@dataclass(frozen=True)
class PipelineRunResult:
    run: ResearchRunResult
    pipeline_identity: dict
    risk_decisions: tuple[dict, ...]
    sizing_decisions: tuple[dict, ...]
    orders: tuple[dict, ...]
    broker_fills: tuple[dict, ...]
    reconciliations: tuple[dict, ...]
    summary: dict
