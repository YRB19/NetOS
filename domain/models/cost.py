"""CostEstimate / ActualCost (Stage 3 §2, §6) — TR-2 / PR-6 / PR-7.

Both are immutable, pinned to a `cost_model_version` so a Research-stage
backtest and a live decision can never silently use inconsistent cost
assumptions (Stage 3 §6's "no hidden global state" design).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from domain.models._validators import (
    require_non_empty_str,
    require_non_negative,
    require_uuid_like,
)
from shared.versioning.identifiers import new_id


@dataclass(frozen=True, slots=True)
class CostEstimate:
    instrument_id: str
    brokerage: float
    stt: float
    exchange_charges: float
    sebi_fees: float
    gst: float
    stamp_duty: float
    estimated_slippage: float
    cost_model_version: str
    cost_estimate_id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        require_non_empty_str(self.instrument_id, "instrument_id")
        require_non_empty_str(self.cost_model_version, "cost_model_version")
        require_uuid_like(self.cost_estimate_id, "cost_estimate_id")
        for name in (
            "brokerage",
            "stt",
            "exchange_charges",
            "sebi_fees",
            "gst",
            "stamp_duty",
            "estimated_slippage",
        ):
            require_non_negative(getattr(self, name), name)

    def total(self) -> float:
        return (
            self.brokerage
            + self.stt
            + self.exchange_charges
            + self.sebi_fees
            + self.gst
            + self.stamp_duty
            + self.estimated_slippage
        )


@dataclass(frozen=True, slots=True)
class ActualCost:
    order_id: str  # FK -> Order
    brokerage: float
    stt: float
    exchange_charges: float
    sebi_fees: float
    gst: float
    stamp_duty: float
    realized_slippage: float
    cost_model_version: str
    actual_cost_id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        require_uuid_like(self.order_id, "order_id")
        require_non_empty_str(self.cost_model_version, "cost_model_version")
        require_uuid_like(self.actual_cost_id, "actual_cost_id")
        for name in ("brokerage", "stt", "exchange_charges", "sebi_fees", "gst", "stamp_duty"):
            require_non_negative(getattr(self, name), name)
        # Slippage can, in principle, be negative (a fill better than the
        # reference price) — unlike estimated_slippage (a conservative
        # projection), realized_slippage is an observed delta and is not
        # constrained to be non-negative.
        if not isinstance(self.realized_slippage, (int, float)):
            raise ValueError(f"realized_slippage must be numeric, got: {self.realized_slippage!r}")

    def total(self) -> float:
        return (
            self.brokerage
            + self.stt
            + self.exchange_charges
            + self.sebi_fees
            + self.gst
            + self.stamp_duty
            + self.realized_slippage
        )
