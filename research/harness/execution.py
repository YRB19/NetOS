"""Research execution assumption (Slice 5, spec §13, §14).

ASSUMPTION `NEXT_BAR_OPEN` (the only one supported):

  * A CandidateTrade produced at decision time t (using information available at t)
    becomes a simulated order sized at t, and FILLS at the OPEN of the instrument's
    next observation strictly after t.
  * No partial fills, no slippage beyond the open-vs-prior-close gap, no market impact,
    no liquidity/volume cap, no price limits, no halts. This is NOT live execution.

SIZING (research accounting only; NOT a production sizing engine):

  target_notional = size_hint * equity_t * (1 - allocation_cash_buffer)
  BUY  quantity  = floor((target_notional - current_value) / reference_close_t), if > 0
  SELL quantity  = held - floor(target_notional / reference_close_t), floored at 0;
                   size_hint == 0 sells the entire holding
  * Integer shares only (floor). Fractional quantities are never permitted.
  * Residual cash (rounding remainder + buffer) stays in cash.
  * The buffer exists so costs/gap-ups are normally affordable; it is configuration,
    not a risk rule. If cash is nevertheless insufficient at fill time the run fails
    closed (or records a rejection, per `order_rejection_policy`).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from domain.models.enums import Action
from domain.models.feature_snapshot import FeatureSnapshot
from domain.models.trade import CandidateTrade
from shared.versioning.content_hash import hash_json_stable

ONE = Decimal("1")


@dataclass
class PendingOrder:
    seq: int
    order_id: str
    instrument_id: str
    side: Action  # BUY or SELL
    quantity: int
    decision_ts: object  # datetime
    candidate: CandidateTrade
    snapshot: FeatureSnapshot
    decision_trace: dict  # mutated in place when the order resolves


@dataclass(frozen=True)
class Translation:
    side: Action | None
    quantity: int
    outcome: str  # ORDER_CREATED | HOLD | NO_TRADE | REJECTED_NO_REFERENCE_PRICE
    reason: str


def research_order_id(run_id: str, candidate_id: str, seq: int) -> str:
    return "rord_" + hash_json_stable({"run": run_id, "candidate": candidate_id, "seq": seq})[:24]


def _floor_int(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_FLOOR))


def translate_candidate(
    candidate: CandidateTrade,
    snapshot: FeatureSnapshot,
    held_quantity: int,
    equity: Decimal,
    cash_buffer: Decimal,
) -> Translation:
    if candidate.action is Action.HOLD:
        return Translation(None, 0, "HOLD", "HOLD decision; no order")

    hint = Decimal(str(candidate.size_hint))
    ref = Decimal(str(snapshot.reference_price)) if snapshot.reference_price is not None else None
    target_notional = hint * equity * (ONE - cash_buffer)

    if candidate.action is Action.SELL:
        if held_quantity <= 0:
            return Translation(None, 0, "NO_TRADE", "SELL requested but nothing is held")
        if hint == 0:
            return Translation(Action.SELL, held_quantity, "ORDER_CREATED", "full exit (target 0)")
        if ref is None:
            return Translation(
                None, 0, "REJECTED_NO_REFERENCE_PRICE",
                "partial SELL needs a reference price; snapshot has none",
            )  # fmt: skip
        qty = max(held_quantity - _floor_int(target_notional / ref), 0)
        if qty == 0:
            return Translation(None, 0, "NO_TRADE", "holding already at/below target")
        return Translation(Action.SELL, qty, "ORDER_CREATED", "reduce to target allocation")

    # BUY
    if ref is None:
        return Translation(
            None, 0, "REJECTED_NO_REFERENCE_PRICE", "BUY needs a reference price; snapshot has none"
        )
    delta = target_notional - Decimal(held_quantity) * ref
    qty = _floor_int(delta / ref) if delta > 0 else 0
    if qty <= 0:
        return Translation(None, 0, "NO_TRADE", "target already met or below one share")
    return Translation(Action.BUY, qty, "ORDER_CREATED", "increase to target allocation")
