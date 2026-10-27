"""Durable protocol registry: write-once, hash-verified, ordered by an injected clock."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from research.harness.jsonio import dumps
from research.protocol.protocol import ExperimentMode, ExperimentProtocol
from shared.time.clock import ensure_utc, utc_now
from shared.versioning.content_hash import hash_json_stable


class ProtocolError(ValueError):
    pass


class ProtocolConflict(ProtocolError):
    pass


class ProtocolNotRegistered(ProtocolError):
    pass


@dataclass(frozen=True)
class RegisteredProtocol:
    protocol: ExperimentProtocol | None  # None when loaded from disk (payload hash is verified)
    protocol_hash: str
    registered_at: datetime  # non-deterministic registration metadata, kept apart from the hash


class ProtocolRegistry:
    def __init__(self, root: Path | str, clock: Callable[[], datetime] = utc_now) -> None:
        self._root = Path(root) / "protocols"
        self._clock = clock

    def _path(self, protocol_id: str, version: int) -> Path:
        return self._root / protocol_id / f"v{version}.json"

    def register(self, protocol: ExperimentProtocol) -> RegisteredProtocol:
        errs = protocol.validate()
        if errs:
            raise ProtocolError("invalid protocol: " + "; ".join(errs))
        h = protocol.protocol_hash()
        path = self._path(protocol.protocol_id, protocol.version)
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            if stored["protocol_hash"] == h:
                return self.get(protocol.protocol_id, protocol.version)
            raise ProtocolConflict(
                f"{protocol.protocol_id} v{protocol.version} is already registered with a "
                f"different hash; a changed protocol needs a NEW version (the original is "
                f"never edited)"
            )
        if protocol.version > 1:
            prior = self._path(protocol.protocol_id, protocol.version - 1)
            if not prior.exists():
                raise ProtocolError(f"v{protocol.version} requires registered v{protocol.version - 1}")
            prior_hash = json.loads(prior.read_text(encoding="utf-8"))["protocol_hash"]
            if protocol.supersedes_protocol_hash != prior_hash:
                raise ProtocolError("supersedes_protocol_hash does not match the prior version")
        path.parent.mkdir(parents=True, exist_ok=True)
        at = ensure_utc(self._clock())
        path.write_text(
            dumps({"protocol_hash": h, "registered_at": at, "protocol": protocol.payload()}),
            encoding="utf-8",
        )
        return RegisteredProtocol(protocol, h, at)

    def get(self, protocol_id: str, version: int) -> RegisteredProtocol:
        path = self._path(protocol_id, version)
        if not path.exists():
            raise ProtocolNotRegistered(f"{protocol_id} v{version} is not registered")
        stored = json.loads(path.read_text(encoding="utf-8"))
        recomputed = hash_json_stable(stored["protocol"])
        if recomputed != stored["protocol_hash"]:
            raise ProtocolError(f"stored protocol {protocol_id} v{version} fails hash verification")
        # The live dataclass is not reconstructed from JSON; callers keep the object they
        # registered. We return the stored payload's hash/time and verify identity separately.
        return RegisteredProtocol(None, stored["protocol_hash"],
                                  datetime.fromisoformat(stored["registered_at"]))

    def verify_registered_before(
        self, protocol: ExperimentProtocol, evaluation_started_at: datetime
    ) -> RegisteredProtocol:
        """Confirmatory prerequisite: exact frozen protocol, registered BEFORE evaluation."""
        reg = self.get(protocol.protocol_id, protocol.version)
        if reg.protocol_hash != protocol.protocol_hash():
            raise ProtocolConflict("the protocol being evaluated differs from the frozen one")
        if reg.registered_at > ensure_utc(evaluation_started_at):
            raise ProtocolError(
                "protocol was registered after evaluation began; it cannot be pre-registered"
            )
        return RegisteredProtocol(protocol, reg.protocol_hash, reg.registered_at)


def confirmatory_eligibility(protocol: ExperimentProtocol) -> list[str]:
    """Reasons a run under this protocol cannot be a valid confirmatory result (empty = none)."""
    reasons = [] if protocol.mode is ExperimentMode.CONFIRMATORY else ["protocol is EXPLORATORY"]
    reasons += protocol.validate()
    return reasons
