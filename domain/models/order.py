"""Order (Stage 3 §2, §9) — the broker-tracked lifecycle of an OrderRequest.

This is the one domain object that is genuinely, deliberately mutable —
but only through `transition_to()`, which enforces the exact state machine
diagram in Stage 3 §9. Every transition (attempted or successful) is
recorded in `state_history`, which is append-only: history entries are
never removed or edited, only added to.

Invalid transitions raise `InvalidOrderTransition` rather than being
silently coerced — per the implementation prompt's explicit requirement
that e.g. CANDIDATE -> FILLED "must fail" and "must not silently coerce
invalid states."

RECONCILIATION_REQUIRED is treated as terminal *for automated purposes*:
resolving it requires an out-of-band reconciliation action (Stage 3 §9,
"resolves it against the broker's own order/position query endpoint"),
which is not implemented in this slice. The state machine still models the
four possible resolution outcomes as legal *targets* from
RECONCILIATION_REQUIRED, since Stage 3 describes it as resolvable, not as
a true dead end — but nothing in Slice 0/1 calls that transition
automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from domain.models._validators import require_aware_utc, require_non_empty_str, require_uuid_like
from domain.models.enums import OrderState
from shared.time.clock import utc_now
from shared.versioning.identifiers import new_id

# The exact transition table from Stage 3 §9's ASCII diagram, plus the
# explicit resolution transitions out of RECONCILIATION_REQUIRED described
# in the surrounding prose (not shown in the diagram's arrows directly, but
# stated as the mechanism by which that state is eventually resolved).
#
# AMENDMENT (Slice 7 closure, ADR-11): ACKNOWLEDGED -> CANCELLED added. Stage 1 FR-3 (Must) and the
# Stage 3 §10 broker interface (`cancel_order`) require cancelling orders; the §9 diagram only draws a
# cancel edge after a partial fill ("remaining qty cancelled"), leaving the primary case of cancelling
# a resting, entirely unfilled order unrepresentable. Only a BROKER-CONFIRMED cancel may use this edge.
# SUBMITTED -> CANCELLED is deliberately NOT added (no broker acknowledgement => stays fail-closed).
ALLOWED_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.CANDIDATE: frozenset({OrderState.APPROVED}),
    OrderState.APPROVED: frozenset({OrderState.SUBMITTED}),
    OrderState.SUBMITTED: frozenset(
        {OrderState.ACKNOWLEDGED, OrderState.REJECTED, OrderState.RECONCILIATION_REQUIRED}
    ),
    OrderState.ACKNOWLEDGED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
            OrderState.RECONCILIATION_REQUIRED,
        }
    ),
    OrderState.PARTIALLY_FILLED: frozenset(
        {OrderState.FILLED, OrderState.CANCELLED, OrderState.RECONCILIATION_REQUIRED}
    ),
    OrderState.FILLED: frozenset(),  # terminal
    OrderState.CANCELLED: frozenset(),  # terminal
    OrderState.REJECTED: frozenset(),  # terminal
    # Resolution-only transitions; not reachable via normal broker-event
    # handling in this slice (no reconciliation logic exists yet).
    OrderState.RECONCILIATION_REQUIRED: frozenset(
        {OrderState.FILLED, OrderState.PARTIALLY_FILLED, OrderState.CANCELLED, OrderState.REJECTED}
    ),
}

TERMINAL_STATES: frozenset[OrderState] = frozenset(
    {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED}
)


class InvalidOrderTransition(ValueError):
    """Raised when a transition is attempted that the state machine forbids."""

    def __init__(self, current: OrderState, attempted: OrderState) -> None:
        self.current = current
        self.attempted = attempted
        super().__init__(
            f"Invalid order state transition: {current.value} -> {attempted.value}. "
            f"Allowed from {current.value}: "
            f"{sorted(s.value for s in ALLOWED_TRANSITIONS.get(current, frozenset()))}"
        )


@dataclass(frozen=True, slots=True)
class StateTransitionRecord:
    from_state: OrderState
    to_state: OrderState
    at: datetime
    detail: str = ""


@dataclass(slots=True)
class Order:
    """Deliberately NOT frozen: `state` mutates via `transition_to()` only.

    Every other field is set once at construction and never reassigned —
    only `state` and `_state_history` change over the object's life.
    """

    order_request_id: str  # FK -> OrderRequest.idempotency_key
    order_id: str = field(default_factory=new_id)
    broker_order_id: str | None = None
    state: OrderState = OrderState.CANDIDATE
    last_broker_response: str | None = None
    _state_history: list[StateTransitionRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        require_uuid_like(self.order_request_id, "order_request_id")
        require_uuid_like(self.order_id, "order_id")
        if not isinstance(self.state, OrderState):
            raise ValueError(f"state must be an OrderState, got: {self.state!r}")
        if self.state is not OrderState.CANDIDATE:
            raise ValueError(
                "An Order must always be constructed in the CANDIDATE state and "
                "then advanced via transition_to() — constructing directly into a "
                "later state would bypass the audit trail this state machine exists "
                "to guarantee."
            )

    @property
    def state_history(self) -> tuple[StateTransitionRecord, ...]:
        """Read-only, append-only view of every transition this order has made."""
        return tuple(self._state_history)

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def transition_to(
        self, new_state: OrderState, *, detail: str = "", at: datetime | None = None
    ) -> None:
        """Advance the order's state, enforcing Stage 3 §9's transition table.

        Raises `InvalidOrderTransition` (and leaves the order's state
        unchanged) if the transition is not permitted. This is a hard
        failure by design — callers must not catch this exception and
        proceed as if the transition happened.
        """
        allowed = ALLOWED_TRANSITIONS.get(self.state, frozenset())
        if new_state not in allowed:
            raise InvalidOrderTransition(self.state, new_state)

        timestamp = require_aware_utc(at, "at") if at is not None else utc_now()
        record = StateTransitionRecord(
            from_state=self.state, to_state=new_state, at=timestamp, detail=detail
        )
        self._state_history.append(record)
        self.state = new_state

    def set_broker_order_id(self, broker_order_id: str) -> None:
        require_non_empty_str(broker_order_id, "broker_order_id")
        if self.broker_order_id is not None and self.broker_order_id != broker_order_id:
            raise ValueError(
                f"broker_order_id is already set to {self.broker_order_id!r}; "
                f"refusing to overwrite with {broker_order_id!r} "
                "(an order must correspond to exactly one broker order id)."
            )
        self.broker_order_id = broker_order_id
