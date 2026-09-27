"""Domain model package (Stage 3 §2).

Pure data structures, no logic, no I/O — see the module docstring in each
submodule for the specific object it defines. This `__init__.py` re-exports
the full public surface so callers can write:

    from domain.models import CandidateTrade, Action, ...

rather than needing to know which submodule each class lives in.
"""

from domain.models.autonomy import LEVEL_NAMES, MAX_LEVEL, MIN_LEVEL, AutonomyLevel
from domain.models.candidate_trade import CandidateTrade
from domain.models.cost import ActualCost, CostEstimate
from domain.models.decision_record import DataSourceRef, DecisionRecord, DecisionRecordBuilder
from domain.models.enums import (
    Action,
    FillType,
    OrderState,
    PortfolioStateSource,
    PositionSide,
    PromotionDecision,
    RiskVerdict,
    Segment,
    TerminalState,
    UncertaintyBand,
)
from domain.models.feature_snapshot import FeatureSnapshot
from domain.models.instrument import Instrument
from domain.models.market_data import MarketData
from domain.models.order import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    InvalidOrderTransition,
    Order,
    StateTransitionRecord,
)
from domain.models.order_request import Fill, OrderRequest, OrderType
from domain.models.portfolio import PortfolioState, Position
from domain.models.promotion import PromotionCandidate
from domain.models.research_artifacts import (
    ContaminationCheckResult,
    EvaluationRun,
    Experiment,
    SplitSpec,
)
from domain.models.risk_decision import RiskCheckResult, RiskDecision
from domain.models.versions import (
    ConfigurationVersion,
    ModelVersion,
    Plane2Type,
    PromotionStatus,
    RiskRuleVersion,
    StrategyVersion,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "LEVEL_NAMES",
    "MAX_LEVEL",
    "MIN_LEVEL",
    "TERMINAL_STATES",
    "Action",
    "ActualCost",
    "AutonomyLevel",
    "CandidateTrade",
    "ConfigurationVersion",
    "ContaminationCheckResult",
    "CostEstimate",
    "DataSourceRef",
    "DecisionRecord",
    "DecisionRecordBuilder",
    "EvaluationRun",
    "Experiment",
    "FeatureSnapshot",
    "Fill",
    "FillType",
    "Instrument",
    "InvalidOrderTransition",
    "MarketData",
    "ModelVersion",
    "Order",
    "OrderRequest",
    "OrderState",
    "OrderType",
    "Plane2Type",
    "Position",
    "PortfolioState",
    "PortfolioStateSource",
    "PositionSide",
    "PromotionCandidate",
    "PromotionDecision",
    "PromotionStatus",
    "RiskCheckResult",
    "RiskDecision",
    "RiskRuleVersion",
    "RiskVerdict",
    "Segment",
    "SplitSpec",
    "StateTransitionRecord",
    "StrategyVersion",
    "TerminalState",
    "UncertaintyBand",
]

from domain.models.feature_snapshot import MarketDataRef
from domain.models.raw_observation import RawMarketObservation

__all__ += ["RawMarketObservation", "MarketDataRef"]
