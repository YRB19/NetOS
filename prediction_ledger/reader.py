"""READ-ONLY ledger access and chain verification. Safe for the independent evaluator to import."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from markets.lane import MarketLane
from prediction_ledger.models import PredictionEventType, PredictionRecord, PredictionStatus
from shared.versioning.content_hash import hash_json_stable

GENESIS = "0" * 64


class LedgerReadError(Exception):
    pass


def line_hash(prev: str, body: dict) -> str:
    return hash_json_stable({"prev": prev, "body": body})


@dataclass(frozen=True)
class LedgerVerification:
    ok: bool
    count: int
    head_hash: str
    errors: tuple[str, ...] = ()


def verify_ledger(path: Path | str) -> LedgerVerification:
    p = Path(path)
    if not p.exists():
        return LedgerVerification(True, 0, GENESIS)
    prev, n, errs = GENESIS, 0, []
    for i, raw in enumerate(p.read_text(encoding="utf-8").splitlines()):
        try:
            rec = json.loads(raw)
            if rec["prev"] != prev:
                errs.append(f"line {i}: chain break")
            if rec["body"]["seq"] != n:
                errs.append(f"line {i}: sequence gap")
            if line_hash(rec["prev"], rec["body"]) != rec["hash"]:
                errs.append(f"line {i}: hash mismatch")
            prev = rec["hash"]
        except Exception as e:  # noqa: BLE001
            errs.append(f"line {i}: unreadable ({type(e).__name__})")
            break
        n += 1
    return LedgerVerification(not errs, n, prev, tuple(errs))


@dataclass(frozen=True)
class PredictionView:
    record: PredictionRecord  # effective (latest pre-valid_from correction)
    original: PredictionRecord
    corrections: int
    invalidated: bool
    late_rejected: bool
    invalidation_reason: str = ""

    @property
    def scoreable(self) -> bool:
        return (
            self.record.status is PredictionStatus.ISSUED
            and not self.invalidated
            and not self.late_rejected
        )


class LedgerReader:
    def __init__(self, root: Path | str, lane: MarketLane):
        self.lane = lane
        self.path = Path(root) / lane.value / "predictions.jsonl"
        rep = verify_ledger(self.path)
        if not rep.ok:
            raise LedgerReadError(f"ledger failed verification: {rep.errors}")
        self.head_hash, self.event_count = rep.head_hash, rep.count
        self._views: dict[str, dict] = {}
        if self.path.exists():
            for raw in self.path.read_text(encoding="utf-8").splitlines():
                b = json.loads(raw)["body"]
                ev = b["event"]
                if ev in (PredictionEventType.RECORDED.value, PredictionEventType.REJECTED_LATE.value):
                    r = PredictionRecord.from_dict(b["record"])
                    self._views[r.prediction_id] = {"orig": r, "eff": r, "n": 0, "inv": False,
                                                    "late": ev == PredictionEventType.REJECTED_LATE.value, "why": ""}  # fmt: skip
                elif ev == PredictionEventType.CORRECTED.value:
                    r = PredictionRecord.from_dict(b["record"])
                    v = self._views[r.prediction_id]
                    v["eff"], v["n"] = r, v["n"] + 1
                elif ev == PredictionEventType.INVALIDATED.value:
                    v = self._views[b["prediction_id"]]
                    v["inv"], v["why"] = True, b["reason"]

    def views(self) -> tuple[PredictionView, ...]:
        return tuple(
            PredictionView(v["eff"], v["orig"], v["n"], v["inv"], v["late"], v["why"])
            for v in self._views.values()
        )  # fmt: skip
