"""Confirmatory protocol freezing, variant accounting, holdout exposure, multiple-testing (per lane)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from markets.lane import MarketLane
from prediction_ledger.models import Designation
from shared.versioning.content_hash import hash_json_stable


class ConfirmatoryProtocolError(Exception):
    pass


class ProtocolDrift(ConfirmatoryProtocolError):
    pass


@dataclass(frozen=True)
class ConfirmatoryProtocol:
    lane: MarketLane
    protocol_id: str
    designation: Designation
    window_start: datetime
    window_end: datetime
    universe_version: str
    horizons: tuple[str, ...]
    benchmark_id: str
    primary_metrics: tuple[str, ...]
    secondary_metrics: tuple[str, ...]
    exclusion_criteria: tuple[str, ...]
    min_duration_days: int
    min_coverage_ratio: float
    min_scored_predictions: int
    statistical_method: str
    trial_accounting: str
    decision_criteria: tuple[str, ...]
    config_hash: str  # hash of the frozen strategy/AI/prompt/threshold configuration

    def __post_init__(self) -> None:
        if self.window_end <= self.window_start:
            raise ValueError("window_end must follow window_start")
        if not (self.primary_metrics and self.decision_criteria and self.horizons and self.exclusion_criteria is not None):
            raise ValueError("primary metrics, horizons and decision criteria must be pre-declared")
        if not 0 < self.min_coverage_ratio <= 1 or self.min_scored_predictions < 1:
            raise ValueError("coverage ratio in (0,1] and min_scored_predictions >= 1 required")

    def to_dict(self) -> dict:
        d = {}
        for k, v in self.__dict__.items():
            d[k] = v.isoformat() if isinstance(v, datetime) else v.value if hasattr(v, "value") else list(v) if isinstance(v, tuple) else v
        return d

    def protocol_hash(self) -> str:
        return hash_json_stable(self.to_dict())


class ConfirmatoryProtocolRegistry:
    def __init__(self, root: Path | str, lane: MarketLane):
        self.lane = lane
        self.dir = Path(root) / lane.value / "protocols"
        self.dir.mkdir(parents=True, exist_ok=True)

    def freeze(self, p: ConfirmatoryProtocol, frozen_at: datetime, holdouts: ConfirmatoryHoldoutRegistry | None = None) -> str:
        if p.lane is not self.lane:
            raise ConfirmatoryProtocolError("protocol lane mismatch")
        if p.designation is Designation.CONFIRMATORY:
            if frozen_at > p.window_start:
                raise ConfirmatoryProtocolError("confirmatory protocol must be frozen before its window starts")
            if holdouts is not None and holdouts.overlaps_exposed(p.window_start, p.window_end):
                raise ConfirmatoryProtocolError("confirmatory window overlaps an EXPOSED holdout in this market")
        path = self.dir / f"{p.protocol_id}.json"
        h = p.protocol_hash()
        if path.exists():
            if json.loads(path.read_text())["protocol_hash"] != h:
                raise ProtocolDrift("protocol already frozen with different content")
            return h
        path.write_text(json.dumps({"protocol_hash": h, "frozen_at": frozen_at.isoformat(),
                                    "protocol": p.to_dict()}, sort_keys=True, indent=1))  # fmt: skip
        return h

    def frozen_at(self, protocol_id: str) -> datetime:
        return datetime.fromisoformat(json.loads((self.dir / f"{protocol_id}.json").read_text())["frozen_at"])

    def check_no_drift(self, p: ConfirmatoryProtocol, current_config_hash: str) -> None:
        path = self.dir / f"{p.protocol_id}.json"
        if not path.exists():
            raise ConfirmatoryProtocolError("protocol not frozen")
        if json.loads(path.read_text())["protocol_hash"] != p.protocol_hash():
            raise ProtocolDrift("protocol content differs from the frozen protocol")
        if current_config_hash != p.config_hash:
            raise ProtocolDrift("configuration differs from the frozen confirmatory configuration")


class VariantLedger:
    """Every model/prompt/feature/threshold/horizon/strategy variant tried — including abandoned ones."""

    def __init__(self, root: Path | str, lane: MarketLane):
        self.lane = lane
        self.path = Path(root) / lane.value / "variants.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rows = [json.loads(x) for x in self.path.read_text().splitlines()] if self.path.exists() else []
        prev = "0" * 64
        for r in self.rows:
            if r["prev"] != prev or hash_json_stable({"prev": r["prev"], "body": r["body"]}) != r["hash"]:
                raise ConfirmatoryProtocolError("variant ledger failed verification")
            prev = r["hash"]
        self._head = prev

    def register(self, variant_id: str, kind: str, params: dict, status: str, note: str = "") -> None:
        if status not in ("TRIED", "ABANDONED", "ADOPTED"):
            raise ValueError("status must be TRIED, ABANDONED or ADOPTED")
        body = {"variant_id": variant_id, "kind": kind, "params": params, "status": status, "note": note}
        h = hash_json_stable({"prev": self._head, "body": body})
        row = {"prev": self._head, "hash": h, "body": body}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self.rows.append(row)
        self._head = h

    def count(self) -> int:
        return len({r["body"]["variant_id"] for r in self.rows})


class ConfirmatoryHoldoutRegistry:
    """Per-market holdout exposure. Exposure in one market never changes another's."""

    def __init__(self, root: Path | str, lane: MarketLane):
        self.lane = lane
        self.path = Path(root) / lane.value / "holdouts.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self.data, sort_keys=True, indent=1))

    def declare(self, holdout_id: str, start: datetime, end: datetime) -> None:
        self.data[holdout_id] = {"start": start.isoformat(), "end": end.isoformat(), "exposed": False, "why": ""}
        self._save()

    def mark_exposed(self, holdout_id: str, why: str) -> None:
        self.data[holdout_id].update(exposed=True, why=why)
        self._save()

    def overlaps_exposed(self, start: datetime, end: datetime) -> bool:
        return any(
            h["exposed"] and datetime.fromisoformat(h["start"]) < end and start < datetime.fromisoformat(h["end"])
            for h in self.data.values()
        )  # fmt: skip


def holm_adjust(pvalues: dict[str, float]) -> dict[str, float]:
    """Holm step-down on SUPPLIED p-values only. This module never fabricates p-values."""
    items = sorted(pvalues.items(), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def confirmatory_verdict(p: ConfirmatoryProtocol, *, elapsed_days: int, coverage_ratio: float, scored_n: int) -> dict:
    reasons = []
    if elapsed_days < p.min_duration_days:
        reasons.append("below minimum duration")
    if coverage_ratio < p.min_coverage_ratio:
        reasons.append("below minimum coverage")
    if scored_n < p.min_scored_predictions:
        reasons.append("below minimum scored sample")
    return {"lane": p.lane.value, "protocol_id": p.protocol_id,
            "verdict": "INSUFFICIENT_SAMPLE" if reasons else "EVALUABLE_AGAINST_PREDECLARED_CRITERIA",
            "reasons": reasons}  # fmt: skip
