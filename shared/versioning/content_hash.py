"""Deterministic content-addressed versioning.

Stage 3 §19 requires a "data snapshot version" = raw data set identity + normalization code
version, and states: "A deterministic content hash or equivalent simple mechanism is
sufficient." This module implements exactly that — nothing more.

No network calls, no wall-clock dependence, no randomness: the same inputs always produce
the same identifier.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def hash_bytes(data: bytes) -> str:
    """SHA-256 hex digest of raw bytes. The single low-level primitive everything else uses."""
    return hashlib.sha256(data).hexdigest()


def hash_file(path: str | Path) -> str:
    """SHA-256 hex digest of a file's exact byte content (the raw source file, e.g. a CSV)."""
    p = Path(path)
    return hash_bytes(p.read_bytes())


def hash_json_stable(obj: Any) -> str:
    """SHA-256 hex digest of a JSON-serializable object, with stable (sorted-key) encoding.

    Used for hashing normalization *code version* identifiers and other small structured
    values where a canonical, order-independent encoding matters.
    """
    encoded = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hash_bytes(encoded)


def data_snapshot_version(raw_source_hash: str, normalization_code_version: str) -> str:
    """Compose a data snapshot version identifier.

    Per Stage 3 §5/§19: "data snapshot version = raw data set + normalization code version."
    Composing the two into one identifier (rather than just concatenating strings) makes it
    infeasible to confuse a snapshot version with either of its inputs, and gives every
    snapshot a fixed-length, hash-shaped identifier regardless of how large the raw dataset
    identity string is.
    """
    combined = f"raw:{raw_source_hash}|norm:{normalization_code_version}"
    return "snap_" + hash_bytes(combined.encode("utf-8"))[:32]
