"""OrderLifecycleManager (Slice 7) — the single owner of *what we believe about each order*.

It EXTENDS the existing domain `Order` state machine (it never defines a second lifecycle) and adds:
  * approval re-validation at the point of submission (never creates OrderRequests - sizing alone does);
  * write-ahead submission with explicit uncertainty (SENT_UNCONFIRMED) instead of guessing;
  * idempotent, identity-based broker-event processing with quarantine for anything contradictory;
  * execution halts that only an explicit operator action (with evidence) can clear;
  * explicit JSON snapshot/restore (checksum-protected). No durable store is claimed.

Fail-closed rules: an event that cannot be safely applied is NEVER applied; it is recorded, the order
is escalated (RECONCILIATION_REQUIRED where the contract allows) and execution is halted.
Everything is deterministic: time is injected, ids are content hashes, no randomness, no network.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from domain.models.enums import Action, OrderState, RiskVerdict
from domain.models.order import InvalidOrderTransition, Order
from domain.models.order_request import OrderRequest
from domain.models.risk_decision import RiskDecision
from risk_execution.broker.interface import BrokerRequestError, order_id_for_idempotency_key
from risk_execution.order_lifecycle.checkpoint import CheckpointError, CheckpointStore
from risk_execution.order_lifecycle.events import BrokerEvent, EventKind
from shared.versioning.content_hash import hash_json_stable


SNAPSHOT_VERSION = "order-lifecycle-snapshot-v2"
_READABLE_VERSIONS = ("order-lifecycle-snapshot-v1", SNAPSHOT_VERSION)  # v1 restores with provenance = UNKNOWN


class ApprovalError(ValueError):
    """The order lacks a valid, current risk approval (or the request itself is invalid)."""


class ExecutionHalted(RuntimeError):
    """New submissions are blocked by an active halt."""


class UnresolvedSubmission(RuntimeError):
    """An earlier submission outcome is unknown; it must be reconciled before anything is retried."""


class SubmissionStatus(str, Enum):  # noqa: UP042
    APPROVED_NOT_SENT = "APPROVED_NOT_SENT"
    LOCAL_FAILURE = "LOCAL_FAILURE"            # definitively NOT sent (adapter refused structurally)
    SENT_UNCONFIRMED = "SENT_UNCONFIRMED"      # attempted; outcome unknown -> execution halted
    ACCEPTED = "ACCEPTED"
    REJECTED_BY_BROKER = "REJECTED_BY_BROKER"
    RECONCILED_FROM_BROKER = "RECONCILED_FROM_BROKER"
    ABSENT_AT_BROKER = "ABSENT_AT_BROKER"      # broker lookup authoritatively says: never received
    UNRESOLVED = "UNRESOLVED"


class SubmitOutcome(str, Enum):  # noqa: UP042
    ACCEPTED = "ACCEPTED"
    REJECTED_BY_BROKER = "REJECTED_BY_BROKER"
    LOCAL_FAILURE = "LOCAL_FAILURE"
    UNCERTAIN = "UNCERTAIN"
    DUPLICATE_NOT_RESENT = "DUPLICATE_NOT_RESENT"


class EventStatus(str, Enum):  # noqa: UP042
    APPLIED = "APPLIED"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"
    STALE_IGNORED = "STALE_IGNORED"
    QUARANTINED = "QUARANTINED"      # recorded as evidence; NOT applied to state or accounting
    ESCALATED = "ESCALATED"          # order moved to RECONCILIATION_REQUIRED and/or halted
    UNKNOWN_ORDER = "UNKNOWN_ORDER"
    INVALID = "INVALID"


@dataclass(frozen=True)
class HaltRecord:
    halt_id: str
    code: str
    detail: str
    order_key: str | None
    seq: int
    requires_clean_reconciliation: bool = False
    cleared: bool = False
    cleared_by: str | None = None
    cleared_reason: str | None = None
    recorded_at: str | None = None       # manager's injected clock (ISO); None for halts restored from a v1 snapshot
    correlation_id: str | None = None    # the order record's correlation id, when the halt concerns an order
    event_identity: str | None = None    # the triggering event's identity, when there was one


@dataclass(frozen=True)
class EventResult:
    status: EventStatus
    detail: str
    order_state: OrderState | None = None
    halt_id: str | None = None
    fill_id: str | None = None


@dataclass(frozen=True)
class AppliedFill:
    fill_id: str
    event_identity: str
    side: str
    quantity: int
    price: Decimal
    charges_total: Decimal | None  # None => cash effect unverifiable (reconciler says so)
    fingerprint: str
    via_correction: bool = False
    # --- per-fill evidence retained for reconciliation (Slice 7 closure); None = UNKNOWN, never zero ---
    charges_components: tuple[tuple[str, str], ...] | None = None   # (name, Decimal-as-str) as broker-reported
    schedule_version: str | None = None
    order_id: str | None = None
    source: str | None = None


@dataclass
class OrderRecord:
    request: OrderRequest
    order: Order
    approval_id: str
    submission: SubmissionStatus = SubmissionStatus.APPROVED_NOT_SENT
    applied_fills: dict[str, AppliedFill] = field(default_factory=dict)
    quarantined: dict[str, tuple[str, AppliedFill | None]] = field(default_factory=dict)  # ident -> (reason, fill)
    seen: dict[str, str] = field(default_factory=dict)        # event identity -> fingerprint
    fill_fp: dict[str, str] = field(default_factory=dict)     # fill_id -> fingerprint
    event_log: list[dict] = field(default_factory=list)
    corrections: list[dict] = field(default_factory=list)
    cancel_requested: bool = False
    unresolved_reason: str | None = None
    failure: str | None = None
    correlation_id: str | None = None

    @property
    def key(self) -> str:
        return self.request.idempotency_key

    @property
    def quantity(self) -> int:
        return int(self.request.quantity)

    @property
    def filled_qty(self) -> int:
        return sum(f.quantity for f in self.applied_fills.values())

    @property
    def consideration(self) -> Decimal:
        return sum((Decimal(f.quantity) * f.price for f in self.applied_fills.values()), Decimal(0))


@dataclass(frozen=True)
class SubmitResult:
    outcome: SubmitOutcome
    record: OrderRecord
    detail: str = ""


class OrderLifecycleManager:
    def __init__(self, expected_risk_rule_version_id: str, clock: Callable[[], datetime],
                 checkpoint: CheckpointStore | None = None) -> None:
        if not expected_risk_rule_version_id:
            raise ValueError("expected_risk_rule_version_id is required (no default approval policy)")
        if not callable(clock):
            raise ValueError("an injected clock is required (no wall-clock fallback by design)")
        self._rrv = expected_risk_rule_version_id
        self._clock = clock
        self._checkpoint = checkpoint
        self._cur_ev: BrokerEvent | None = None
        self._records: dict[str, OrderRecord] = {}
        self._by_broker: dict[str, str] = {}
        self._by_order_id: dict[str, str] = {}
        self._approvals: dict[str, str] = {}      # risk_decision_id -> idempotency key (one approval, one order)
        self._halts: list[HaltRecord] = []
        self._seq = 0
        self._portfolio_applied: set[str] = set()
        self._global_log: list[dict] = []
        self._last_recon_run: str | None = None
        self._last_recon_ok = False
        self._last_recon_seq = -1

    # ------------------------------------------------------------------ queries
    def record(self, key: str) -> OrderRecord | None:
        return self._records.get(key)

    def records(self) -> tuple[OrderRecord, ...]:
        return tuple(self._records.values())

    def active_halts(self) -> tuple[HaltRecord, ...]:
        return tuple(h for h in self._halts if not h.cleared)

    def all_halts(self) -> tuple[HaltRecord, ...]:
        return tuple(self._halts)

    @property
    def halted(self) -> bool:
        return bool(self.active_halts())

    def can_submit(self) -> tuple[bool, tuple[str, ...]]:
        reasons = tuple(f"{h.code}: {h.detail}" for h in self.active_halts())
        return (not reasons, reasons)

    def unresolved_orders(self) -> tuple[OrderRecord, ...]:
        return tuple(r for r in self._records.values() if self._unresolved(r))

    def global_event_log(self) -> tuple[dict, ...]:
        return tuple(self._global_log)

    @staticmethod
    def _unresolved(r: OrderRecord) -> bool:
        return (r.order.state is OrderState.RECONCILIATION_REQUIRED
                or r.submission in (SubmissionStatus.SENT_UNCONFIRMED, SubmissionStatus.UNRESOLVED)
                or r.unresolved_reason is not None
                or bool(r.quarantined))

    def fills_pending_portfolio_application(self) -> tuple[tuple[str, AppliedFill], ...]:
        return tuple((r.key, f) for r in self._records.values() for f in r.applied_fills.values()
                     if f.fill_id not in self._portfolio_applied)

    def mark_portfolio_applied(self, fill_id: str) -> None:
        if not any(fill_id in r.applied_fills for r in self._records.values()):
            raise KeyError(f"unknown applied fill {fill_id!r}")
        self._portfolio_applied.add(fill_id)
        self._persist("portfolio application confirmed")

    # -------------------------------------------------------------- internals
    def _now(self) -> datetime:
        return self._clock()

    def _tick(self) -> int:
        self._seq += 1
        return self._seq

    def _stamp(self) -> str:
        return self._now().astimezone(UTC).isoformat()

    @staticmethod
    def _clip(text: str | None, n: int = 200) -> str:
        """Diagnostics are bounded: broker free text is truncated, never copied wholesale."""
        t = (text or "").replace("\n", " ")
        return t if len(t) <= n else t[: n - 3] + "..."

    def _halt(self, code: str, detail: str, order_key: str | None = None, clean_recon: bool = False,
              event_identity: str | None = None) -> HaltRecord:
        detail = self._clip(detail)
        for h in self._halts:  # idempotent: same condition is not re-raised while active
            if not h.cleared and (h.code, h.order_key, h.detail) == (code, order_key, detail):
                return h
        seq = self._tick()
        corr = self._records[order_key].correlation_id if order_key in self._records else None
        h = HaltRecord("halt_" + hash_json_stable([seq, code, order_key])[:16], code, detail, order_key, seq,
                       requires_clean_reconciliation=clean_recon, recorded_at=self._stamp(), correlation_id=corr,
                       event_identity=event_identity)
        self._halts.append(h)
        return h

    def _log(self, rec: OrderRecord | None, ident: str | None, kind: str, status: str, detail: str,
             halt_id: str | None = None) -> None:
        ev = self._cur_ev
        et, et_src = (None, "unknown")
        if ev is not None:
            if ev.event_time is not None:
                et, et_src = ev.event_time.isoformat(), "event"
            elif ev.fill is not None:
                et, et_src = ev.fill.timestamp.isoformat(), "fill.timestamp"
        row = {"seq": self._tick(), "identity": ident, "kind": kind, "status": status, "detail": self._clip(detail),
               "order": rec.key if rec else None,
               "event_id": ev.event_id if ev else None,
               "idempotency_key": (rec.key if rec else (ev.idempotency_key if ev else None)),
               "order_id": rec.order.order_id if rec else None,
               "broker_order_id": (rec.order.broker_order_id if rec else (ev.broker_order_id if ev else None)),
               "correlation_id": rec.correlation_id if rec else None,
               "event_correlation_id": ev.correlation_id if ev else None,
               "source": ev.source if ev else None, "source_version": ev.source_version if ev else None,
               "event_time": et, "event_time_source": et_src,
               "recorded_at": self._stamp(), "halt_id": halt_id}
        (rec.event_log if rec else self._global_log).append(row)

    def _go(self, rec: OrderRecord, st: OrderState, detail: str) -> None:
        rec.order.transition_to(st, detail=detail, at=self._now())

    def _escalate(self, rec: OrderRecord, code: str, detail: str) -> HaltRecord:
        """Preserve fills; move to RECONCILIATION_REQUIRED where the contract allows; always halt."""
        try:
            self._go(rec, OrderState.RECONCILIATION_REQUIRED, f"{code}: {detail}")
        except InvalidOrderTransition:
            pass  # terminal states cannot be reopened; the halt + unresolved_reason carry the problem
        rec.unresolved_reason = f"{code}: {detail}"
        return self._halt(code, detail, rec.key, event_identity=self._cur_ev.identity() if self._cur_ev else None)

    def _persist(self, why: str) -> None:
        """Write the checkpoint (if one is configured). Failure => halt + raise; never silently continue."""
        if self._checkpoint is None:
            return
        try:
            self._checkpoint.write(self.snapshot())
        except CheckpointError as e:
            self._halt("CHECKPOINT_FAILURE", f"{why}: {e}")
            raise

    # ------------------------------------------------------------- submission
    def _validate_approval(self, request: OrderRequest, rd: RiskDecision) -> None:
        if not isinstance(request, OrderRequest):
            raise ApprovalError("a valid OrderRequest is required")
        if not isinstance(rd, RiskDecision):
            raise ApprovalError("a RiskDecision is required: no approval, no order")
        if rd.final_verdict is not RiskVerdict.APPROVE:
            raise ApprovalError(f"risk verdict is {rd.final_verdict.value}: a veto never becomes an order")
        if rd.risk_decision_id != request.risk_decision_id:
            raise ApprovalError("OrderRequest.risk_decision_id does not match the supplied RiskDecision")
        if rd.risk_rule_version_id != self._rrv:
            raise ApprovalError("RiskDecision was produced under a different (stale) risk rule version")
        if rd.approved_qty is None or float(request.quantity) > float(rd.approved_qty):
            raise ApprovalError("order quantity exceeds the approved quantity ceiling")
        if float(request.quantity) != int(request.quantity) or int(request.quantity) <= 0:
            raise ApprovalError("order quantity must be a positive whole number")
        if request.side not in (Action.BUY, Action.SELL):
            raise ApprovalError("order side must be BUY or SELL")
        used = self._approvals.get(rd.risk_decision_id)
        if used is not None and used != request.idempotency_key:
            raise ApprovalError("this approval was already consumed by a different order")

    def submit(self, request: OrderRequest, risk_decision: RiskDecision, adapter, session) -> SubmitResult:  # noqa: ANN001
        key = getattr(request, "idempotency_key", None)
        existing = self._records.get(key) if key else None
        if existing is not None:
            if existing.submission in (SubmissionStatus.SENT_UNCONFIRMED, SubmissionStatus.UNRESOLVED):
                raise UnresolvedSubmission(f"order {key} outcome unknown; reconcile before any retry")
            return SubmitResult(SubmitOutcome.DUPLICATE_NOT_RESENT, existing, "same logical order: not re-sent")
        ok, reasons = self.can_submit()
        if not ok:
            raise ExecutionHalted("; ".join(reasons))
        self._validate_approval(request, risk_decision)

        order = Order(order_request_id=key, order_id=order_id_for_idempotency_key(key))
        rec = OrderRecord(request, order, risk_decision.risk_decision_id,
                          correlation_id="corr_" + hash_json_stable(["order", key])[:16])
        self._records[key] = rec
        self._by_order_id[order.order_id] = key
        self._approvals[risk_decision.risk_decision_id] = key
        self._go(rec, OrderState.APPROVED, f"risk_decision_id={risk_decision.risk_decision_id}")  # write-ahead
        try:
            self._persist("pre-submission")   # MANDATORY: no durable record of intent => nothing is sent
        except CheckpointError as e:
            rec.submission, rec.failure = SubmissionStatus.LOCAL_FAILURE, self._clip(str(e))
            self._log(rec, None, "SUBMIT", "NOT_SENT_CHECKPOINT_FAILED", str(e))
            raise
        try:
            status = adapter.place_order(session, request)
        except BrokerRequestError as e:  # adapter contract: structurally invalid, NO order was created
            rec.submission, rec.failure = SubmissionStatus.LOCAL_FAILURE, self._clip(str(e))
            self._log(rec, None, "SUBMIT", "LOCAL_FAILURE", str(e))
            return SubmitResult(SubmitOutcome.LOCAL_FAILURE, rec, str(e))
        except Exception as e:  # noqa: BLE001 - ANY other failure leaves the outcome unknown
            self._go(rec, OrderState.SUBMITTED, f"submission attempted; outcome unknown ({type(e).__name__})")
            rec.submission, rec.failure = SubmissionStatus.SENT_UNCONFIRMED, self._clip(f"{type(e).__name__}: {e}")
            self._halt("UNCERTAIN_SUBMISSION", f"order {key}: broker outcome unknown", key)
            self._log(rec, None, "SUBMIT", "UNCERTAIN", rec.failure)
            self._persist("post-submission (uncertain)")
            return SubmitResult(SubmitOutcome.UNCERTAIN, rec, rec.failure)
        self._go(rec, OrderState.SUBMITTED, "sent to broker")
        res = self._absorb_placement(rec, status)
        self._persist("post-submission")
        return res

    def _absorb_placement(self, rec: OrderRecord, st) -> SubmitResult:  # noqa: ANN001
        rec.order.set_broker_order_id(st.broker_order_id)
        self._by_broker[st.broker_order_id] = rec.key
        rec.order.last_broker_response = self._clip(st.last_response)
        if st.duplicate:
            self._halt("DUPLICATE_AT_BROKER", f"broker already held an order for key {rec.key} unknown locally", rec.key)
        if st.state is OrderState.ACKNOWLEDGED:
            self._go(rec, OrderState.ACKNOWLEDGED, "broker acknowledged")
            rec.submission = SubmissionStatus.ACCEPTED
            rec.seen[f"{EventKind.ACKNOWLEDGED.value}:{rec.key}"] = "placement"
            return SubmitResult(SubmitOutcome.ACCEPTED, rec)
        if st.state is OrderState.REJECTED:
            self._go(rec, OrderState.REJECTED, self._clip(st.last_response))
            rec.submission = SubmissionStatus.REJECTED_BY_BROKER
            rec.failure = self._clip(st.last_response)
            rec.seen[f"{EventKind.REJECTED.value}:{rec.key}"] = "placement"
            return SubmitResult(SubmitOutcome.REJECTED_BY_BROKER, rec, st.last_response)
        self._escalate(rec, "UNEXPECTED_PLACEMENT_STATE", f"broker returned {st.state.value} at placement")
        rec.submission = SubmissionStatus.UNRESOLVED
        return SubmitResult(SubmitOutcome.UNCERTAIN, rec, f"unexpected placement state {st.state.value}")

    def request_cancel(self, key: str, adapter, session) -> OrderRecord:  # noqa: ANN001
        """A cancel REQUEST is not evidence of cancellation; only a CANCEL_CONFIRMED event is."""
        rec = self._records[key]
        rec.cancel_requested = True
        self._log(rec, None, "CANCEL_REQUEST", "REQUESTED", "request sent; state unchanged")
        if rec.order.broker_order_id:
            try:
                adapter.cancel_order(session, rec.order.broker_order_id)
            except Exception as e:  # noqa: BLE001 - a failed/timed-out request proves nothing either way
                self._log(rec, None, "CANCEL_REQUEST", "UNCONFIRMED", f"{type(e).__name__}: {e}")
        return rec

    # ----------------------------------------------------------------- events
    def _locate(self, ev: BrokerEvent) -> tuple[OrderRecord | None, str]:
        found: dict[str, str] = {}
        if ev.idempotency_key and ev.idempotency_key in self._records:
            found["key"] = ev.idempotency_key
        if ev.broker_order_id and ev.broker_order_id in self._by_broker:
            found["broker"] = self._by_broker[ev.broker_order_id]
        if ev.fill is not None and ev.fill.order_id in self._by_order_id:
            found["order_id"] = self._by_order_id[ev.fill.order_id]
        if len(set(found.values())) > 1:
            return None, "event identifiers point at different orders"
        if not found:
            return None, "no known order matches the event"
        return self._records[next(iter(found.values()))], ""

    def apply_event(self, ev: BrokerEvent) -> EventResult:
        self._cur_ev = ev
        try:
            res = self._apply_event(ev)
        finally:
            self._cur_ev = None
        if res.status is not EventStatus.DUPLICATE_IGNORED:
            self._persist("event")
        return res

    def _apply_event(self, ev: BrokerEvent) -> EventResult:
        ident = ev.identity()
        if ident is None:
            self._log(None, None, ev.kind.value, "INVALID", "event cannot be identified")
            h = self._halt("EVENT_UNIDENTIFIABLE", f"{ev.kind.value} event has no usable identity")
            return EventResult(EventStatus.INVALID, "unidentifiable event", halt_id=h.halt_id)
        rec, why = self._locate(ev)
        if rec is None:
            self._log(None, ident, ev.kind.value, "UNKNOWN_ORDER", why)
            h = self._halt("UNKNOWN_ORDER_EVENT", f"{ident}: {why}")
            return EventResult(EventStatus.UNKNOWN_ORDER, why, halt_id=h.halt_id)

        fp = ev.fingerprint()
        prior = rec.seen.get(ident)
        if ev.kind is EventKind.FILL and ev.fill is not None and ev.fill.fill_id in rec.fill_fp:
            prior = prior or rec.fill_fp[ev.fill.fill_id]
        if prior is not None and prior != "placement":
            if prior == fp:
                self._log(rec, ident, ev.kind.value, "DUPLICATE_IGNORED", "identical event re-delivered")
                return EventResult(EventStatus.DUPLICATE_IGNORED, "identical event re-delivered", rec.order.state)
            return self._conflict(rec, ident, ev, "same identity re-delivered with a DIFFERENT payload")
        if prior == "placement":  # learnt synchronously from the place_order response
            self._log(rec, ident, ev.kind.value, "DUPLICATE_IGNORED", "already learnt from placement response")
            return EventResult(EventStatus.DUPLICATE_IGNORED, "already learnt at placement", rec.order.state)

        if ev.kind is EventKind.ACKNOWLEDGED:
            res = self._on_ack(rec, ident, ev)
        elif ev.kind is EventKind.REJECTED:
            res = self._on_reject(rec, ident, ev)
        elif ev.kind is EventKind.CANCEL_CONFIRMED:
            res = self._on_cancel(rec, ident, ev)
        else:
            res = self._on_fill(rec, ident, ev)
        if res.status is not EventStatus.INVALID:
            rec.seen[ident] = fp
            if ev.fill is not None:
                rec.fill_fp[ev.fill.fill_id] = fp
        return res

    def _conflict(self, rec: OrderRecord, ident: str, ev: BrokerEvent, why: str) -> EventResult:
        rec.quarantined[ident] = (why, self._as_applied(rec, ev, ident) if ev.kind is EventKind.FILL and ev.fill else None)
        h = self._escalate(rec, "EVENT_CONFLICT", f"{ident}: {why}")
        self._log(rec, ident, ev.kind.value, "ESCALATED", why, h.halt_id)
        return EventResult(EventStatus.ESCALATED, why, rec.order.state, h.halt_id)

    def _quarantine(self, rec: OrderRecord, ident: str, ev: BrokerEvent, code: str, why: str) -> EventResult:
        rec.quarantined[ident] = (why, self._as_applied(rec, ev, ident) if ev.kind is EventKind.FILL and ev.fill else None)
        h = self._escalate(rec, code, f"{ident}: {why}")
        self._log(rec, ident, ev.kind.value, "QUARANTINED", why, h.halt_id)
        return EventResult(EventStatus.QUARANTINED, why, rec.order.state, h.halt_id,
                           ev.fill.fill_id if ev.fill else None)

    def _as_applied(self, rec: OrderRecord, ev: BrokerEvent, ident: str) -> AppliedFill:
        f, c = ev.fill, ev.charges
        comps = None if c is None else (
            ("brokerage", str(c.brokerage)), ("stt", str(c.stt)), ("exchange_txn_charges", str(c.exchange_txn_charges)),
            ("sebi_charges", str(c.sebi_charges)), ("gst", str(c.gst)), ("stamp_duty", str(c.stamp_duty)))
        return AppliedFill(f.fill_id, ident, rec.request.side.value, int(f.quantity), Decimal(str(f.price)),
                           c.total_cost if c is not None else None, ev.fingerprint(),
                           charges_components=comps, schedule_version=None if c is None else c.schedule_version,
                           order_id=f.order_id, source=ev.source)

    def _on_ack(self, rec: OrderRecord, ident: str, ev: BrokerEvent) -> EventResult:
        s = rec.order.state
        if s is OrderState.SUBMITTED:
            self._go(rec, OrderState.ACKNOWLEDGED, "broker acknowledged")
            if rec.submission is SubmissionStatus.SENT_UNCONFIRMED:
                rec.submission = SubmissionStatus.RECONCILED_FROM_BROKER
            else:
                rec.submission = SubmissionStatus.ACCEPTED
            self._log(rec, ident, "ACKNOWLEDGED", "APPLIED", "")
            return EventResult(EventStatus.APPLIED, "acknowledged", rec.order.state)
        if s in (OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELLED):
            self._log(rec, ident, "ACKNOWLEDGED", "STALE_IGNORED", f"late acknowledgement while {s.value}")
            return EventResult(EventStatus.STALE_IGNORED, f"late acknowledgement while {s.value}", s)
        if s is OrderState.APPROVED:
            return self._quarantine(rec, ident, ev, "ACK_FOR_UNSENT_ORDER", "acknowledgement for an order never sent")
        return self._quarantine(rec, ident, ev, "ACK_CONFLICT", f"acknowledgement while {s.value}")

    def _on_reject(self, rec: OrderRecord, ident: str, ev: BrokerEvent) -> EventResult:
        s = rec.order.state
        if s in (OrderState.SUBMITTED, OrderState.ACKNOWLEDGED):
            txt = self._clip(ev.detail) or "REJECTED"   # broker free text is bounded wherever it is stored
            self._go(rec, OrderState.REJECTED, txt)
            rec.order.last_broker_response = txt
            rec.submission = SubmissionStatus.REJECTED_BY_BROKER
            rec.failure = txt
            self._log(rec, ident, "REJECTED", "APPLIED", ev.detail)
            return EventResult(EventStatus.APPLIED, "rejected", rec.order.state)
        if s is OrderState.REJECTED:
            self._log(rec, ident, "REJECTED", "DUPLICATE_IGNORED", "already rejected")
            return EventResult(EventStatus.DUPLICATE_IGNORED, "already rejected", s)
        return self._quarantine(rec, ident, ev, "REJECT_CONFLICT",
                                f"rejection while {s.value} with {rec.filled_qty} filled")

    def _on_cancel(self, rec: OrderRecord, ident: str, ev: BrokerEvent) -> EventResult:
        s = rec.order.state
        if s is OrderState.PARTIALLY_FILLED:
            self._go(rec, OrderState.CANCELLED, "broker confirmed cancellation of remainder")
            rec.order.last_broker_response = "CANCELLED"
            self._log(rec, ident, "CANCEL_CONFIRMED", "APPLIED", f"filled {rec.filled_qty} preserved")
            return EventResult(EventStatus.APPLIED, "remainder cancelled; fills preserved", rec.order.state)
        if s is OrderState.CANCELLED:
            self._log(rec, ident, "CANCEL_CONFIRMED", "DUPLICATE_IGNORED", "already cancelled")
            return EventResult(EventStatus.DUPLICATE_IGNORED, "already cancelled", s)
        if s is OrderState.ACKNOWLEDGED:  # ADR-11: broker-CONFIRMED cancel of a resting, entirely unfilled order
            self._go(rec, OrderState.CANCELLED, "broker confirmed cancellation; no fills")
            rec.order.last_broker_response = "CANCELLED"
            self._log(rec, ident, "CANCEL_CONFIRMED", "APPLIED", "unfilled order cancelled")
            return EventResult(EventStatus.APPLIED, "unfilled order cancelled", rec.order.state)
        if s is OrderState.SUBMITTED:
            # no broker acknowledgement has been recorded, so there is no evidence the order was ever live
            # here; SUBMITTED -> CANCELLED is deliberately not a legal edge (ADR-11): stay fail-closed.
            return self._quarantine(rec, ident, ev, "CANCEL_OF_UNACKNOWLEDGED_ORDER",
                                    "cancel confirmed while SUBMITTED (no acknowledgement recorded)")
        return self._quarantine(rec, ident, ev, "CANCEL_CONFLICT", f"cancel confirmed while {s.value}")

    def _on_fill(self, rec: OrderRecord, ident: str, ev: BrokerEvent) -> EventResult:
        f = ev.fill
        if f is None:
            self._log(rec, ident, "FILL", "INVALID", "FILL event without a Fill")
            h = self._halt("FILL_WITHOUT_PAYLOAD", ident, rec.key)
            return EventResult(EventStatus.INVALID, "fill event has no fill", halt_id=h.halt_id)
        if f.order_id != rec.order.order_id:
            return self._quarantine(rec, ident, ev, "FILL_ORDER_MISMATCH", "fill.order_id does not match the order")
        if float(f.quantity) != int(f.quantity):
            return self._quarantine(rec, ident, ev, "FILL_FRACTIONAL", "fractional fill quantity")
        qty = int(f.quantity)
        s = rec.order.state
        if f.fill_id in rec.applied_fills:  # same fill id, different envelope => fingerprint already compared
            self._log(rec, ident, "FILL", "DUPLICATE_IGNORED", "fill already applied")
            return EventResult(EventStatus.DUPLICATE_IGNORED, "fill already applied", s, fill_id=f.fill_id)
        cum_after = rec.filled_qty + qty
        if s in (OrderState.CANCELLED, OrderState.REJECTED):
            return self._quarantine(rec, ident, ev, "LATE_FILL_AFTER_TERMINAL", f"fill after {s.value}")
        if s is OrderState.RECONCILIATION_REQUIRED or s is OrderState.APPROVED:
            return self._quarantine(rec, ident, ev, "FILL_WHILE_UNRESOLVED", f"fill while {s.value}")
        if cum_after > rec.quantity:
            return self._quarantine(rec, ident, ev, "OVERFILL", f"cumulative {cum_after} > order quantity {rec.quantity}")
        if (f.fill_type.value == "FULL") != (cum_after == rec.quantity):
            return self._quarantine(rec, ident, ev, "FILL_TYPE_CONTRADICTION",
                                    f"fill_type {f.fill_type.value} but cumulative {cum_after}/{rec.quantity}")
        if s is OrderState.SUBMITTED:  # evidence-based acknowledgement: a fill proves the broker holds the order
            self._go(rec, OrderState.ACKNOWLEDGED, "implicit acknowledgement from fill evidence")
            if rec.submission is SubmissionStatus.SENT_UNCONFIRMED:
                rec.submission = SubmissionStatus.RECONCILED_FROM_BROKER
            else:
                rec.submission = SubmissionStatus.ACCEPTED
        rec.applied_fills[f.fill_id] = self._as_applied(rec, ev, ident)
        if cum_after == rec.quantity:
            self._go(rec, OrderState.FILLED, f"filled {cum_after}/{rec.quantity}")
        elif rec.order.state is OrderState.ACKNOWLEDGED:
            self._go(rec, OrderState.PARTIALLY_FILLED, f"filled {cum_after}/{rec.quantity}")
        rec.order.last_broker_response = rec.order.state.value
        self._log(rec, ident, "FILL", "APPLIED", f"{qty} @ {f.price}; cumulative {cum_after}")
        return EventResult(EventStatus.APPLIED, f"fill applied; cumulative {cum_after}/{rec.quantity}",
                           rec.order.state, fill_id=f.fill_id)

    # ---------------------------------------------------- recovery / resolution
    def resolve_uncertain_submission(self, key: str, adapter, session) -> str:  # noqa: ANN001
        """Ask the broker (by client order id) what really happened, then replay that evidence
        through apply_event. Never re-sends. Does NOT clear the halt (operator action required)."""
        rec = self._records[key]
        if rec.submission is not SubmissionStatus.SENT_UNCONFIRMED:
            return f"nothing to resolve (submission={rec.submission.value})"
        find = getattr(adapter, "find_order_by_client_key", None)
        if not callable(find):
            rec.submission = SubmissionStatus.UNRESOLVED
            return "adapter cannot look up orders by client key: remains unresolved"
        st = find(session, key)
        if st is None:
            self._go(rec, OrderState.REJECTED, "ABSENT_AT_BROKER: broker lookup confirms the order was never received")
            rec.submission = SubmissionStatus.ABSENT_AT_BROKER
            rec.failure = "never received by broker (confirmed by lookup)"
            self._log(rec, None, "RESOLVE", "ABSENT_AT_BROKER", "closed; a retry needs a NEW order and fresh risk evaluation")
            return "ABSENT_AT_BROKER"
        rec.order.set_broker_order_id(st.broker_order_id)
        self._by_broker[st.broker_order_id] = key
        if st.state is OrderState.REJECTED:
            self.apply_event(BrokerEvent(EventKind.REJECTED, st.broker_order_id, key, detail=st.last_response))
        else:
            self.apply_event(BrokerEvent(EventKind.ACKNOWLEDGED, st.broker_order_id, key))
            for rep in adapter.get_fills(session, st.broker_order_id):
                self.apply_event(BrokerEvent(EventKind.FILL, rep.broker_order_id, key, fill=rep.fill, charges=rep.charges))
            if st.state is OrderState.CANCELLED:
                self.apply_event(BrokerEvent(EventKind.CANCEL_CONFIRMED, st.broker_order_id, key))
        if rec.submission is SubmissionStatus.SENT_UNCONFIRMED:
            rec.submission = SubmissionStatus.RECONCILED_FROM_BROKER
        return f"RECONCILED_FROM_BROKER ({rec.order.state.value})"

    def accept_quarantined_fill(self, key: str, fill_id: str, operator_id: str, reason: str) -> AppliedFill:
        """Explicit operator correction: account a quarantined fill that broker evidence confirms."""
        self._need_operator(operator_id, reason)
        rec = self._records[key]
        hit = next(((i, v) for i, v in rec.quarantined.items() if v[1] is not None and v[1].fill_id == fill_id), None)
        if hit is None:
            raise KeyError(f"no quarantined fill {fill_id!r} on order {key}")
        ident, (_why, fill) = hit
        if rec.filled_qty + fill.quantity > rec.quantity:
            raise ValueError("accepting this fill would exceed the order quantity")
        corrected = AppliedFill(fill.fill_id, fill.event_identity, fill.side, fill.quantity, fill.price,
                                fill.charges_total, fill.fingerprint, via_correction=True)
        rec.applied_fills[fill_id] = corrected
        del rec.quarantined[ident]
        rec.corrections.append({"seq": self._tick(), "kind": "ACCEPT_FILL", "fill_id": fill_id,
                                "operator": operator_id, "reason": reason})
        self._persist("operator correction")
        return corrected

    def dismiss_quarantined(self, key: str, ident: str, operator_id: str, reason: str) -> None:
        self._need_operator(operator_id, reason)
        rec = self._records[key]
        if ident not in rec.quarantined:
            raise KeyError(ident)
        del rec.quarantined[ident]
        rec.corrections.append({"seq": self._tick(), "kind": "DISMISS_QUARANTINED", "identity": ident,
                                "operator": operator_id, "reason": reason})
        self._persist("operator correction")

    def resolve_reconciliation_required(self, key: str, target: OrderState, operator_id: str, evidence: str) -> OrderRecord:
        """Operator pathway out of RECONCILIATION_REQUIRED; target must agree with accounted fills."""
        self._need_operator(operator_id, evidence)
        rec = self._records[key]
        if rec.order.state is not OrderState.RECONCILIATION_REQUIRED:
            raise ValueError(f"order is {rec.order.state.value}, not RECONCILIATION_REQUIRED")
        q, c = rec.quantity, rec.filled_qty
        legal = {OrderState.FILLED: c == q, OrderState.PARTIALLY_FILLED: 0 < c < q,
                 OrderState.CANCELLED: True, OrderState.REJECTED: c == 0}
        if not legal.get(target, False):
            raise ValueError(f"target {target.value} is inconsistent with {c}/{q} accounted fills")
        self._go(rec, target, f"resolved by operator {operator_id}: {evidence}")
        rec.unresolved_reason = None
        rec.corrections.append({"seq": self._tick(), "kind": "RESOLVE_STATE", "target": target.value,
                                "operator": operator_id, "reason": evidence})
        self._persist("operator resolution")
        return rec

    def acknowledge_terminal_discrepancy(self, key: str, operator_id: str, reason: str) -> OrderRecord:
        """Operator pathway for a TERMINAL order (which cannot enter RECONCILIATION_REQUIRED) whose
        flagged discrepancy has been investigated. Requires every quarantined item to be dealt with first."""
        self._need_operator(operator_id, reason)
        rec = self._records[key]
        if not rec.order.is_terminal():
            raise ValueError(f"order is {rec.order.state.value}; use resolve_reconciliation_required")
        if rec.quarantined:
            raise ValueError("quarantined evidence must be accepted or dismissed first")
        rec.unresolved_reason = None
        rec.corrections.append({"seq": self._tick(), "kind": "ACK_TERMINAL_DISCREPANCY", "operator": operator_id,
                                "reason": reason})
        self._persist("operator acknowledgement")
        return rec

    @staticmethod
    def _need_operator(operator_id: str, reason: str) -> None:
        if not (isinstance(operator_id, str) and operator_id.strip() and isinstance(reason, str) and reason.strip()):
            raise ValueError("an operator id and a non-empty reason/evidence are required")

    # ------------------------------------------------------------- reconciliation
    def record_reconciliation(self, result) -> HaltRecord | None:  # noqa: ANN001 - duck-typed ReconciliationResult
        self._last_recon_run, self._last_recon_ok = result.run_id, bool(result.consistent)
        self._last_recon_seq = self._tick()
        if result.consistent:
            self._persist("reconciliation")
            return None
        h = self._halt("RECONCILIATION_MISMATCH", f"run {result.run_id}: {len(result.mismatches)} mismatch(es)",
                          None, clean_recon=True)
        self._persist("reconciliation")
        return h

    def clear_halt(self, halt_id: str, operator_id: str, reason: str, reconciliation_run_id: str | None = None) -> HaltRecord:
        """Explicit, evidenced, operator-only. A passing check never clears a halt by itself."""
        self._need_operator(operator_id, reason)
        idx = next((i for i, h in enumerate(self._halts) if h.halt_id == halt_id), None)
        if idx is None or self._halts[idx].cleared:
            raise KeyError(f"no active halt {halt_id!r}")
        h = self._halts[idx]
        if h.order_key is not None:
            rec = self._records[h.order_key]
            if self._unresolved(rec):
                raise ValueError(f"order {h.order_key} is still unresolved ({rec.unresolved_reason or rec.submission.value}); "
                                 "resolve it first")
        if h.requires_clean_reconciliation:
            if not (self._last_recon_ok and reconciliation_run_id == self._last_recon_run and self._last_recon_seq > h.seq):
                raise ValueError("a consistent reconciliation run newer than the halt must be cited")
        if h.order_key is None and not h.requires_clean_reconciliation and self.unresolved_orders():
            raise ValueError("unresolved orders remain")
        self._halts[idx] = HaltRecord(h.halt_id, h.code, h.detail, h.order_key, h.seq, h.requires_clean_reconciliation,
                                      True, operator_id, reason, h.recorded_at, h.correlation_id, h.event_identity)
        self._persist("halt cleared")
        return self._halts[idx]

    # ------------------------------------------------------------ persistence
    def snapshot(self) -> dict:
        def fill(f: AppliedFill) -> dict:
            return {"fill_id": f.fill_id, "event_identity": f.event_identity, "side": f.side, "quantity": f.quantity,
                    "price": str(f.price), "charges_total": None if f.charges_total is None else str(f.charges_total),
                    "fingerprint": f.fingerprint, "via_correction": f.via_correction,
                    "charges_components": None if f.charges_components is None else [list(c) for c in f.charges_components],
                    "schedule_version": f.schedule_version, "order_id": f.order_id, "source": f.source}
        recs = []
        for r in self._records.values():
            q = r.request
            recs.append({
                "request": {"instrument_id": q.instrument_id, "side": q.side.value, "quantity": q.quantity,
                            "order_type": q.order_type.value, "risk_decision_id": q.risk_decision_id,
                            "limit_price": q.limit_price, "idempotency_key": q.idempotency_key},
                "approval_id": r.approval_id, "submission": r.submission.value,
                "broker_order_id": r.order.broker_order_id, "last_broker_response": r.order.last_broker_response,
                "history": [{"from": h.from_state.value, "to": h.to_state.value, "at": h.at.isoformat(), "detail": h.detail}
                            for h in r.order.state_history],
                "applied_fills": [fill(f) for f in r.applied_fills.values()],
                "quarantined": [{"identity": i, "reason": v[0], "fill": None if v[1] is None else fill(v[1])}
                                for i, v in r.quarantined.items()],
                "seen": dict(r.seen), "fill_fp": dict(r.fill_fp), "event_log": list(r.event_log),
                "corrections": list(r.corrections), "cancel_requested": r.cancel_requested,
                "unresolved_reason": r.unresolved_reason, "failure": r.failure, "correlation_id": r.correlation_id,
            })
        body = {"version": SNAPSHOT_VERSION, "risk_rule_version_id": self._rrv, "seq": self._seq,
                "records": recs, "approvals": dict(self._approvals), "portfolio_applied": sorted(self._portfolio_applied),
                "halts": [h.__dict__ for h in self._halts], "global_log": list(self._global_log),
                "last_recon": [self._last_recon_run, self._last_recon_ok, self._last_recon_seq]}
        return {"body": body, "checksum": hash_json_stable(body)}

    @classmethod
    def restore(cls, snap: dict, clock: Callable[[], datetime],
                requests: Mapping[str, OrderRequest], checkpoint: CheckpointStore | None = None) -> OrderLifecycleManager:
        """`requests` must supply the ORIGINAL OrderRequest objects (keyed by idempotency key): this module
        never constructs an OrderRequest (sizing is the sole creator). Each is checked against the snapshot."""
        body = snap["body"]
        if hash_json_stable(body) != snap["checksum"]:
            raise ValueError("snapshot checksum mismatch: refusing to restore a tampered or corrupted snapshot")
        if body.get("version") not in _READABLE_VERSIONS:
            raise ValueError(f"unsupported snapshot version {body.get('version')!r}")
        m = cls(body["risk_rule_version_id"], clock, checkpoint)
        m._seq, m._approvals = body["seq"], dict(body["approvals"])
        m._portfolio_applied = set(body["portfolio_applied"])
        m._halts = [HaltRecord(**h) for h in body["halts"]]  # v1 halts lack provenance keys: dataclass defaults = unknown
        m._global_log = list(body["global_log"])
        m._last_recon_run, m._last_recon_ok, m._last_recon_seq = body["last_recon"]

        def fill(d: dict) -> AppliedFill:
            comps = d.get("charges_components")  # absent in v1 => unknown, stays None (never zero)
            return AppliedFill(d["fill_id"], d["event_identity"], d["side"], d["quantity"], Decimal(d["price"]),
                               None if d["charges_total"] is None else Decimal(d["charges_total"]),
                               d["fingerprint"], d["via_correction"],
                               None if comps is None else tuple((a, b) for a, b in comps),
                               d.get("schedule_version"), d.get("order_id"), d.get("source"))
        for d in body["records"]:
            q = d["request"]
            req = requests.get(q["idempotency_key"])
            if req is None or (req.instrument_id, req.side.value, req.quantity, req.order_type.value,
                               req.risk_decision_id, req.limit_price) != (
                    q["instrument_id"], q["side"], q["quantity"], q["order_type"], q["risk_decision_id"], q["limit_price"]):
                raise ValueError(f"original OrderRequest for {q['idempotency_key']!r} missing or different from snapshot")
            order = Order(order_request_id=req.idempotency_key, order_id=order_id_for_idempotency_key(req.idempotency_key))
            for h in d["history"]:  # replay through the real state machine: an illegal history cannot be restored
                order.transition_to(OrderState(h["to"]), detail=h["detail"], at=datetime.fromisoformat(h["at"]))
            if d["broker_order_id"]:
                order.set_broker_order_id(d["broker_order_id"])
                m._by_broker[d["broker_order_id"]] = req.idempotency_key
            order.last_broker_response = d["last_broker_response"]
            r = OrderRecord(req, order, d["approval_id"], SubmissionStatus(d["submission"]))
            r.applied_fills = {f["fill_id"]: fill(f) for f in d["applied_fills"]}
            r.quarantined = {x["identity"]: (x["reason"], None if x["fill"] is None else fill(x["fill"])) for x in d["quarantined"]}
            r.seen, r.fill_fp, r.event_log = dict(d["seen"]), dict(d["fill_fp"]), list(d["event_log"])
            r.corrections, r.cancel_requested = list(d["corrections"]), d["cancel_requested"]
            r.unresolved_reason, r.failure = d["unresolved_reason"], d["failure"]
            r.correlation_id = d.get("correlation_id")
            if r.filled_qty > r.quantity or (order.state is OrderState.FILLED and r.filled_qty != r.quantity):
                raise ValueError(f"snapshot inconsistent for {req.idempotency_key!r}: {r.filled_qty}/{r.quantity} filled "
                                 f"but state {order.state.value}")
            m._records[req.idempotency_key] = r
            m._by_order_id[order.order_id] = req.idempotency_key
        return m

    @classmethod
    def restore_from_store(cls, store: CheckpointStore, clock: Callable[[], datetime],
                           requests: Mapping[str, OrderRequest]) -> OrderLifecycleManager:
        snap = store.read()
        if snap is None:
            raise CheckpointError("no checkpoint to restore from")
        return cls.restore(snap, clock, requests, checkpoint=store)

    def recover_after_restart(self, adapter, session) -> dict:  # noqa: ANN001
        """Reconcile restored state against the independently retained BROKER state. Never re-sends.
        1. A record that was written ahead (APPROVED) but has no recorded outcome is treated as 'sent,
           outcome unknown' (the crash may have happened before OR after the broker accepted it).
        2. Every unconfirmed submission is looked up by client key (found => evidence replayed; absent => closed).
        3. Fills/terminal outcomes the broker holds are replayed through apply_event (idempotent), which
           recovers events lost between the broker and the last checkpoint.
        Halts raised here are NOT cleared: clearing remains an explicit operator action."""
        actions: dict[str, list[str]] = {"marked_unconfirmed": [], "resolved": [], "replayed_fills": [], "terminal_synced": []}
        for rec in list(self._records.values()):
            if rec.submission is SubmissionStatus.APPROVED_NOT_SENT and rec.order.state is OrderState.APPROVED:
                self._go(rec, OrderState.SUBMITTED, "recovered after restart: write-ahead record without outcome")
                rec.submission = SubmissionStatus.SENT_UNCONFIRMED
                self._halt("UNCERTAIN_SUBMISSION", f"order {rec.key}: recovered after restart without an outcome", rec.key)
                actions["marked_unconfirmed"].append(rec.key)
        for rec in list(self._records.values()):
            if rec.submission is SubmissionStatus.SENT_UNCONFIRMED:
                actions["resolved"].append(f"{rec.key}: {self.resolve_uncertain_submission(rec.key, adapter, session)}")
        for rec in list(self._records.values()):
            bid = rec.order.broker_order_id
            if not bid:
                continue
            for rep in adapter.get_fills(session, bid):
                before = len(rec.applied_fills)
                self.apply_event(BrokerEvent(EventKind.FILL, rep.broker_order_id, rec.key, fill=rep.fill,
                                             charges=rep.charges, source=rep.adapter_id, source_version=rep.adapter_version))
                if len(rec.applied_fills) > before:
                    actions["replayed_fills"].append(rep.fill.fill_id)
            st = adapter.get_order_status(session, bid)
            kind = {OrderState.REJECTED: EventKind.REJECTED, OrderState.CANCELLED: EventKind.CANCEL_CONFIRMED}.get(st.state)
            if kind is not None and rec.order.state is not st.state:
                self.apply_event(BrokerEvent(kind, bid, rec.key, detail=st.last_response))
                actions["terminal_synced"].append(f"{rec.key}: {kind.value}")
        self._persist("recovery")
        return actions
