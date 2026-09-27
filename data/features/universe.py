"""PermittedUniverse — the explicit, versioned, operator-controlled set
of instruments the system may trade. Slice 3 spec §7 / Stage 1 TR-1.

Deliberately NOT a dynamic/discovered universe: it is constructed from
an explicit input list only. No algorithm in this module ever adds or
removes an instrument on its own (Stage 1 TR-7 / Slice 3 spec §7:
"do not invent a dynamic universe-selection algorithm in this slice").

In the full architecture this is Plane-0-owned governance config
(governance/config/); this module is the *shape* and the deterministic
versioning function, used by the feature/context layer and, in later
slices, by governance itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from shared.time.clock import is_utc
from shared.versioning.versioning import content_hash


@dataclass(frozen=True)
class PermittedUniverse:
    """An explicit, deterministically-versioned set of permitted
    instrument_ids, effective from a given point in time."""

    version: str
    instrument_ids: frozenset[str]
    effective_from: datetime

    def __post_init__(self) -> None:
        if not is_utc(self.effective_from):
            raise ValueError("PermittedUniverse.effective_from must be timezone-aware UTC")
        if not isinstance(self.instrument_ids, frozenset):
            object.__setattr__(self, "instrument_ids", frozenset(self.instrument_ids))
        expected_version = compute_universe_version(self.instrument_ids)
        if self.version != expected_version:
            raise ValueError(
                f"PermittedUniverse.version {self.version!r} does not match its "
                f"content-derived version {expected_version!r}; use "
                f"make_permitted_universe() rather than constructing directly, "
                f"or recompute the version explicitly if you changed instrument_ids."
            )

    def contains(self, instrument_id: str) -> bool:
        return instrument_id in self.instrument_ids

    def diff(self, previous: PermittedUniverse | None) -> tuple[frozenset[str], frozenset[str]]:
        """Returns (added, removed) instrument_ids relative to `previous`.
        If previous is None, everything in this universe counts as added
        (the "initial universe" case, per Slice 3 spec §10)."""
        if previous is None:
            return (frozenset(self.instrument_ids), frozenset())
        added = self.instrument_ids - previous.instrument_ids
        removed = previous.instrument_ids - self.instrument_ids
        return (added, removed)


def compute_universe_version(instrument_ids: frozenset[str] | set[str]) -> str:
    """Deterministic version identifier derived purely from universe
    membership — the same set of instruments always yields the same
    version, regardless of insertion order (sorted before hashing)."""
    return content_hash(sorted(instrument_ids))


def make_permitted_universe(instrument_ids, effective_from: datetime) -> PermittedUniverse:
    """Preferred constructor: computes the version for you."""
    frozen = frozenset(instrument_ids)
    if not frozen:
        raise ValueError("PermittedUniverse cannot be empty")
    return PermittedUniverse(
        version=compute_universe_version(frozen),
        instrument_ids=frozen,
        effective_from=effective_from,
    )
