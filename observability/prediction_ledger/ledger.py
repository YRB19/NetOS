"""Ledger WRITER. Hash-chained JSONL: tamper-EVIDENT, not tamper-proof. Research must not import this."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from markets.lane import MarketLane
from prediction_ledger.models import PredictionEventType, PredictionRecord
from prediction_ledger.reader import GENESIS, line_hash, verify_ledger


class LedgerError(Exception):
    pass


class PredictionLedger:
    def __init__(self, root: Path | str, lane: MarketLane):
        self.lane = lane
        self.path = Path(root) / lane.value / "predictions.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rep = verify_ledger(self.path)
        if not rep.ok:
            raise LedgerError(f"existing ledger failed verification: {rep.errors}")
        self._head, self._seq = rep.head_hash, rep.count
        self._known: dict[str, PredictionRecord] = {}
        self._invalidated: set[str] = set()
        if self.path.exists():
            for raw in self.path.read_text(encoding="utf-8").splitlines():
                b = json.loads(raw)["body"]
                if b["event"] in (PredictionEventType.RECORDED.value, PredictionEventType.REJECTED_LATE.value):
                    r = PredictionRecord.from_dict(b["record"])
                    self._known[r.prediction_id] = r
                elif b["event"] == PredictionEventType.CORRECTED.value:
                    r = PredictionRecord.from_dict(b["record"])
                    self._known[r.prediction_id] = r
                elif b["event"] == PredictionEventType.INVALIDATED.value:
                    self._invalidated.add(b["prediction_id"])

    def _append(self, body: dict) -> None:
        body["seq"] = self._seq
        h = line_hash(self._head, body)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"prev": self._head, "hash": h, "body": body}, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._head, self._seq = h, self._seq + 1

    def _check_lane(self, rec: PredictionRecord) -> None:
        if rec.lane is not self.lane:
            raise LedgerError("prediction lane does not match ledger lane")

    def record(self, rec: PredictionRecord, recorded_at: datetime) -> PredictionEventType:
        """Freeze a prediction. Must be committed at/before `valid_from` (before the outcome window)."""
        self._check_lane(rec)
        if rec.prediction_id in self._known:
            raise LedgerError(f"duplicate prediction_id {rec.prediction_id}; use correct()")
        if recorded_at < rec.created_at:
            raise LedgerError("recording time precedes creation time")
        ev = PredictionEventType.RECORDED if recorded_at <= rec.valid_from else PredictionEventType.REJECTED_LATE
        self._append({"event": ev.value, "recorded_at": recorded_at.isoformat(), "record": rec.to_dict(),
                      "late_reason": "" if ev is PredictionEventType.RECORDED else "committed after valid_from"})  # fmt: skip
        self._known[rec.prediction_id] = rec
        return ev

    def correct(self, rec: PredictionRecord, recorded_at: datetime, reason: str) -> None:
        """Linked correction. Allowed only BEFORE valid_from: no hindsight edits."""
        self._check_lane(rec)
        old = self._known.get(rec.prediction_id)
        if old is None:
            raise LedgerError("cannot correct an unknown prediction")
        if recorded_at > old.valid_from:
            raise LedgerError("corrections after valid_from are forbidden; invalidate instead")
        if not reason:
            raise LedgerError("correction requires a reason")
        self._append({"event": PredictionEventType.CORRECTED.value, "recorded_at": recorded_at.isoformat(),
                      "record": rec.to_dict(), "reason": reason})  # fmt: skip
        self._known[rec.prediction_id] = rec

    def invalidate(self, prediction_id: str, recorded_at: datetime, reason: str) -> None:
        """Marks a prediction invalid. The original record and the invalidation both remain visible."""
        if prediction_id not in self._known:
            raise LedgerError("cannot invalidate an unknown prediction")
        if not reason:
            raise LedgerError("invalidation requires a reason")
        self._append({"event": PredictionEventType.INVALIDATED.value, "recorded_at": recorded_at.isoformat(),
                      "prediction_id": prediction_id, "reason": reason})  # fmt: skip
        self._invalidated.add(prediction_id)
