"""Holdout identity and exposure history (Slice 9, ADR-15).

The holdout id is derived ONLY from the underlying dataset identity, universe identity and
test window — never from the protocol — so registering a new protocol cannot make an
already-exposed holdout 'untouched' again. Exposure history is append-only.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from pathlib import Path

from research.protocol.protocol import HoldoutReusePolicy
from shared.time.clock import ensure_utc, utc_now
from shared.versioning.content_hash import hash_json_stable


class HoldoutStatus(str, Enum):  # noqa: UP042
    UNTOUCHED = "UNTOUCHED"
    REUSED_NON_CONFIRMATORY = "REUSED_NON_CONFIRMATORY"


class HoldoutReuseError(RuntimeError):
    pass


def holdout_id_for(*, dataset_id: str, dataset_hash: str, universe_versions: tuple[str, ...],
                   test_start: datetime, test_end: datetime) -> str:  # fmt: skip
    return "holdout_" + hash_json_stable({
        "dataset_id": dataset_id, "dataset_hash": dataset_hash,
        "universe_versions": sorted(universe_versions),
        "test_start": ensure_utc(test_start).isoformat(),
        "test_end": ensure_utc(test_end).isoformat(),
    })[:32]  # fmt: skip


class HoldoutRegistry:
    def __init__(self, root: Path | str, clock: Callable[[], datetime] = utc_now) -> None:
        self._dir = Path(root) / "holdouts"
        self._clock = clock

    def _path(self, holdout_id: str) -> Path:
        return self._dir / f"{holdout_id}.jsonl"

    def exposures(self, holdout_id: str) -> list[dict]:
        p = self._path(holdout_id)
        if not p.exists():
            return []
        return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def status(self, holdout_id: str) -> HoldoutStatus:
        return HoldoutStatus.REUSED_NON_CONFIRMATORY if self.exposures(holdout_id) else HoldoutStatus.UNTOUCHED

    def expose(self, *, holdout_id: str, protocol_id: str, protocol_hash: str | None,
               run_id: str | None, mode: str, policy: HoldoutReusePolicy) -> HoldoutStatus:  # fmt: skip
        """Record an exposure. Any prior exposure (exploratory or confirmatory) means the
        holdout is no longer untouched: REJECT refuses, otherwise the new use is recorded as
        REUSED_NON_CONFIRMATORY. History is never erased."""
        prior = self.exposures(holdout_id)
        if prior and policy is HoldoutReusePolicy.REJECT:
            raise HoldoutReuseError(
                f"holdout {holdout_id} was already exposed {len(prior)} time(s); the frozen "
                f"protocol policy REJECTs reuse"
            )
        status = HoldoutStatus.REUSED_NON_CONFIRMATORY if prior else HoldoutStatus.UNTOUCHED
        self._dir.mkdir(parents=True, exist_ok=True)
        rec = {
            "holdout_id": holdout_id, "exposure_number": len(prior) + 1,
            "protocol_id": protocol_id, "protocol_hash": protocol_hash, "run_id": run_id,
            "mode": mode, "status_at_exposure": status.value,
            "recorded_at": ensure_utc(self._clock()).isoformat(),
        }
        with open(self._path(holdout_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return status
