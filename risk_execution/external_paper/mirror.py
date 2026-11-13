"""ExternalMirror: mirror an approved intent to a paper platform with its OWN ledger.

Guarantees: the intent is never modified; no exception escapes into the caller's internal path; an
UNKNOWN submission is resolved by status read-back BEFORE any retry; the internal result is never read
or overwritten. External cash/positions/costs live only in `ExternalLedger`."""

from __future__ import annotations

from dataclasses import dataclass, field

from risk_execution.external_paper.contract import (
    ApprovedIntent, ExternalFill, ExternalOrderStatus, ExternalPaperAdapter, ExternalState, IntegrationMode,
    client_order_id,
)  # fmt: skip


@dataclass(frozen=True)
class ExternalOrderRecord:
    platform_id: str
    mode: str
    client_order_id: str
    internal_order_id: str  # correlation only; the two lifecycles stay separate
    external_order_id: str | None
    state: ExternalState
    filled_quantity: int
    fills: tuple[ExternalFill, ...]
    detail: str
    resolution: str  # DIRECT | READBACK_FOUND | READBACK_NOT_FOUND | UNRESOLVED | NONE


@dataclass
class ExternalLedger:
    """Platform-side accounting: cash, positions and costs as THIS platform reports them."""

    currency: str
    cash: float = 0.0
    positions: dict = field(default_factory=dict)
    fees: float = 0.0
    records: list = field(default_factory=list)

    def apply(self, rec: ExternalOrderRecord, side: str, instrument_id: str) -> None:
        sgn = 1 if side == "BUY" else -1
        for f in rec.fills:
            self.cash -= sgn * f.quantity * f.price + f.fee
            self.fees += f.fee
            self.positions[instrument_id] = self.positions.get(instrument_id, 0) + sgn * f.quantity
        self.records.append(rec)


class ExternalMirror:
    def __init__(self, adapter: ExternalPaperAdapter, ledger: ExternalLedger):
        self.adapter, self.ledger = adapter, ledger

    def mirror(self, intent: ApprovedIntent) -> ExternalOrderRecord:
        cid = client_order_id(intent, self.adapter.platform_id)
        status: ExternalOrderStatus | None = None
        resolution, detail = "DIRECT", ""
        try:
            status = self.adapter.submit_order(intent, cid)
        except Exception as e:  # noqa: BLE001 — timeout/outage must never reach the internal path
            detail = f"{type(e).__name__}"
            status, resolution = self._read_back(cid)
        fills: tuple[ExternalFill, ...] = ()
        if status is not None and status.external_order_id and status.state in (
            ExternalState.FILLED, ExternalState.PARTIALLY_FILLED
        ):
            try:
                fills = tuple(self.adapter.get_fills(status.external_order_id))
            except Exception as e:  # noqa: BLE001
                detail += f";fills-unavailable:{type(e).__name__}"
        if status is None:
            status = ExternalOrderStatus(None, cid, ExternalState.UNKNOWN, reason="unresolved after read-back")
        rec = ExternalOrderRecord(self.adapter.platform_id, self.adapter.mode.value, cid, intent.internal_order_id,
                                  status.external_order_id, status.state, status.filled_quantity, fills,
                                  detail or status.reason, resolution)  # fmt: skip
        self.ledger.apply(rec, intent.side, intent.instrument_id)
        return rec

    def _read_back(self, cid: str):
        """Documented status read-back by client id. Only a confirmed absence may allow a later resubmit,
        and even then NOT automatically: this method never resubmits."""
        try:
            found = self.adapter.get_order_by_client_id(cid)
        except Exception:  # noqa: BLE001
            return None, "UNRESOLVED"
        if found is None:
            return ExternalOrderStatus(None, cid, ExternalState.UNKNOWN, reason="read-back: not found"), "READBACK_NOT_FOUND"
        return found, "READBACK_FOUND"


def mode_is_mock(adapter: ExternalPaperAdapter) -> bool:
    return adapter.mode is IntegrationMode.MOCK
