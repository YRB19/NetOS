"""US equity cost schedule and model (Slice 13) — STANDALONE and UNVERIFIED.

This is deliberately NOT wired into the India-shaped `shared.costs.CostEstimate` / simulated broker:
that estimate carries STT/SEBI/GST/stamp-duty fields that do not exist in the US and must not be
relabelled. See ADR-25: the US internal execution path stays BLOCKED until a jurisdiction-neutral
cost breakdown exists. No rate below was verified against a primary source in this slice (no network
access); every rate is an explicit, operator-overridable parameter and `verified` is False.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")


def _money(v: Decimal) -> Decimal:
    return v.quantize(_CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class UsEquityCostSchedule:
    version_id: str
    verified: bool
    source: str
    commission_per_order: Decimal
    sec_fee_per_million_sell: Decimal
    finra_taf_per_share_sell: Decimal
    finra_taf_max_per_trade: Decimal
    notes: dict[str, str] = field(default_factory=dict)


US_EQUITY_SCHEDULE_V1_UNVERIFIED = UsEquityCostSchedule(
    version_id="us-equity-v1-unverified",
    verified=False,
    source="UNVERIFIED recollection of published US fee structures; NOT primary-source verified",
    commission_per_order=Decimal("0"),
    sec_fee_per_million_sell=Decimal("0"),
    finra_taf_per_share_sell=Decimal("0.000166"),
    finra_taf_max_per_trade=Decimal("8.30"),
    notes={
        "warning": "Rates may be stale or wrong. A zero SEC fee/commission can UNDERSTATE cost.",
        "excluded": "No slippage, market impact, borrow, dividends or tax is modelled here.",
        "currency": "USD",
    },
)


@dataclass(frozen=True)
class UsCostEstimate:
    schedule_version: str
    verified: bool
    side: str
    quantity: int
    price: Decimal
    gross_turnover: Decimal
    commission: Decimal
    sec_fee: Decimal
    finra_taf: Decimal
    total_cost: Decimal
    currency: str = "USD"


def estimate_us_cost(
    side: str, quantity: int, price: Decimal, schedule: UsEquityCostSchedule = US_EQUITY_SCHEDULE_V1_UNVERIFIED
) -> UsCostEstimate:
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
        raise ValueError("quantity must be a non-negative int")
    price = Decimal(price)
    if quantity > 0 and price <= 0:
        raise ValueError("price must be positive")
    turnover = price * quantity
    commission = _money(schedule.commission_per_order) if quantity else Decimal("0.00")
    sec = taf = Decimal("0.00")
    if side == "SELL" and quantity:
        sec = _money(turnover / Decimal(1_000_000) * schedule.sec_fee_per_million_sell)
        taf = _money(min(Decimal(quantity) * schedule.finra_taf_per_share_sell,
                         schedule.finra_taf_max_per_trade))  # fmt: skip
    return UsCostEstimate(schedule.version_id, schedule.verified, side, quantity, price, turnover,
                          commission, sec, taf, commission + sec + taf)  # fmt: skip
