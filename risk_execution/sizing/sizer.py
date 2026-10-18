"""Deterministic position sizing (Slice 6, Stage 3 §8, TR-3).

The FIRST and ONLY place an executable share quantity is computed and an
OrderRequest is constructed. Input: an APPROVED RiskDecision (verified here, not
trusted) plus portfolio state and a reference price. No LLM, no broker, no strategy
import. Integer shares, FLOOR rounding, never negative, never above the risk ceiling.

BUY  : target_value = size_hint * equity * (1 - cash_buffer)
       qty = floor((target_value - effective_position_value) / price)
       then clamped to min(risk ceiling, affordable cash incl. pending sells/buys)
SELL : size_hint == 0 -> full exit of the unencumbered holding
       else qty = effective_qty - floor(size_hint * equity * (1 - cash_buffer) / price)
       clamped to [0, risk ceiling]
Costs are NOT included in the affordability clamp; `cash_buffer` is the explicit
allowance, and the simulated broker rejects a fill it cannot afford (never silently).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from domain.models.enums import Action, RiskVerdict
from domain.models.order_request import OrderRequest, OrderType
from domain.models.portfolio import PortfolioState
from domain.models.risk_decision import RiskDecision
from domain.models.trade import CandidateTrade
from shared.versioning.content_hash import hash_json_stable

ROUNDING = "FLOOR_INTEGER_SHARES"


class SizingOutcome(str, Enum):  # noqa: UP042
    ORDER = "ORDER"
    NO_TRADE = "NO_TRADE"
    REFUSED_NOT_APPROVED = "REFUSED_NOT_APPROVED"
    REJECTED_INVALID_INPUT = "REJECTED_INVALID_INPUT"


@dataclass(frozen=True)
class SizingConfig:
    label: str
    cash_buffer: Decimal  # fraction of equity never allocated, in [0, 1)
    min_trade_notional: Decimal  # partial trades below this value are skipped (full exits exempt)

    def validate(self) -> list[str]:
        e: list[str] = []
        if not isinstance(self.label, str) or not self.label.strip():
            e.append("label must be a non-empty string")
        for name in ("cash_buffer", "min_trade_notional"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (Decimal, int, str)):
                e.append(f"{name} must be Decimal/int/str, got {v!r}")
                continue
            try:
                d = Decimal(v)
            except Exception:  # noqa: BLE001
                e.append(f"{name} not a valid decimal: {v!r}")
                continue
            if not d.is_finite() or d < 0:
                e.append(f"{name} must be finite and >= 0")
            if name == "cash_buffer" and d >= 1:
                e.append("cash_buffer must be < 1")
        return e

    def payload(self) -> dict:
        return {"label": self.label, "cash_buffer": str(Decimal(self.cash_buffer)),
                "min_trade_notional": str(Decimal(self.min_trade_notional)),
                "rounding": ROUNDING, "order_type": "MARKET"}  # fmt: skip


@dataclass(frozen=True)
class SizingInputs:
    portfolio: PortfolioState | None
    equity: Decimal | None
    reference_price: Decimal | None
    pending_buy_qty: int = 0
    pending_sell_qty: int = 0
    research_run_id: str = ""


@dataclass(frozen=True)
class SizingDecision:
    candidate_id: str
    risk_decision_id: str
    outcome: SizingOutcome
    reason: str
    side: Action | None = None
    quantity: int = 0
    target_notional: Decimal | None = None
    reference_price: Decimal | None = None
    estimated_residual_cash: Decimal | None = None  # before transaction costs
    order_request: OrderRequest | None = None


def _no(c, rd, outcome, reason, price=None) -> SizingDecision:  # noqa: ANN001
    return SizingDecision(str(getattr(c, "candidate_id", "UNKNOWN_CANDIDATE")),
                          str(getattr(rd, "risk_decision_id", "UNKNOWN_RISK_DECISION")),
                          outcome, reason, reference_price=price)  # fmt: skip


def _floor(x: Decimal) -> int:
    return int(x.to_integral_value(rounding="ROUND_FLOOR"))


def size_order(
    candidate: CandidateTrade, risk_decision: RiskDecision, inputs: SizingInputs, config: SizingConfig
) -> SizingDecision:
    """Never raises. Anything not provably valid -> no OrderRequest."""
    try:
        return _size(candidate, risk_decision, inputs, config)
    except Exception as e:  # noqa: BLE001
        return _no(candidate, risk_decision, SizingOutcome.REJECTED_INVALID_INPUT,
                   f"sizing error: {type(e).__name__}: {e}")  # fmt: skip


def _size(c: CandidateTrade, rd: RiskDecision, inp: SizingInputs, cfg: SizingConfig) -> SizingDecision:
    # 1. approval is verified, never assumed (veto cannot become an order)
    if not isinstance(rd, RiskDecision) or rd.final_verdict is not RiskVerdict.APPROVE:
        return _no(c, rd, SizingOutcome.REFUSED_NOT_APPROVED, "risk decision is not an APPROVE")
    if not isinstance(c, CandidateTrade) or rd.candidate_trade_id != c.candidate_id:
        return _no(c, rd, SizingOutcome.REFUSED_NOT_APPROVED, "risk decision does not belong to this candidate")
    if any(not k.passed for k in rd.checks_evaluated) or rd.approved_qty is None or rd.approved_qty < 1:
        return _no(c, rd, SizingOutcome.REFUSED_NOT_APPROVED, "risk decision carries a failed check or no ceiling")
    errs = cfg.validate()
    if errs:
        return _no(c, rd, SizingOutcome.REJECTED_INVALID_INPUT, "invalid sizing config: " + "; ".join(errs))
    if c.action not in (Action.BUY, Action.SELL):
        return _no(c, rd, SizingOutcome.NO_TRADE, f"{c.action.value} requests no order")

    # 2. inputs
    p, eq, pf = inp.reference_price, inp.equity, inp.portfolio
    if not isinstance(p, Decimal) or not p.is_finite() or p <= 0:
        return _no(c, rd, SizingOutcome.REJECTED_INVALID_INPUT, f"invalid reference price {p!r}")
    if not isinstance(eq, Decimal) or not eq.is_finite() or eq <= 0:
        return _no(c, rd, SizingOutcome.REJECTED_INVALID_INPUT, f"invalid equity {eq!r}", p)
    if not isinstance(pf, PortfolioState):
        return _no(c, rd, SizingOutcome.REJECTED_INVALID_INPUT, "portfolio state missing", p)
    h = c.size_hint
    if isinstance(h, bool) or not isinstance(h, (int, float)) or not math.isfinite(h) or not (0 <= h <= 1):
        return _no(c, rd, SizingOutcome.REJECTED_INVALID_INPUT, f"invalid size_hint {h!r}", p)
    for n in (inp.pending_buy_qty, inp.pending_sell_qty):
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            return _no(c, rd, SizingOutcome.REJECTED_INVALID_INPUT, "invalid pending quantity", p)

    held_pos = pf.position_for(c.instrument_id)
    held = int(held_pos.quantity) if held_pos is not None else 0
    keep = Decimal(1) - Decimal(cfg.cash_buffer)
    target_value = Decimal(str(h)) * eq * keep
    ceiling = int(rd.approved_qty)
    cash = Decimal(str(pf.cash_balance))
    min_notional = Decimal(cfg.min_trade_notional)

    if c.action is Action.BUY:
        effective = held + inp.pending_buy_qty - inp.pending_sell_qty
        delta = target_value - Decimal(effective) * p
        want = _floor(delta / p) if delta > 0 else 0
        cash_avail = cash + Decimal(inp.pending_sell_qty) * p - Decimal(inp.pending_buy_qty) * p
        afford = _floor(cash_avail / p) if cash_avail > 0 else 0
        qty = max(0, min(want, ceiling, afford))
        if qty <= 0:
            why = "already at/above target" if want <= 0 else ("insufficient cash" if afford <= 0 else "risk ceiling")
            return SizingDecision(c.candidate_id, rd.risk_decision_id, SizingOutcome.NO_TRADE,
                                  f"BUY quantity is 0 ({why})", Action.BUY, 0, target_value, p,
                                  cash)  # fmt: skip
        if Decimal(qty) * p < min_notional:
            return SizingDecision(c.candidate_id, rd.risk_decision_id, SizingOutcome.NO_TRADE,
                                  "BUY below minimum trade notional", Action.BUY, 0, target_value, p, cash)  # fmt: skip
        side = Action.BUY
        residual = cash - Decimal(qty) * p
    else:
        effective = held - inp.pending_sell_qty
        if effective <= 0:
            return SizingDecision(c.candidate_id, rd.risk_decision_id, SizingOutcome.NO_TRADE,
                                  "nothing unencumbered to sell", Action.SELL, 0, target_value, p, cash)  # fmt: skip
        full_exit = h == 0
        keep_qty = 0 if full_exit else _floor(target_value / p)
        qty = max(0, min(effective - keep_qty, ceiling, effective))
        if qty <= 0:
            return SizingDecision(c.candidate_id, rd.risk_decision_id, SizingOutcome.NO_TRADE,
                                  "SELL quantity is 0 (already at/below target)", Action.SELL, 0, target_value, p, cash)  # fmt: skip
        if not full_exit and Decimal(qty) * p < min_notional:
            return SizingDecision(c.candidate_id, rd.risk_decision_id, SizingOutcome.NO_TRADE,
                                  "SELL below minimum trade notional", Action.SELL, 0, target_value, p, cash)  # fmt: skip
        side = Action.SELL
        residual = cash + Decimal(qty) * p

    req = OrderRequest(
        instrument_id=c.instrument_id,
        side=side,
        quantity=float(qty),
        order_type=OrderType.MARKET,
        risk_decision_id=rd.risk_decision_id,
        idempotency_key="idem_" + hash_json_stable([inp.research_run_id, c.candidate_id, side.value])[:24],
    )
    return SizingDecision(c.candidate_id, rd.risk_decision_id, SizingOutcome.ORDER,
                          f"{side.value} {qty} @ ref {p} (target value {target_value:.2f}, ceiling {ceiling})",
                          side, qty, target_value, p, residual, req)  # fmt: skip
