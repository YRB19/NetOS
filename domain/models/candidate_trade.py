"""CandidateTrade (Stage 3 §2, §3.2) — the single most load-bearing interface
in the system.

This is the ONLY channel through which Plane 2 (intelligence) can ever
affect the real world, and it must confer ZERO execution authority. Per
Stage 3 §3.2, this object explicitly does NOT contain:

    - an actual order quantity (see `size_hint` below)
    - a broker instruction of any kind
    - any credential
    - any field that could be interpreted as "execute this"

`size_hint` is deliberately named (not `quantity` or `size`) to avoid the
appearance of a binding amount. Plane 3's sizing module is the only place
a real order quantity is ever computed — this module does not, and must
never, define one. Do not add a field here that would let Plane 2 specify
an authoritative quantity; if you find yourself wanting to, that is a
sign the boundary is being violated, not a sign this class needs a new
field.

`confidence` is mandatory (never optional) per SF-10 — a fallback for
"uncertain" decisions cannot exist if uncertainty is sometimes just absent.

`rationale` is mandatory and non-empty per RR-7 — a candidate with no
loggable justification is rejected before it can influence anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from domain.models._validators import (
    require_aware_utc,
    require_non_empty_str,
    require_unit_interval,
    require_uuid_like,
)
from domain.models.enums import Action, UncertaintyBand
from shared.versioning.identifiers import new_id

# Deliberately NOT part of this module's public surface: any notion of a
# concrete order quantity. See module docstring.
_FORBIDDEN_FIELD_NAMES = frozenset({"quantity", "order_quantity", "shares", "order_size"})


@dataclass(frozen=True, slots=True)
class CandidateTrade:
    instrument_id: str
    timestamp: datetime
    action: Action
    confidence: float  # [0, 1], mandatory (SF-10)
    rationale: str  # mandatory, non-empty (RR-7)
    input_snapshot_id: str  # FK -> FeatureSnapshot.snapshot_id (RR-7 attributability)
    strategy_version_id: str  # FK -> StrategyVersion
    size_hint: float | None = None  # a SUGGESTION only — see module docstring. NOT a quantity.
    uncertainty_band: UncertaintyBand | None = None
    model_version_id: str | None = None  # null for the deterministic baseline
    candidate_id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        require_non_empty_str(self.instrument_id, "instrument_id")
        object.__setattr__(self, "timestamp", require_aware_utc(self.timestamp, "timestamp"))

        if not isinstance(self.action, Action):
            raise ValueError(f"action must be a domain.models.enums.Action, got: {self.action!r}")

        require_unit_interval(self.confidence, "confidence")
        require_non_empty_str(self.rationale, "rationale")
        require_uuid_like(self.input_snapshot_id, "input_snapshot_id")
        require_uuid_like(self.strategy_version_id, "strategy_version_id")
        require_uuid_like(self.candidate_id, "candidate_id")

        if self.uncertainty_band is not None and not isinstance(
            self.uncertainty_band, UncertaintyBand
        ):
            raise ValueError(
                f"uncertainty_band must be an UncertaintyBand or None, got: "
                f"{self.uncertainty_band!r}"
            )

        if self.size_hint is not None and not isinstance(self.size_hint, (int, float)):
            raise ValueError(f"size_hint must be numeric or None, got: {self.size_hint!r}")

        if self.action != Action.HOLD and (self.size_hint is None or self.size_hint < 0):
            raise ValueError("BUY/SELL require a non-negative advisory size_hint")

        # Structural guard against the boundary being weakened later: if
        # anyone ever adds a forbidden field name to this dataclass, fail
        # loudly at every construction rather than silently allowing it.
        present_fields = {f for f in self.__dataclass_fields__ if f in _FORBIDDEN_FIELD_NAMES}
        if present_fields:  # pragma: no cover - defensive, should be unreachable
            raise AssertionError(
                f"CandidateTrade must never define an authoritative order-quantity "
                f"field; found: {present_fields}. This violates the Plane 2/Plane 3 "
                f"boundary (Stage 3 §3.2) and must be reverted, not worked around."
            )
