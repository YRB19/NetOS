from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from markets.lane import MarketLane


class PredictionStatus(str, Enum):  # noqa: UP042
    ISSUED = "ISSUED"
    NO_SIGNAL = "NO_SIGNAL"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    REJECTED_OUTPUT = "REJECTED_OUTPUT"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class Direction(str, Enum):  # noqa: UP042
    UP = "UP"
    DOWN = "DOWN"
    FLAT = "FLAT"


class ConfidenceSemantics(str, Enum):  # noqa: UP042
    UNDEFINED = "UNDEFINED"  # default: confidence is an ordinal score, NOT a probability
    CALIBRATED_PROBABILITY_CLAIMED = "CALIBRATED_PROBABILITY_CLAIMED"  # P(direction) — must be tested


class Designation(str, Enum):  # noqa: UP042
    EXPLORATORY = "EXPLORATORY"
    VALIDATION = "VALIDATION"
    CONFIRMATORY = "CONFIRMATORY"


class PredictionEventType(str, Enum):  # noqa: UP042
    RECORDED = "PREDICTION_RECORDED"
    CORRECTED = "PREDICTION_CORRECTED"
    INVALIDATED = "PREDICTION_INVALIDATED"
    REJECTED_LATE = "PREDICTION_REJECTED_LATE"


def _utc(n: str, v: datetime) -> None:
    if v.tzinfo is None or v.utcoffset() != UTC.utcoffset(None):
        raise ValueError(f"{n} must be timezone-aware UTC")


@dataclass(frozen=True)
class PredictionRecord:
    prediction_id: str
    correlation_id: str
    lane: MarketLane
    instrument_id: str
    universe_version: str
    session_id: str
    created_at: datetime
    input_available_at: datetime
    valid_from: datetime
    valid_until: datetime
    horizon_label: str
    forecast_target: str
    status: PredictionStatus
    benchmark_id: str
    benchmark_instrument_id: str
    currency: str
    calendar_id: str
    outcome_definition: dict
    protocol_id: str
    designation: Designation
    evidence_class: str
    direction: Direction | None = None
    score: float | None = None
    confidence: float | None = None
    confidence_semantics: ConfidenceSemantics = ConfidenceSemantics.UNDEFINED
    status_reason: str = ""
    feature_snapshot_ids: tuple[str, ...] = ()
    input_hashes: tuple[str, ...] = ()
    disclosure_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    ai_provider: str = ""
    requested_model: str = ""
    returned_model: str = ""
    prompt_template_version: str = ""
    output_schema_version: str = ""
    config_hash: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        for n in ("created_at", "input_available_at", "valid_from", "valid_until"):
            _utc(n, getattr(self, n))
        for n in ("prediction_id", "instrument_id", "session_id", "protocol_id", "currency", "benchmark_id"):
            if not getattr(self, n):
                raise ValueError(f"{n} must be non-empty")
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be after valid_from")
        if self.input_available_at > self.created_at:
            raise ValueError("inputs must be available before the prediction is created")
        if self.status is PredictionStatus.ISSUED and self.direction is None:
            raise ValueError("ISSUED prediction requires a direction")
        if self.status is not PredictionStatus.ISSUED and self.direction is not None:
            raise ValueError("non-ISSUED prediction must not carry a direction")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if (
            self.confidence_semantics is ConfidenceSemantics.CALIBRATED_PROBABILITY_CLAIMED
            and self.confidence is None
        ):
            raise ValueError("probability semantics claimed but no confidence given")

    def to_dict(self) -> dict:
        d: dict = {}
        for k, v in self.__dict__.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat()
            elif isinstance(v, Enum):
                d[k] = v.value
            elif isinstance(v, tuple):
                d[k] = list(v)
            else:
                d[k] = v
        return d

    @staticmethod
    def from_dict(d: dict) -> PredictionRecord:
        kw = dict(d)
        for n in ("created_at", "input_available_at", "valid_from", "valid_until"):
            kw[n] = datetime.fromisoformat(kw[n])
        kw["lane"] = MarketLane(kw["lane"])
        kw["status"] = PredictionStatus(kw["status"])
        kw["designation"] = Designation(kw["designation"])
        kw["confidence_semantics"] = ConfidenceSemantics(kw["confidence_semantics"])
        kw["direction"] = Direction(kw["direction"]) if kw.get("direction") else None
        for n in ("feature_snapshot_ids", "input_hashes", "disclosure_ids", "evidence_refs"):
            kw[n] = tuple(kw.get(n, ()))
        return PredictionRecord(**kw)
