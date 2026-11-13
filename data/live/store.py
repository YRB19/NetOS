"""Append-only, hash-chained observation store + read-only reader (Slice 13 §4).

Every observation is persisted WITH its quality verdict, including rejected ones. The chain is
tamper-EVIDENT (not tamper-proof). Single writer per lane directory; no locking is claimed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from data.live.observation import LiveObservation
from data.live.quality import QualityDecision
from data.live.reader import StoreError, line_hash, store_path, verify_store
from markets.lane import MarketLane

class ObservationStore:
    """Writer. Research/evaluation code must use `ObservationReader`, never this class."""

    def __init__(self, root: Path | str, lane: MarketLane):
        self.lane = lane
        self.path = store_path(root, lane)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rep = verify_store(self.path)
        if not rep.ok:
            raise StoreError(f"existing store failed verification: {rep.errors}")
        self._head = rep.head_hash
        self._seq = rep.count

    def append(self, obs: LiveObservation, decision: QualityDecision) -> int:
        if obs.lane is not self.lane:
            raise StoreError("observation lane does not match store lane")
        body = {"seq": self._seq, "obs": obs.to_dict(), "verdict": decision.verdict.value,
                "reason": decision.reason}  # fmt: skip
        h = line_hash(self._head, body)
        line = json.dumps({"prev": self._head, "hash": h, "body": body}, sort_keys=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._head = h
        self._seq += 1
        return self._seq - 1


