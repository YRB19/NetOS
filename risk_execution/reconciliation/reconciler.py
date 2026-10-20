"""Execution reconciliation (Slice 7) — extends the Slice 6 two-ledger cash/position check.

`compare_cash_positions` is the ORIGINAL cash/position comparison (simulation.reconcile now delegates
to it, so there is one implementation, not two). `reconcile_execution` adds, on top of it:
  orders (identity / status / filled & outstanding quantity), fills (identity, missing, extra,
  contradictory), positions & cash three ways, quarantined evidence, unresolved submissions and
  portfolio-application lag.

INDEPENDENCE (stated honestly): three representations are compared —
  (1) LIFECYCLE-IMPLIED: opening state + the fills the OrderLifecycleManager accepted from the event stream;
  (2) INTERNAL PORTFOLIO: the system's own books (supplied by the caller);
  (3) BROKER LEDGER: the broker's own books and fill history.
(1)/(3) are accumulated independently of (2). In the OFFLINE SIMULATION the per-fill charges come from the
same cost model in all three, so charge *rates* are NOT independently verified here — only that the same
charges were booked everywhere. A mismatch is never "fixed" by inventing an adjustment.
This module never creates approvals, orders or fills and never clears a halt.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum

from domain.models.enums import OrderState
from risk_execution.order_lifecycle.events import BrokerEvent, EventKind
from risk_execution.order_lifecycle.manager import OrderLifecycleManager
from shared.versioning.content_hash import hash_json_stable


class ReconciliationOutcome(str, Enum):  # noqa: UP042
    CONSISTENT = "CONSISTENT"
    CONSISTENT_AFTER_SAFE_DUPLICATES = "CONSISTENT_AFTER_SAFE_DUPLICATES"
    RECONCILED_FROM_BROKER_EVIDENCE = "RECONCILED_FROM_BROKER_EVIDENCE"
    MISMATCH_DETECTED = "MISMATCH_DETECTED"          # caller must record it -> execution halted
    UNRESOLVED = "UNRESOLVED"                         # cannot be established -> execution halted


@dataclass(frozen=True)
class Mismatch:
    kind: str
    subject: str
    expected: str
    actual: str
    detail: str = ""
    unresolved: bool = False   # "cannot verify" is distinct from "verified different", never "verified equal"

    def __str__(self) -> str:
        return f"{self.kind} [{self.subject}]: {self.expected} vs {self.actual} {self.detail}".strip()


@dataclass(frozen=True)
class LedgerView:
    cash: Decimal
    positions: Mapping[str, int]


@dataclass(frozen=True)
class ReconciliationResult:
    run_id: str
    outcome: ReconciliationOutcome
    mismatches: tuple[Mismatch, ...]
    implied_cash: Decimal | None
    implied_positions: Mapping[str, int]
    safe_duplicates_ignored: int
    evidence_fill_ids: tuple[str, ...]
    halt_id: str | None = None

    @property
    def consistent(self) -> bool:
        return self.outcome in (ReconciliationOutcome.CONSISTENT, ReconciliationOutcome.CONSISTENT_AFTER_SAFE_DUPLICATES,
                                ReconciliationOutcome.RECONCILED_FROM_BROKER_EVIDENCE)


def compare_cash_positions(a_cash: Decimal, a_pos: Mapping[str, int], b_cash: Decimal, b_pos: Mapping[str, int],
                           a_label: str = "portfolio", b_label: str = "broker") -> list[str]:
    out: list[str] = []
    if a_cash != b_cash:
        out.append(f"cash: {a_label} {a_cash} != {b_label} {b_cash}")
    for i in sorted(set(a_pos) | set(b_pos)):
        a, b = a_pos.get(i, 0), b_pos.get(i, 0)
        if a != b:
            out.append(f"position {i}: {a_label} {a} != {b_label} {b}")
    return out


def _implied(mgr: OrderLifecycleManager, opening: LedgerView) -> tuple[Decimal | None, dict[str, int]]:
    cash: Decimal | None = Decimal(opening.cash)
    pos = {k: int(v) for k, v in opening.positions.items()}
    for r in mgr.records():
        sign = 1 if r.request.side.value == "BUY" else -1
        for f in r.applied_fills.values():
            pos[r.request.instrument_id] = pos.get(r.request.instrument_id, 0) + sign * f.quantity
            if cash is not None:
                if f.charges_total is None:
                    cash = None
                else:
                    t = Decimal(f.quantity) * f.price
                    cash += (-(t + f.charges_total)) if sign == 1 else (t - f.charges_total)
    return cash, {k: v for k, v in pos.items() if v != 0}


def reconcile_execution(
    mgr: OrderLifecycleManager,
    opening: LedgerView,
    internal: LedgerView,
    broker: LedgerView,
    broker_orders: Mapping[str, object] | None,
    broker_fills: tuple | None,
) -> ReconciliationResult:
    mm: list[Mismatch] = []
    icash, ipos = _implied(mgr, opening)

    # ---- orders -----------------------------------------------------------
    known_broker_ids = set()
    for r in mgr.records():
        subj = r.key
        if mgr._unresolved(r):  # noqa: SLF001 - same package family, read-only use
            why = r.unresolved_reason or r.submission.value or r.order.state.value
            mm.append(Mismatch("UNRESOLVED_ORDER", subj, "resolved", why, unresolved=True))
        bid = r.order.broker_order_id
        if bid is None:
            continue
        known_broker_ids.add(bid)
        if broker_orders is None:
            continue
        st = broker_orders.get(bid)
        if st is None:
            mm.append(Mismatch("ORDER_MISSING_AT_BROKER", subj, bid, "absent"))
            continue
        if st.filled_quantity != r.filled_qty:
            mm.append(Mismatch("ORDER_FILLED_QTY", subj, str(r.filled_qty), str(st.filled_quantity)))
        if r.order.state not in (OrderState.RECONCILIATION_REQUIRED,) and st.state is not r.order.state:
            mm.append(Mismatch("ORDER_STATE", subj, r.order.state.value, st.state.value))
        if not r.order.is_terminal() and st.remaining_quantity != r.quantity - r.filled_qty:
            mm.append(Mismatch("OUTSTANDING_QTY", subj, str(r.quantity - r.filled_qty), str(st.remaining_quantity)))
    if broker_orders is not None:
        for bid in sorted(set(broker_orders) - known_broker_ids):
            mm.append(Mismatch("UNKNOWN_BROKER_ORDER", bid, "known", "unknown to lifecycle", unresolved=True))

    # ---- fills ------------------------------------------------------------
    ours = {f.fill_id: (r, f) for r in mgr.records() for f in r.applied_fills.values()}
    quarantined = {f.fill_id for r in mgr.records() for _w, f in r.quarantined.values() if f is not None}
    if broker_fills is not None:
        theirs = {rep.fill.fill_id: rep for rep in broker_fills}
        for fid in sorted(set(theirs) - set(ours)):
            tag = "QUARANTINED_FILL" if fid in quarantined else "FILL_MISSING_IN_LIFECYCLE"
            mm.append(Mismatch(tag, fid, "accounted", "broker reports it", unresolved=fid in quarantined))
        for fid in sorted(set(ours) - set(theirs)):
            mm.append(Mismatch("FILL_NOT_AT_BROKER", fid, "broker holds it", "absent"))
        for fid in sorted(set(ours) & set(theirs)):
            f, rep = ours[fid][1], theirs[fid]
            if (f.quantity, f.price) != (int(rep.fill.quantity), Decimal(str(rep.fill.price))):
                mm.append(Mismatch("FILL_CONTRADICTION", fid, f"{f.quantity}@{f.price}", f"{rep.fill.quantity}@{rep.fill.price}"))
    for ident_owner in mgr.records():
        for ident in ident_owner.quarantined:
            if not any(m.kind == "QUARANTINED_FILL" for m in mm) and ident_owner.quarantined[ident][1] is None:
                mm.append(Mismatch("QUARANTINED_EVENT", ident_owner.key, "none", ident, unresolved=True))

    # ---- positions & cash, three ways ---------------------------------------
    for a_lab, a_pos, b_lab, b_pos in (("lifecycle-implied", ipos, "internal portfolio", internal.positions),
                                       ("lifecycle-implied", ipos, "broker", broker.positions),
                                       ("internal portfolio", internal.positions, "broker", broker.positions)):
        for i in sorted(set(a_pos) | set(b_pos)):
            if a_pos.get(i, 0) != b_pos.get(i, 0):
                mm.append(Mismatch("POSITION", i, f"{a_lab}={a_pos.get(i, 0)}", f"{b_lab}={b_pos.get(i, 0)}"))
    if icash is None:
        mm.append(Mismatch("CASH_UNVERIFIABLE", "lifecycle", "charges known for every fill", "a fill has no charges",
                           unresolved=True))
    else:
        for a_lab, a, b_lab, b in (("lifecycle-implied", icash, "internal portfolio", internal.cash),
                                   ("lifecycle-implied", icash, "broker", broker.cash),
                                   ("internal portfolio", internal.cash, "broker", broker.cash)):
            if a != b:
                mm.append(Mismatch("CASH", "cash", f"{a_lab}={a}", f"{b_lab}={b}"))
    pend = mgr.fills_pending_portfolio_application()
    for key, f in pend:
        mm.append(Mismatch("PORTFOLIO_APPLICATION_PENDING", f.fill_id, "applied to portfolio", "not confirmed",
                           detail=f"(order {key})", unresolved=True))

    # de-duplicate identical mismatches while keeping order
    seen, uniq = set(), []
    for m in mm:
        k = (m.kind, m.subject, m.expected, m.actual)
        if k not in seen:
            seen.add(k)
            uniq.append(m)
    dups = sum(1 for r in mgr.records() for e in r.event_log if e["status"] in ("DUPLICATE_IGNORED", "STALE_IGNORED"))
    if not uniq:
        out = ReconciliationOutcome.CONSISTENT_AFTER_SAFE_DUPLICATES if dups else ReconciliationOutcome.CONSISTENT
    elif all(m.unresolved for m in uniq):
        out = ReconciliationOutcome.UNRESOLVED
    else:
        out = ReconciliationOutcome.MISMATCH_DETECTED
    run_id = "recon_" + hash_json_stable([
        str(opening.cash), sorted(opening.positions.items()), str(internal.cash), sorted(internal.positions.items()),
        str(broker.cash), sorted(broker.positions.items()), sorted(ours), sorted(
            (k, repr(v)) for k, v in ((broker_fills and {x.fill.fill_id: x.fill.quantity for x in broker_fills}) or {}).items()),
        [str(m) for m in uniq], len(mgr.records()), len(pend)])[:24]
    return ReconciliationResult(run_id, out, tuple(uniq), icash, ipos, dups, ())


def reconcile_from_broker_evidence(mgr: OrderLifecycleManager, opening: LedgerView, internal: LedgerView,
                                   broker: LedgerView, broker_orders, broker_fills: tuple,
                                   book_evidence=None) -> ReconciliationResult:  # noqa: ANN001
    """Ingest broker-reported fills missing from the lifecycle (as ordinary events, with all the usual
    safeguards) and re-reconcile. Anything contradictory stays quarantined and halts.

    `book_evidence(report) -> LedgerView` lets the caller apply an ingested fill to its own portfolio and
    return the updated internal view; without it the internal books are (truthfully) still behind and the
    result stays a mismatch/unresolved. Fills are only marked portfolio-applied after the caller booked them."""
    first = reconcile_execution(mgr, opening, internal, broker, broker_orders, broker_fills)
    missing = [m.subject for m in first.mismatches if m.kind == "FILL_MISSING_IN_LIFECYCLE"]
    if not missing:
        return first
    by_id = {rep.fill.fill_id: rep for rep in broker_fills}
    view = internal
    for fid in missing:
        rep = by_id[fid]
        res = mgr.apply_event(BrokerEvent(EventKind.FILL, rep.broker_order_id, rep.idempotency_key,
                                          fill=rep.fill, charges=rep.charges))
        if res.fill_id == fid and res.status.value == "APPLIED" and book_evidence is not None:
            view = book_evidence(rep)
            mgr.mark_portfolio_applied(fid)
    second = reconcile_execution(mgr, opening, view, broker, broker_orders, broker_fills)
    if second.consistent:
        return replace(second, outcome=ReconciliationOutcome.RECONCILED_FROM_BROKER_EVIDENCE,
                       evidence_fill_ids=tuple(missing))
    return replace(second, evidence_fill_ids=tuple(missing))
