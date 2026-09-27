"""
Shared, broker-independent, strategy-independent India-equity Cost Model.

Public API:
    CostInputs, CostEstimate, TransactionSide, TradeType   (models)
    IndiaEquityCostSchedule, ScheduleRegistry, default_registry,
    INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED                    (schedule)
    CostModel                                              (calculator)

See docs/cost-model.md for the full contract, rate provenance, and
rounding/versioning policy.
"""

from .calculator import CostModel
from .models import CostEstimate, CostInputs, TradeType, TransactionSide
from .schedule import (
    INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED,
    IndiaEquityCostSchedule,
    ScheduleRegistry,
    default_registry,
)

__all__ = [
    "CostModel",
    "CostInputs",
    "CostEstimate",
    "TransactionSide",
    "TradeType",
    "IndiaEquityCostSchedule",
    "ScheduleRegistry",
    "default_registry",
    "INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED",
]
