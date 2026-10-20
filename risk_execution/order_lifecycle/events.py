"""Broker events and their stable identity (Slice 7, §5 of the Slice 7 brief).

Identity rules (documented in docs/order-state-machine-reconciliation.md):
  * if the broker supplies an `event_id`, identity = "evt:<event_id>";
  * else a FILL is identified by its `fill_id` ("fill:<fill_id>");
  * else ACK / REJECT / CANCEL_CONFIRMED are naturally unique per order
    ("<KIND>:<order ref>") - an order is acknowledged / rejected / cancelled once.
Distinct events are NEVER merged because their payloads look alike. A *fill* is additionally
guarded by fill_id: the same fill_id re-delivered under a new envelope is a duplicate only if
its payload fingerprint is identical; if it differs it is a CONFLICT (never guessed).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from domain.models.order_request import Fill
from shared.costs import CostEstimate
from shared.versioning.content_hash import hash_json_stable


class EventKind(str, Enum):  # noqa: UP042 - repository enum convention
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    FILL = "FILL"
    CANCEL_CONFIRMED = "CANCEL_CONFIRMED"


@dataclass(frozen=True)
class BrokerEvent:
    kind: EventKind
    broker_order_id: str | None = None
    idempotency_key: str | None = None  # client order id, when the broker echoes it
    event_id: str | None = None
    fill: Fill | None = None
    charges: CostEstimate | None = None
    detail: str = ""

    def order_ref(self) -> str | None:
        return self.idempotency_key or self.broker_order_id

    def identity(self) -> str | None:
        """Stable event identity, or None when the event cannot be identified at all."""
        if self.event_id:
            return f"evt:{self.event_id}"
        if self.kind is EventKind.FILL:
            return f"fill:{self.fill.fill_id}" if self.fill is not None else None
        ref = self.order_ref()
        return f"{self.kind.value}:{ref}" if ref else None

    def fingerprint(self) -> str:
        """Payload fingerprint used to tell a benign duplicate from a contradictory one."""
        if self.kind is EventKind.FILL and self.fill is not None:
            f = self.fill
            payload = [self.kind.value, f.fill_id, f.order_id, f.quantity, f.price, f.fill_type.value,
                       str(self.charges.total_cost) if self.charges is not None else None]
        else:
            payload = [self.kind.value, self.order_ref()]  # detail text is not identity
        return hash_json_stable(payload)


def event_from_fill_report(report, event_id: str | None = None) -> BrokerEvent:  # noqa: ANN001
    """Wrap a BrokerFillReport as a FILL event (the Fill object is the broker's, not ours)."""
    return BrokerEvent(
        EventKind.FILL, broker_order_id=report.broker_order_id, idempotency_key=report.idempotency_key,
        event_id=event_id, fill=report.fill, charges=report.charges, detail=report.state_after.value,
    )
