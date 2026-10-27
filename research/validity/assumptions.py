"""Execution/cost assumption disclosure contract (Slice 9, ADR-19).

Never invents market-depth, spread or slippage evidence. Each component is SOURCED,
ASSUMED (explicit, unverified), UNMODELLED or UNSUPPORTED, and surfaces in every report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class AssumptionStatus(str, Enum):  # noqa: UP042
    SOURCED = "SOURCED"
    ASSUMED_UNVERIFIED = "ASSUMED_UNVERIFIED"
    UNMODELLED = "UNMODELLED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class ExecutionAssumptions:
    version: str = "execution-assumptions-v1"
    # slippage applied ONLY to the terminal-liquidation estimate, never to booked trades
    terminal_slippage_bps: Decimal | None = None
    terminal_slippage_status: AssumptionStatus = AssumptionStatus.UNMODELLED
    extra: dict = field(default_factory=dict)

    def disclosures(self) -> dict:
        return {
            "version": self.version,
            "booked_fill_price": {"status": "ASSUMED_UNVERIFIED", "detail": "NEXT_BAR_OPEN fills at the bar open; no verified execution-quality evidence"},  # fmt: skip
            "slippage_booked_trades": AssumptionStatus.UNMODELLED.value,
            "spread": AssumptionStatus.UNMODELLED.value,
            "market_impact": AssumptionStatus.UNMODELLED.value,
            "liquidity_participation_limits": AssumptionStatus.UNMODELLED.value,
            "partial_fills": AssumptionStatus.UNMODELLED.value,
            "terminal_slippage": {
                "status": self.terminal_slippage_status.value,
                "bps": str(self.terminal_slippage_bps) if self.terminal_slippage_bps is not None else None,
            },
            "terminal_liquidation_price": {"status": "ASSUMED_UNVERIFIED", "detail": "last mark close"},
            "brokerage": {"status": "ASSUMED_UNVERIFIED", "detail": "unverified in both cost schedules"},
            "statutory_cost_scope": {"status": "PARTIAL", "detail": "see docs/cost-rate-verification.md"},
        }
