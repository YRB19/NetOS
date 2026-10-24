"""Atomic single-file checkpoint for `ResearchPortfolio` (Slice 7 final closure, ADR-13).

Same conventions as the lifecycle checkpoint (temp file in the same directory, flush + fsync, os.replace,
best-effort directory fsync) but deliberately a SEPARATE implementation: `research/` must never import
`risk_execution/` (ADR-6). It stores the portfolio's checksummed snapshot and nothing else. A failed write
raises `ResearchRunFailure(PORTFOLIO_CHECKPOINT_ERROR)`; callers must treat that as "state not durable".
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from research.harness.failures import FailureCategory, ResearchRunFailure


def _err(msg: str, **ctx: object) -> ResearchRunFailure:
    return ResearchRunFailure(FailureCategory.PORTFOLIO_CHECKPOINT_ERROR, msg, **ctx)


class PortfolioCheckpointStore:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def write(self, snapshot: dict) -> None:
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)  # atomic on POSIX: a reader sees the old or the new file, never a torn one
            try:  # make the rename itself durable where the platform allows it
                fd = os.open(self._path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except OSError:
                pass
        except OSError as e:
            raise _err(f"portfolio checkpoint write failed: {type(e).__name__}: {e}") from e

    def read(self) -> dict | None:
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise _err(f"portfolio checkpoint unreadable or corrupt: {type(e).__name__}: {e}") from e
        if not isinstance(data, dict):
            raise _err("portfolio checkpoint is not a JSON object")
        return data
