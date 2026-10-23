"""Explicit checkpoint persistence for the order lifecycle (Slice 7 closure, ADR-12).

Deliberately small: ONE JSON file, written atomically (temp file in the same directory, flush + fsync,
os.replace, best-effort directory fsync). It stores the manager's checksummed snapshot, nothing else
(no credentials, no sessions, no raw broker payloads). It is an explicit checkpoint, NOT a database,
write-ahead log or queue; see docs/order-state-machine-reconciliation.md §8 for what is and is not guaranteed.
A failed write raises CheckpointError; callers must treat that as "state not durable".
"""

from __future__ import annotations

import json
import os
from pathlib import Path


class CheckpointError(RuntimeError):
    """The mandatory checkpoint could not be written (or read): the dependent operation must not proceed."""


class CheckpointStore:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def write(self, snapshot: dict) -> None:
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self._path)  # atomic on POSIX: readers see the old or the new file, never a torn one
            try:  # make the rename itself durable where the platform allows it
                fd = os.open(self._path.parent, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except OSError:
                pass
        except OSError as e:
            raise CheckpointError(f"checkpoint write failed: {type(e).__name__}: {e}") from e

    def read(self) -> dict | None:
        if not self._path.exists():
            return None
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise CheckpointError(f"checkpoint unreadable or corrupt: {type(e).__name__}: {e}") from e
