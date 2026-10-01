"""Minimal deterministic research portfolio (Slice 5, spec §11, §16, §17).

This is RESEARCH ACCOUNTING, not the production Risk Engine: no margin, no
leverage, no exposure/drawdown limits, no kill switch. It enforces only
accounting correctness — cash cannot go negative, positions cannot go negative,
integer share quantities — and fails closed (raises `ResearchRunFailure`).

All money is `decimal.Decimal`. Transaction costs are deducted from cash, so
equity genuinely reflects them (spec §16).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from research.harness.failures import FailureCategory, ResearchRunFailure

ZERO = Decimal("0")


@dataclass
class _Holding:
    quantity: int
    cost_basis: Decimal  # total gross cost of currently-held shares, EXCLUDING fees

    @property
    def avg_cost(self) -> Decimal:
        return self.cost_basis / Decimal(self.quantity) if self.quantity else ZERO


@dataclass(frozen=True)
class PortfolioChange:
    """What a single simulated transaction did to the portfolio (spec §26)."""

    instrument_id: str
    side: str
    quantity: int
    price: Decimal
    gross_turnover: Decimal
    cost: Decimal
    cash_before: Decimal
    cash_after: Decimal
    position_before: int
    position_after: int
    realized_pnl_gross: Decimal


class ResearchPortfolio:
    def __init__(self, initial_capital: Decimal) -> None:
        if not isinstance(initial_capital, Decimal) or not initial_capital.is_finite():
            raise ResearchRunFailure(
                FailureCategory.INVALID_CONFIGURATION, "initial_capital must be a finite Decimal"
            )
        if initial_capital <= 0:
            raise ResearchRunFailure(
                FailureCategory.INVALID_CONFIGURATION,
                f"initial_capital must be positive, got {initial_capital}",
            )
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self._holdings: dict[str, _Holding] = {}
        self.cumulative_costs = ZERO
        self.cumulative_turnover = ZERO
        self.realized_pnl_gross = ZERO
        self.transaction_count = 0

    # --- queries -----------------------------------------------------------
    def quantity(self, instrument_id: str) -> int:
        h = self._holdings.get(instrument_id)
        return h.quantity if h else 0

    def held_instruments(self) -> list[str]:
        return sorted(i for i, h in self._holdings.items() if h.quantity > 0)

    def market_value(self, marks: dict[str, Decimal]) -> Decimal:
        total = ZERO
        for inst in self.held_instruments():
            if inst not in marks:
                raise ResearchRunFailure(
                    FailureCategory.MISSING_DATA,
                    f"no mark price supplied for held instrument {inst!r}",
                    instrument_id=inst,
                )
            total += Decimal(self._holdings[inst].quantity) * marks[inst]
        return total

    def equity(self, marks: dict[str, Decimal]) -> Decimal:
        return self.cash + self.market_value(marks)

    def unrealized_pnl_gross(self, marks: dict[str, Decimal]) -> Decimal:
        total = ZERO
        for inst in self.held_instruments():
            h = self._holdings[inst]
            total += Decimal(h.quantity) * marks[inst] - h.cost_basis
        return total

    def positions_snapshot(self) -> list[dict]:
        return [
            {
                "instrument_id": i,
                "quantity": self._holdings[i].quantity,
                "avg_cost": str(self._holdings[i].avg_cost),
            }
            for i in self.held_instruments()
        ]

    # --- mutations -----------------------------------------------------------
    @staticmethod
    def _check_qty_price(quantity: object, price: object, cost: object) -> None:
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ResearchRunFailure(
                FailureCategory.ACCOUNTING_ERROR,
                f"transaction quantity must be a positive integer, got {quantity!r}",
            )
        if not isinstance(price, Decimal) or not price.is_finite() or price <= 0:
            raise ResearchRunFailure(
                FailureCategory.ACCOUNTING_ERROR,
                f"transaction price must be a positive finite Decimal, got {price!r}",
            )
        if not isinstance(cost, Decimal) or not cost.is_finite() or cost < 0:
            raise ResearchRunFailure(
                FailureCategory.ACCOUNTING_ERROR,
                f"transaction cost must be a non-negative finite Decimal, got {cost!r}",
            )

    def buy(self, instrument_id: str, quantity: int, price: Decimal, cost: Decimal) -> PortfolioChange:
        self._check_qty_price(quantity, price, cost)
        turnover = Decimal(quantity) * price
        needed = turnover + cost
        if needed > self.cash:
            raise ResearchRunFailure(
                FailureCategory.INSUFFICIENT_CASH,
                f"BUY {quantity} {instrument_id} needs {needed} (turnover {turnover} + costs "
                f"{cost}) but only {self.cash} cash is available",
                instrument_id=instrument_id,
                needed=str(needed),
                available=str(self.cash),
            )
        before_cash, before_qty = self.cash, self.quantity(instrument_id)
        h = self._holdings.setdefault(instrument_id, _Holding(0, ZERO))
        h.quantity += quantity
        h.cost_basis += turnover
        self.cash -= needed
        self._book(turnover, cost)
        return PortfolioChange(
            instrument_id, "BUY", quantity, price, turnover, cost,
            before_cash, self.cash, before_qty, h.quantity, ZERO,
        )  # fmt: skip

    def sell(self, instrument_id: str, quantity: int, price: Decimal, cost: Decimal) -> PortfolioChange:
        self._check_qty_price(quantity, price, cost)
        held = self.quantity(instrument_id)
        if quantity > held:
            raise ResearchRunFailure(
                FailureCategory.INSUFFICIENT_POSITION,
                f"SELL {quantity} {instrument_id} exceeds held quantity {held}",
                instrument_id=instrument_id,
                requested=quantity,
                held=held,
            )
        turnover = Decimal(quantity) * price
        if cost > turnover:
            # Proceeds would not cover the sale's own charges: refuse to let cash go negative.
            if turnover - cost + self.cash < 0:
                raise ResearchRunFailure(
                    FailureCategory.INSUFFICIENT_CASH,
                    f"SELL {quantity} {instrument_id}: costs {cost} exceed proceeds {turnover} "
                    f"and cash {self.cash} cannot absorb the shortfall",
                    instrument_id=instrument_id,
                )
        before_cash = self.cash
        h = self._holdings[instrument_id]
        avg = h.avg_cost
        realized = (price - avg) * Decimal(quantity)
        h.quantity -= quantity
        h.cost_basis -= avg * Decimal(quantity)
        if h.quantity == 0:
            h.cost_basis = ZERO
        self.cash += turnover - cost
        self.realized_pnl_gross += realized
        self._book(turnover, cost)
        return PortfolioChange(
            instrument_id, "SELL", quantity, price, turnover, cost,
            before_cash, self.cash, held, h.quantity, realized,
        )  # fmt: skip

    def _book(self, turnover: Decimal, cost: Decimal) -> None:
        self.cumulative_costs += cost
        self.cumulative_turnover += turnover
        self.transaction_count += 1
        if self.cash < 0:  # defensive; unreachable given the checks above
            raise ResearchRunFailure(
                FailureCategory.ACCOUNTING_ERROR, f"cash became negative: {self.cash}"
            )
