"""Currency-safe money. USD and INR must never be mixed (Slice 13 §2.1)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


class CurrencyMismatch(ValueError):  # noqa: N818 - domain term
    pass


@dataclass(frozen=True)
class LaneMoney:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise ValueError("LaneMoney.amount must be a finite Decimal")
        if not self.currency or not self.currency.isupper():
            raise ValueError("LaneMoney.currency must be an upper-case code")

    def _check(self, other: LaneMoney) -> None:
        if not isinstance(other, LaneMoney):
            raise CurrencyMismatch("cannot combine LaneMoney with a bare number")
        if other.currency != self.currency:
            raise CurrencyMismatch(f"{self.currency} and {other.currency} must never be combined")

    def __add__(self, other: LaneMoney) -> LaneMoney:
        self._check(other)
        return LaneMoney(self.amount + other.amount, self.currency)

    def __sub__(self, other: LaneMoney) -> LaneMoney:
        self._check(other)
        return LaneMoney(self.amount - other.amount, self.currency)

    def __lt__(self, other: LaneMoney) -> bool:
        self._check(other)
        return self.amount < other.amount
