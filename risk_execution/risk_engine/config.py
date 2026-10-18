"""Risk configuration and versioning (Slice 6, Stage 3 §7/§16/§19, RR-9).

All thresholds are OPERATOR inputs (Stage 1 §12.2): there are deliberately NO default
values. Any value used in tests/demos is an explicit EXAMPLE, not an approved limit.

A RiskConfig is immutable, content-hashed, and versioned: changing any value yields a
different `risk_rule_version_id`. The engine re-verifies that hash on every evaluation
(RR-9 integrity), so a silently mutated config is detected and fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

from domain.models.versions import ConfigurationVersion, RiskRuleVersion
from shared.versioning.content_hash import hash_json_stable

CONFIG_SENTINEL_INVALID = "INVALID_RISK_CONFIG"


class KillSwitchState(str, Enum):  # noqa: UP042 - repository enum convention
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    UNKNOWN = "UNKNOWN"  # treated exactly like ACTIVE (fail closed)


def _is_decimal(v: object) -> bool:
    if isinstance(v, bool) or not isinstance(v, (Decimal, int, str)):
        return False
    try:
        return Decimal(v).is_finite()
    except (InvalidOperation, ValueError):
        return False


@dataclass(frozen=True)
class RiskConfig:
    label: str  # e.g. "risk_rules_v1"
    effective_from: datetime
    max_position_fraction: Decimal  # RR-1: per-position value / equity
    max_gross_exposure_fraction: Decimal  # RR-1: gross long exposure / equity
    max_leverage: Decimal  # RR-2: projected gross exposure / equity
    max_drawdown_fraction: Decimal  # RR-3: halt new BUYs at/after this peak-to-trough drawdown
    order_rate_window_seconds: int  # RR-5
    max_orders_per_window: int  # RR-5
    permitted_account_scope: str  # RR-6
    allow_exit_of_removed_instruments: bool  # RR-4 nuance, see docs/risk-engine.md

    def validate(self) -> list[str]:
        e: list[str] = []
        if not isinstance(self.label, str) or not self.label.strip():
            e.append("label must be a non-empty string")
        if not isinstance(self.effective_from, datetime) or self.effective_from.tzinfo is None:
            e.append("effective_from must be a timezone-aware datetime")
        for name in ("max_position_fraction", "max_drawdown_fraction"):
            v = getattr(self, name)
            if not _is_decimal(v) or not (Decimal(0) < Decimal(v) <= Decimal(1)):
                e.append(f"{name} must be a decimal in (0, 1], got {v!r}")
        for name in ("max_gross_exposure_fraction", "max_leverage"):  # both positive; the stricter binds
            v = getattr(self, name)
            if not _is_decimal(v) or Decimal(v) <= 0:
                e.append(f"{name} must be a positive decimal, got {v!r}")
        for name in ("order_rate_window_seconds", "max_orders_per_window"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                e.append(f"{name} must be a positive int, got {v!r}")
        if not isinstance(self.permitted_account_scope, str) or not self.permitted_account_scope.strip():
            e.append("permitted_account_scope must be a non-empty string")
        if not isinstance(self.allow_exit_of_removed_instruments, bool):
            e.append("allow_exit_of_removed_instruments must be a bool")
        return e

    def payload(self) -> dict:
        def s(v: object) -> str:
            return str(Decimal(v)) if _is_decimal(v) else repr(v)  # type: ignore[arg-type]

        return {
            "label": self.label,
            "effective_from": self.effective_from.isoformat()
            if isinstance(self.effective_from, datetime) else repr(self.effective_from),
            "max_position_fraction": s(self.max_position_fraction),
            "max_gross_exposure_fraction": s(self.max_gross_exposure_fraction),
            "max_leverage": s(self.max_leverage),
            "max_drawdown_fraction": s(self.max_drawdown_fraction),
            "order_rate_window_seconds": self.order_rate_window_seconds,
            "max_orders_per_window": self.max_orders_per_window,
            "permitted_account_scope": self.permitted_account_scope,
            "allow_exit_of_removed_instruments": self.allow_exit_of_removed_instruments,
        }  # fmt: skip

    def rule_set_hash(self) -> str:
        return hash_json_stable(self.payload())

    def risk_rule_version(self) -> RiskRuleVersion:
        return RiskRuleVersion(rule_set_hash=self.rule_set_hash(), effective_from=self.effective_from)

    def configuration_version(self, set_by: str = "operator") -> ConfigurationVersion:
        """Deterministic ConfigurationVersion (existing mechanism) for this risk config."""
        return ConfigurationVersion(
            values=self.payload(),
            set_by=set_by,
            effective_from=self.effective_from,
            version_id="riskcfg_" + self.rule_set_hash()[:24],
        )
