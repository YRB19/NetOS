"""READ-ONLY observation access + chain verification (Slice 13). Safe for the independent evaluator."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from data.live.observation import LiveObservation
from data.live.quality import USABLE, QualityVerdict
from markets.lane import DataProvenance, MarketLane
from shared.versioning.content_hash import hash_json_stable

GENESIS = "0" * 64
FILENAME = "observations.jsonl"


class StoreError(Exception):
    pass


def store_path(root: Path | str, lane: MarketLane) -> Path:
    return Path(root) / lane.value / FILENAME


def line_hash(prev: str, body: dict) -> str:
    return hash_json_stable({"prev": prev, "body": body})


@dataclass(frozen=True)
class StoreVerification:
    ok: bool
    count: int
    head_hash: str
    errors: tuple[str, ...] = ()


def verify_store(path: Path | str) -> StoreVerification:
    p = Path(path)
    if not p.exists():
        return StoreVerification(True, 0, GENESIS)
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
    return StoreVerification(not errs, n, prev, tuple(errs))


@dataclass(frozen=True)
class StoredObservation:
    seq: int
    obs: LiveObservation
    verdict: QualityVerdict
    reason: str

    @property
    def usable(self) -> bool:
        return self.verdict in USABLE


class ObservationReader:
    """READ-ONLY view. Exposes no mutation method; fails closed if the chain does not verify."""

    def __init__(self, root: Path | str, lane: MarketLane):
        self.lane = lane
        self._path = store_path(root, lane)
        rep = verify_store(self._path)
        if not rep.ok:
            raise StoreError(f"observation store failed verification: {rep.errors}")
        self.head_hash = rep.head_hash
        self._rows: list[StoredObservation] = []
        if self._path.exists():
            for raw in self._path.read_text(encoding="utf-8").splitlines():
                b = json.loads(raw)["body"]
                self._rows.append(StoredObservation(b["seq"], LiveObservation.from_dict(b["obs"]),
                                                    QualityVerdict(b["verdict"]), b["reason"]))  # fmt: skip

    def all(self) -> tuple[StoredObservation, ...]:
        return tuple(self._rows)

    def provenances(self) -> frozenset[DataProvenance]:
        return frozenset(r.obs.provenance for r in self._rows if r.usable)

    def usable_as_of(self, as_of: datetime, instrument_id: str | None = None) -> list[LiveObservation]:
        """Point-in-time: only usable observations AVAILABLE at `as_of`; latest revision wins."""
        best: dict = {}
        for r in self._rows:
            o = r.obs
            if not r.usable or o.available_time > as_of:
                continue
            if instrument_id is not None and o.instrument_id != instrument_id:
                continue
            cur = best.get(o.identity)
            if cur is None or o.revision > cur.revision:
                best[o.identity] = o
        return sorted(best.values(), key=lambda x: (x.event_time, x.instrument_id))

    def verdict_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self._rows:
            out[r.verdict.value] = out.get(r.verdict.value, 0) + 1
        return out
