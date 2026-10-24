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
from decimal import Decimal, InvalidOperation
from enum import Enum

from research.harness.failures import FailureCategory, ResearchRunFailure
from research.harness.portfolio_checkpoint import PortfolioCheckpointStore
from shared.versioning.content_hash import hash_json_stable

ZERO = Decimal("0")
SNAPSHOT_VERSION = 1
_SIDES = ("BUY", "SELL")


def _dstr(d: Decimal) -> str:
    """Canonical plain-notation string (Decimal('50.0') and Decimal('50') fingerprint identically)."""
    return format(d.normalize(), "f") if d != 0 else "0"


class FillApplyStatus(str, Enum):  # noqa: UP042 - matches repository enum convention
    APPLIED = "APPLIED"
    ALREADY_APPLIED = "ALREADY_APPLIED"


@dataclass(frozen=True)
class _LedgerEntry:
    fill_id: str
    fingerprint: str
    instrument_id: str
    side: str
    quantity: int
    price: Decimal
    cost: Decimal
    order_id: str | None = None   # provenance only: stored, NOT part of the fingerprint
    source: str | None = None


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


@dataclass(frozen=True)
class FillApplication:
    """Outcome of `apply_fill`. `change` is None when the fill had already been booked (no effect this call)."""

    status: FillApplyStatus
    fill_id: str
    fingerprint: str
    change: PortfolioChange | None = None


def _cp_err(msg: str, **ctx: object) -> ResearchRunFailure:
    return ResearchRunFailure(FailureCategory.PORTFOLIO_CHECKPOINT_ERROR, msg, **ctx)


class ResearchPortfolio:
    def __init__(self, initial_capital: Decimal, checkpoint: PortfolioCheckpointStore | None = None) -> None:
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
        self._applied: dict[str, _LedgerEntry] = {}   # fill_id -> entry, in application order (ADR-13)
        self._checkpoint = checkpoint
        if checkpoint is not None:
            if checkpoint.exists():  # never overwrite durable state with an empty portfolio
                raise _cp_err("a portfolio checkpoint already exists; use ResearchPortfolio.restore_from_store",
                              path=str(checkpoint.path))
            checkpoint.write(self.snapshot())

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

    def _guard_direct(self) -> None:
        if self._checkpoint is not None:
            raise ResearchRunFailure(
                FailureCategory.ACCOUNTING_ERROR,
                "direct buy/sell is not permitted on a checkpointed portfolio: use apply_fill (idempotent, durable)",
            )

    def buy(
        self, instrument_id: str, quantity: int, price: Decimal, cost: Decimal
    ) -> PortfolioChange:
        self._guard_direct()
        return self._buy(instrument_id, quantity, price, cost)

    def sell(
        self, instrument_id: str, quantity: int, price: Decimal, cost: Decimal
    ) -> PortfolioChange:
        self._guard_direct()
        return self._sell(instrument_id, quantity, price, cost)

    def _buy(
        self, instrument_id: str, quantity: int, price: Decimal, cost: Decimal
    ) -> PortfolioChange:
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

    def _sell(
        self, instrument_id: str, quantity: int, price: Decimal, cost: Decimal
    ) -> PortfolioChange:
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

    # --- idempotent fill application + durable state (Slice 7 final closure, ADR-13) ---------------------------
    @staticmethod
    def fill_fingerprint(fill_id: str, instrument_id: str, side: str, quantity: int, price: Decimal,
                         cost: Decimal) -> str:
        return hash_json_stable({"fill_id": fill_id, "instrument_id": instrument_id, "side": side,
                                 "quantity": quantity, "price": _dstr(price), "cost": _dstr(cost)})

    def applied_fill_ids(self) -> tuple[str, ...]:
        return tuple(self._applied)

    def has_applied(self, fill_id: str) -> bool:
        return fill_id in self._applied

    def apply_fill(self, fill_id: str, instrument_id: str, side: object, quantity: int, price: Decimal,
                   cost: Decimal, *, order_id: str | None = None, source: str | None = None) -> FillApplication:
        """Book one fill's financial effect exactly once, keyed by its stable fill_id.

        Same fill_id + same material payload  -> ALREADY_APPLIED, nothing changes (duplicate is not an error).
        Same fill_id + different payload      -> fail closed (ACCOUNTING_ERROR); nothing changes.
        Otherwise the existing accounting rules (`_buy`/`_sell`) are run on a copy; if a checkpoint store is
        configured the new state (financials + applied-fill ledger) is written as ONE atomic file; only after that
        succeeds does the live object adopt the new state. A failed write raises and leaves this object, and the
        fill's eligibility to be applied later, untouched. Cash/position/cost/turnover/realized-P&L effects and the
        ledger entry therefore commit together or not at all."""
        if not isinstance(fill_id, str) or not fill_id:
            raise ResearchRunFailure(FailureCategory.ACCOUNTING_ERROR, f"fill_id must be a non-empty string, got {fill_id!r}")
        if not isinstance(instrument_id, str) or not instrument_id:
            raise ResearchRunFailure(FailureCategory.ACCOUNTING_ERROR,
                                     f"instrument_id must be a non-empty string, got {instrument_id!r}", fill_id=fill_id)
        side_v = getattr(side, "value", side)
        if side_v not in _SIDES:
            raise ResearchRunFailure(FailureCategory.ACCOUNTING_ERROR, f"fill side must be BUY or SELL, got {side!r}",
                                     fill_id=fill_id)
        for name, v in (("order_id", order_id), ("source", source)):
            if v is not None and not isinstance(v, str):
                raise ResearchRunFailure(FailureCategory.ACCOUNTING_ERROR, f"{name} must be a string or None", fill_id=fill_id)
        self._check_qty_price(quantity, price, cost)
        fp = self.fill_fingerprint(fill_id, instrument_id, side_v, quantity, price, cost)
        prior = self._applied.get(fill_id)
        if prior is not None:
            if prior.fingerprint != fp:
                raise ResearchRunFailure(
                    FailureCategory.ACCOUNTING_ERROR,
                    f"fill_id {fill_id!r} was already applied with a DIFFERENT payload: refusing (reconciliation required)",
                    fill_id=fill_id, applied_fingerprint=prior.fingerprint, offered_fingerprint=fp)
            return FillApplication(FillApplyStatus.ALREADY_APPLIED, fill_id, fp, None)

        trial = self._copy()
        change = trial._buy(instrument_id, quantity, price, cost) if side_v == "BUY" \
            else trial._sell(instrument_id, quantity, price, cost)
        trial._applied[fill_id] = _LedgerEntry(fill_id, fp, instrument_id, side_v, quantity, price, cost, order_id, source)
        if self._checkpoint is not None:
            self._checkpoint.write(trial.snapshot())   # raises on failure: nothing below runs, nothing is adopted
        self._adopt(trial)
        return FillApplication(FillApplyStatus.APPLIED, fill_id, fp, change)

    def _copy(self) -> ResearchPortfolio:
        c = ResearchPortfolio(self.initial_capital)
        c.cash = self.cash
        c._holdings = {k: _Holding(h.quantity, h.cost_basis) for k, h in self._holdings.items()}
        c.cumulative_costs, c.cumulative_turnover = self.cumulative_costs, self.cumulative_turnover
        c.realized_pnl_gross, c.transaction_count = self.realized_pnl_gross, self.transaction_count
        c._applied = dict(self._applied)
        return c

    def _adopt(self, other: ResearchPortfolio) -> None:
        self.cash, self._holdings = other.cash, other._holdings
        self.cumulative_costs, self.cumulative_turnover = other.cumulative_costs, other.cumulative_turnover
        self.realized_pnl_gross, self.transaction_count = other.realized_pnl_gross, other.transaction_count
        self._applied = other._applied

    def snapshot(self) -> dict:
        """Checksummed, JSON-safe image of every field needed to restore this portfolio faithfully."""
        if self.transaction_count != len(self._applied):
            raise ResearchRunFailure(
                FailureCategory.ACCOUNTING_ERROR,
                "portfolio holds transactions that were not applied via apply_fill: it cannot be checkpointed faithfully",
                transactions=self.transaction_count, ledger=len(self._applied))
        body = {
            "kind": "research_portfolio", "version": SNAPSHOT_VERSION,
            "initial_capital": _dstr(self.initial_capital), "cash": _dstr(self.cash),
            "holdings": {i: {"quantity": h.quantity, "cost_basis": _dstr(h.cost_basis)}
                         for i, h in sorted(self._holdings.items()) if h.quantity > 0},
            "cumulative_costs": _dstr(self.cumulative_costs), "cumulative_turnover": _dstr(self.cumulative_turnover),
            "realized_pnl_gross": _dstr(self.realized_pnl_gross), "transaction_count": self.transaction_count,
            "applied_fills": [{"fill_id": e.fill_id, "fingerprint": e.fingerprint, "instrument_id": e.instrument_id,
                               "side": e.side, "quantity": e.quantity, "price": _dstr(e.price), "cost": _dstr(e.cost),
                               "order_id": e.order_id, "source": e.source} for e in self._applied.values()],
        }
        return {"body": body, "checksum": hash_json_stable(body)}

    @classmethod
    def restore(cls, snap: object, checkpoint: PortfolioCheckpointStore | None = None) -> ResearchPortfolio:
        """Rebuild a portfolio from a snapshot. Fails closed (PORTFOLIO_CHECKPOINT_ERROR) on a bad checksum, an
        unsupported version, malformed fields, or any disagreement between the stored financial state and the state
        obtained by independently replaying the stored applied-fill ledger from the initial capital."""
        try:
            if not isinstance(snap, dict) or not isinstance(snap.get("body"), dict) or "checksum" not in snap:
                raise _cp_err("portfolio checkpoint has no body/checksum")
            body = snap["body"]
            if hash_json_stable(body) != snap["checksum"]:
                raise _cp_err("portfolio checkpoint checksum mismatch: refusing a tampered or corrupted checkpoint")
            if body.get("kind") != "research_portfolio" or body.get("version") != SNAPSHOT_VERSION:
                raise _cp_err(f"unsupported portfolio checkpoint kind/version {body.get('kind')!r}/{body.get('version')!r}")
            capital = Decimal(body["initial_capital"])
            replay = cls(capital)
            seen: set[str] = set()
            for d in body["applied_fills"]:
                if d["fill_id"] in seen:
                    raise _cp_err(f"duplicate fill_id {d['fill_id']!r} in the applied-fill ledger")
                seen.add(d["fill_id"])
                qty, price, cost = d["quantity"], Decimal(d["price"]), Decimal(d["cost"])
                if replay.fill_fingerprint(d["fill_id"], d["instrument_id"], d["side"], qty, price, cost) != d["fingerprint"]:
                    raise _cp_err(f"ledger entry {d['fill_id']!r} does not match its stored fingerprint")
                replay.apply_fill(d["fill_id"], d["instrument_id"], d["side"], qty, price, cost,
                                  order_id=d.get("order_id"), source=d.get("source"))
            if replay.snapshot()["body"] != body:
                raise _cp_err("stored portfolio state disagrees with the state replayed from its applied-fill ledger")
        except ResearchRunFailure as e:
            if e.category is FailureCategory.PORTFOLIO_CHECKPOINT_ERROR:
                raise
            raise _cp_err(f"portfolio checkpoint inconsistent: {e.message}") from e
        except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError) as e:
            raise _cp_err(f"portfolio checkpoint malformed: {type(e).__name__}: {e}") from e
        replay._checkpoint = checkpoint
        return replay

    @classmethod
    def restore_from_store(cls, store: PortfolioCheckpointStore) -> ResearchPortfolio:
        snap = store.read()
        if snap is None:  # a missing checkpoint is NEVER treated as an empty portfolio
            raise _cp_err("no portfolio checkpoint to restore from", path=str(store.path))
        return cls.restore(snap, checkpoint=store)
