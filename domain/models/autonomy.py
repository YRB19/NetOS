"""AutonomyLevel (Stage 3 §2, AR-1, AR-5) — current + historical autonomy state.

Append-only: a level "transition," never an edit in place (Stage 3 §2).
This slice establishes only the domain representation — no autonomy
*behavior* (what a given level actually permits) and no promotion logic
are implemented here; that is Governance-plane build work per the
implementation prompt's explicit "do not implement autonomy behavior yet."
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from domain.models._validators import require_aware_utc, require_non_empty_str

MIN_LEVEL = 0
MAX_LEVEL = 3

LEVEL_NAMES: dict[int, str] = {
    0: "Advisory",
    1: "Supervised",
    2: "Delegated",
    3: "Fully Autonomous",
}


@dataclass(frozen=True, slots=True)
class AutonomyLevel:
    level: int  # 0..3
    set_by: str  # always the operator (AR-2: system may never self-promote)
    effective_from: datetime
    effective_to: datetime | None = None  # None means "currently in effect"

    def __post_init__(self) -> None:
        if not isinstance(self.level, int) or not (MIN_LEVEL <= self.level <= MAX_LEVEL):
            raise ValueError(
                f"level must be an int in {MIN_LEVEL}..{MAX_LEVEL}, got: {self.level!r}"
            )
        require_non_empty_str(self.set_by, "set_by")
        object.__setattr__(
            self, "effective_from", require_aware_utc(self.effective_from, "effective_from")
        )
        if self.effective_to is not None:
            object.__setattr__(
                self, "effective_to", require_aware_utc(self.effective_to, "effective_to")
            )
            if self.effective_to <= self.effective_from:
                raise ValueError("effective_to must be strictly after effective_from")

    @property
    def name(self) -> str:
        return LEVEL_NAMES[self.level]

    def is_current(self) -> bool:
        return self.effective_to is None

    def closed(self, effective_to: datetime) -> AutonomyLevel:
        """Return a NEW record with effective_to set — never mutates in place.

        This is how an append-only history is built: the old record is
        superseded by writing a new immutable record with its window
        closed, plus a fresh AutonomyLevel record for the new level. Which
        code path is allowed to call this (only an explicit, documented
        operator decision — AR-2) is enforced at the governance layer, not
        by this domain object itself.
        """
        from dataclasses import replace

        return replace(self, effective_to=effective_to)
