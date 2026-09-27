"""DecisionRecord (Stage 3 §2, §4) — the single structured artifact that
answers every Stage 2 §12 observability question without re-derivation.

Per §4: "It is not a log line; it is a first-class, versioned object
assembled incrementally as a decision cycle proceeds through the planes,
and only marked 'finalized' once the cycle completes." This module
provides:

  - `DecisionRecord`: the immutable, finalized artifact (frozen dataclass,
    matching the §4 schema field-for-field).
  - `DecisionRecordBuilder`: a mutable, in-progress accumulator used while
    a single decision cycle is being processed across planes; it produces
    a `DecisionRecord` only via `.finalize()`.

No persistence (a decision-log store) is implemented in this slice —
Stage 3 §18/§20's `observability/decision_log/` module is later work.
This module only defines the shape and finalization discipline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from domain.models._validators import require_aware_utc, require_non_empty_str, require_uuid_like
from domain.models.enums import TerminalState
from domain.models.order_request import Fill
from shared.time.clock import utc_now
from shared.versioning.identifiers import new_id


@dataclass(frozen=True, slots=True)
class DataSourceRef:
    source: str
    version: str
    timestamp: datetime

    def __post_init__(self) -> None:
        require_non_empty_str(self.source, "source")
        require_non_empty_str(self.version, "version")
        object.__setattr__(self, "timestamp", require_aware_utc(self.timestamp, "timestamp"))


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    instrument_id: str
    cycle_timestamp: datetime
    autonomy_level: int  # 0-3, AR-5
    input_snapshot_id: str
    data_sources: tuple[DataSourceRef, ...]
    terminal_state: TerminalState
    risk_rule_version_id: str  # always present, even on HOLD/no-candidate cycles
    config_version_id: str
    decision_id: str = field(default_factory=new_id)
    candidate_trade_id: str | None = None
    rationale: str | None = None
    strategy_version_id: str | None = None
    model_version_id: str | None = None
    cost_estimate_id: str | None = None
    risk_decision_id: str | None = None
    order_request_id: str | None = None
    order_id: str | None = None
    fills: tuple[Fill, ...] = field(default_factory=tuple)
    actual_cost_id: str | None = None
    realized_pnl_delta: float | None = None
    finalized_at: datetime | None = None

    def __post_init__(self) -> None:
        require_non_empty_str(self.instrument_id, "instrument_id")
        object.__setattr__(
            self, "cycle_timestamp", require_aware_utc(self.cycle_timestamp, "cycle_timestamp")
        )
        if not isinstance(self.autonomy_level, int) or not (0 <= self.autonomy_level <= 3):
            raise ValueError(f"autonomy_level must be an int in 0..3, got: {self.autonomy_level!r}")
        require_uuid_like(self.input_snapshot_id, "input_snapshot_id")
        if not isinstance(self.data_sources, tuple) or not all(
            isinstance(d, DataSourceRef) for d in self.data_sources
        ):
            raise ValueError("data_sources must be a tuple of DataSourceRef instances")
        if not isinstance(self.terminal_state, TerminalState):
            raise ValueError(
                f"terminal_state must be a TerminalState, got: {self.terminal_state!r}"
            )
        require_uuid_like(self.risk_rule_version_id, "risk_rule_version_id")
        require_uuid_like(self.config_version_id, "config_version_id")
        require_uuid_like(self.decision_id, "decision_id")

        if not isinstance(self.fills, tuple) or not all(isinstance(f, Fill) for f in self.fills):
            raise ValueError("fills must be a tuple of Fill instances")

        if self.finalized_at is not None:
            object.__setattr__(
                self, "finalized_at", require_aware_utc(self.finalized_at, "finalized_at")
            )

        # Cross-field consistency: a HOLD/no-candidate cycle must not carry
        # downstream artifacts that could only exist if a candidate was
        # actually produced (TR-4: hold is a first-class decision, not a
        # silent no-op, but it is still a decision with no order path).
        if self.terminal_state == TerminalState.NO_CANDIDATE:
            if self.candidate_trade_id is not None or self.order_id is not None:
                raise ValueError(
                    "terminal_state=NO_CANDIDATE must not reference a candidate_trade_id "
                    "or order_id."
                )

    def is_finalized(self) -> bool:
        return self.finalized_at is not None


@dataclass
class DecisionRecordBuilder:
    """Mutable accumulator for a single in-progress decision cycle.

    Each plane calls the corresponding `with_*` method as the cycle
    proceeds; `.finalize()` produces the immutable `DecisionRecord` and is
    the only way to obtain one from a builder. Calling `.finalize()` twice
    raises, since a DecisionRecord must be produced exactly once per cycle.
    """

    instrument_id: str
    cycle_timestamp: datetime
    autonomy_level: int
    risk_rule_version_id: str
    config_version_id: str
    input_snapshot_id: str | None = None
    data_sources: list[DataSourceRef] = field(default_factory=list)
    candidate_trade_id: str | None = None
    rationale: str | None = None
    strategy_version_id: str | None = None
    model_version_id: str | None = None
    cost_estimate_id: str | None = None
    risk_decision_id: str | None = None
    order_request_id: str | None = None
    order_id: str | None = None
    fills: list[Fill] = field(default_factory=list)
    actual_cost_id: str | None = None
    realized_pnl_delta: float | None = None
    _finalized: bool = False

    def with_snapshot(
        self, snapshot_id: str, sources: list[DataSourceRef]
    ) -> DecisionRecordBuilder:
        self.input_snapshot_id = snapshot_id
        self.data_sources.extend(sources)
        return self

    def with_candidate(
        self,
        candidate_trade_id: str,
        rationale: str,
        strategy_version_id: str,
        model_version_id: str | None = None,
    ) -> DecisionRecordBuilder:
        self.candidate_trade_id = candidate_trade_id
        self.rationale = rationale
        self.strategy_version_id = strategy_version_id
        self.model_version_id = model_version_id
        return self

    def with_cost_estimate(self, cost_estimate_id: str) -> DecisionRecordBuilder:
        self.cost_estimate_id = cost_estimate_id
        return self

    def with_risk_decision(self, risk_decision_id: str) -> DecisionRecordBuilder:
        self.risk_decision_id = risk_decision_id
        return self

    def with_order(self, order_request_id: str, order_id: str) -> DecisionRecordBuilder:
        self.order_request_id = order_request_id
        self.order_id = order_id
        return self

    def with_fill(self, fill: Fill) -> DecisionRecordBuilder:
        self.fills.append(fill)
        return self

    def with_outcome(self, actual_cost_id: str, realized_pnl_delta: float) -> DecisionRecordBuilder:
        self.actual_cost_id = actual_cost_id
        self.realized_pnl_delta = realized_pnl_delta
        return self

    def finalize(self, terminal_state: TerminalState) -> DecisionRecord:
        if self._finalized:
            raise ValueError("This DecisionRecordBuilder has already been finalized.")
        if self.input_snapshot_id is None:
            raise ValueError(
                "Cannot finalize a DecisionRecord without an input_snapshot_id "
                "(every decision, including a HOLD/no-candidate cycle, must "
                "reference what Plane 1 data it was evaluated against)."
            )
        record = DecisionRecord(
            instrument_id=self.instrument_id,
            cycle_timestamp=self.cycle_timestamp,
            autonomy_level=self.autonomy_level,
            input_snapshot_id=self.input_snapshot_id,
            data_sources=tuple(self.data_sources),
            terminal_state=terminal_state,
            risk_rule_version_id=self.risk_rule_version_id,
            config_version_id=self.config_version_id,
            candidate_trade_id=self.candidate_trade_id,
            rationale=self.rationale,
            strategy_version_id=self.strategy_version_id,
            model_version_id=self.model_version_id,
            cost_estimate_id=self.cost_estimate_id,
            risk_decision_id=self.risk_decision_id,
            order_request_id=self.order_request_id,
            order_id=self.order_id,
            fills=tuple(self.fills),
            actual_cost_id=self.actual_cost_id,
            realized_pnl_delta=self.realized_pnl_delta,
            finalized_at=utc_now(),
        )
        self._finalized = True
        return record
