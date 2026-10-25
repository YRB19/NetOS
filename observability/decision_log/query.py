"""Read-only query / reconstruction interface over a persisted journal (Slice 8).

A BACKEND contract for the future Operator Console (Slice 10). It imports no execution, sizing, risk,
broker or strategy code and has no mutating method. Everything it returns comes from persisted events;
a missing linked object is returned as an explicit `MissingReference`, never regenerated from current
configuration, market data or code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from observability.decision_log.events import ErrorCode, EventType, JournalError, JournalEvent, canonical_json
from observability.decision_log.journal import (
    DecisionJournal,
    VerificationReport,
    journal_path,
    read_journal_file,
    verify_lines,
)

MAX_PAGE = 1000


@dataclass(frozen=True)
class MissingReference:
    kind: str
    expected_id: str
    expected_source: str  # the event type that should have recorded it
    referenced_by: str


@dataclass(frozen=True)
class DecisionSummary:
    decision_id: str
    instrument_id: str | None
    cycle_timestamp: str | None
    status: str  # FINALIZED | INCOMPLETE
    terminal_state: str | None
    last_event_type: str
    event_count: int


@dataclass(frozen=True)
class DecisionChain:
    decision_id: str
    run_id: str
    status: str
    terminal_state: str | None
    last_stage: str
    reconciliation_status: str  # OK | BLOCKED | NOT_RECORDED
    events: tuple[JournalEvent, ...]
    sections: dict
    versions: dict
    decision_record: dict | None
    missing_references: tuple[MissingReference, ...]
    caveats: tuple[str, ...] = field(default_factory=tuple)

    def event_ids(self) -> list[str]:
        return [e.event_id for e in self.events]


class JournalReader:
    """Read-only view. Build with `from_file`/`from_journal`; refuses a journal that fails verification."""

    def __init__(self, events: list[JournalEvent], report: VerificationReport, run_id: str) -> None:
        self._events = list(events)
        self._report = report
        self.run_id = run_id
        self._by_id = {e.event_id: e for e in self._events}

    @classmethod
    def from_file(cls, root: Path | str, run_id: str, *, allow_unverified: bool = False) -> JournalReader:
        events, rep = read_journal_file(journal_path(root, run_id))
        if not rep.ok and not allow_unverified:
            raise JournalError(ErrorCode(rep.errors[0][0]), f"journal failed verification: {rep.errors[0][1]}")
        return cls(events, rep, run_id)

    @classmethod
    def from_journal(cls, journal: DecisionJournal) -> JournalReader:
        lines = [canonical_json(e.to_dict()) for e in journal.events()]
        events, rep = verify_lines(lines, journal.run_id)
        return cls(events, rep, journal.run_id)

    # ---- integrity --------------------------------------------------------
    def verify(self) -> VerificationReport:
        return self._report

    # ---- lookups ----------------------------------------------------------
    def get_event(self, event_id: str) -> JournalEvent:
        ev = self._by_id.get(event_id)
        if ev is None:
            raise JournalError(ErrorCode.JOURNAL_NOT_FOUND, f"no event {event_id}")
        return ev

    def events(self) -> tuple[JournalEvent, ...]:
        return tuple(self._events)

    def events_for_decision(self, decision_id: str) -> tuple[JournalEvent, ...]:
        return tuple(e for e in self._events if e.decision_id == decision_id
                     or decision_id in (e.links.get("decision_ids") or []))  # fmt: skip

    def list_decisions(self, limit: int = 100, offset: int = 0) -> list[DecisionSummary]:
        if limit < 1 or limit > MAX_PAGE or offset < 0:
            raise JournalError(ErrorCode.JOURNAL_INVALID_EVENT, f"limit must be 1..{MAX_PAGE} and offset >= 0")
        order: list[str] = []
        for e in self._events:
            if e.event_type is EventType.DECISION_STARTED and e.decision_id and e.decision_id not in order:
                order.append(e.decision_id)
        return [self._summary(d) for d in order[offset: offset + limit]]  # stable: journal sequence order

    def _summary(self, decision_id: str) -> DecisionSummary:
        evs = self.events_for_decision(decision_id)
        start = next((e for e in evs if e.event_type is EventType.DECISION_STARTED), None)
        fin = next((e for e in evs if e.event_type is EventType.DECISION_FINALIZED), None)
        own = [e for e in evs if e.decision_id == decision_id]
        return DecisionSummary(
            decision_id, start.payload.get("instrument_id") if start else None,
            start.payload.get("cycle_timestamp") if start else None,
            "FINALIZED" if fin else "INCOMPLETE", fin.payload["terminal_state"] if fin else None,
            own[-1].event_type.value if own else "NONE", len(evs),
        )  # fmt: skip

    # ---- reconstruction ---------------------------------------------------
    def decision_chain(self, decision_id: str) -> DecisionChain:
        evs = self.events_for_decision(decision_id)
        if not evs:
            raise JournalError(ErrorCode.JOURNAL_NOT_FOUND, f"no decision {decision_id}")

        def of(t: EventType) -> list[JournalEvent]:
            return [e for e in evs if e.event_type is t]

        started, snap = of(EventType.DECISION_STARTED), of(EventType.INPUT_SNAPSHOT_LINKED)
        cand, rej = of(EventType.CANDIDATE_EMITTED), of(EventType.CANDIDATE_REJECTED)
        risk, siz = of(EventType.RISK_EVALUATED), of(EventType.SIZING_EVALUATED)
        intent, sub = of(EventType.ORDER_INTENT), of(EventType.SUBMISSION_RESULT)
        trans, brk = of(EventType.ORDER_TRANSITION), of(EventType.BROKER_EVENT)
        fills, settled = of(EventType.FILL_RECORDED), of(EventType.PORTFOLIO_SETTLED)
        recon, fin = of(EventType.RECONCILIATION_RESULT), of(EventType.DECISION_FINALIZED)
        record = fin[-1].payload["decision_record"] if fin else None
        sections = {
            "started": started, "snapshot": snap, "candidate": cand, "candidate_rejected": rej, "risk": risk,
            "sizing": siz, "order_intent": intent, "submission": sub, "order_transitions": trans,
            "broker_events": brk, "fills": fills, "portfolio_settled": settled, "reconciliation": recon,
            "finalized": fin, "failures": of(EventType.OPERATIONAL_FAILURE), "corrections": of(EventType.CORRECTION),
        }  # fmt: skip
        versions: dict = {}
        if started:
            versions.update(started[0].payload.get("run_context", {}))
        if cand:
            versions["strategy_version_id"] = cand[0].payload.get("strategy_version_id")
            versions["model_version_id"] = cand[0].payload.get("model_version_id")
        if risk:
            versions["risk_rule_version_id"] = risk[0].payload.get("risk_rule_version_id")
        if snap:
            versions["data_snapshot_version"] = snap[0].payload["snapshot"].get("data_snapshot_version")
            versions["feature_set_version"] = snap[0].payload["snapshot"].get("feature_set_version")
        missing = self._missing(decision_id, record, sections)
        recon_status = "NOT_RECORDED" if not recon else ("OK" if recon[-1].payload["ok"] else "BLOCKED")
        if any(not r.payload["ok"] for r in recon):
            recon_status = "BLOCKED"
        own = [e for e in evs if e.decision_id == decision_id]
        caveats = [f"evidence_class={versions.get('evidence_class', 'UNKNOWN')}"]
        if not fin:
            caveats.append("decision is INCOMPLETE: no DECISION_FINALIZED event was persisted")
        return DecisionChain(decision_id, self.run_id, "FINALIZED" if fin else "INCOMPLETE",
                             fin[-1].payload["terminal_state"] if fin else None,
                             own[-1].event_type.value if own else "NONE", recon_status, tuple(evs),
                             {k: tuple(v) for k, v in sections.items()}, versions, record, tuple(missing), tuple(caveats))  # fmt: skip

    def _missing(self, decision_id: str, record: dict | None, sec: dict) -> list[MissingReference]:
        out: list[MissingReference] = []
        if record is None:
            return out
        have = {
            "snapshot": {e.payload["snapshot_id"] for e in sec["snapshot"]},
            "candidate": {e.payload["candidate_id"] for e in sec["candidate"]},
            "risk": {e.payload["risk_decision_id"] for e in sec["risk"]},
            "order": {e.payload["idempotency_key"] for e in sec["order_intent"]},
            "fill": {e.payload["fill_id"] for e in sec["fills"]},
        }
        ref = f"DECISION_FINALIZED/{decision_id}"

        def need(kind: str, exp: object, src: EventType) -> None:
            if exp and exp not in have[kind]:
                out.append(MissingReference(kind, str(exp), src.value, ref))

        need("snapshot", record.get("input_snapshot_id"), EventType.INPUT_SNAPSHOT_LINKED)
        need("candidate", record.get("candidate_trade_id"), EventType.CANDIDATE_EMITTED)
        need("risk", record.get("risk_decision_id"), EventType.RISK_EVALUATED)
        need("order", record.get("order_request_id"), EventType.ORDER_INTENT)
        for f in record.get("fills") or []:
            need("fill", f.get("fill_id"), EventType.FILL_RECORDED)
        return out

    def explain(self, decision_id: str) -> list[str]:
        """Human-readable explanation built ONLY from persisted facts."""
        c = self.decision_chain(decision_id)
        lines = [f"decision {decision_id}: status={c.status} terminal_state={c.terminal_state}"]
        for e in c.events:
            p = e.payload
            if e.event_type is EventType.CANDIDATE_EMITTED:
                lines.append(f"candidate {p['action']}: {p['rationale']}")
            elif e.event_type is EventType.RISK_EVALUATED:
                bad = [k["check_id"] for k in p["checks"] if not k["passed"]]
                lines.append(f"risk {p['verdict']}; failed checks: {bad or 'none'}")
            elif e.event_type is EventType.SIZING_EVALUATED:
                lines.append(f"sizing {p['outcome']} qty={p['quantity']}: {p['reason']}")
            elif e.event_type is EventType.FILL_RECORDED:
                lines.append(f"fill {p['quantity']} @ {p['price']}")
            elif e.event_type is EventType.OPERATIONAL_FAILURE:
                lines.append(f"failure {p['error_code']}: {p['message']}")
        for m in c.missing_references:
            lines.append(f"MISSING {m.kind} {m.expected_id} (expected from {m.expected_source})")
        return lines


def decision_record_from_dict(d: dict):
    """Rebuild a typed `DecisionRecord` from a persisted JSON dict (legacy Slice 5-7 artifacts included).

    Pure; accepts records without any Slice 8 field because DecisionRecord gained none (ADR-14)."""
    from datetime import datetime
    from decimal import Decimal  # noqa: F401

    from domain.models.decision_record import DataSourceRef, DecisionRecord
    from domain.models.enums import FillType, TerminalState
    from domain.models.order_request import Fill

    if d.get("__type__") not in (None, "DecisionRecord"):
        raise JournalError(ErrorCode.JOURNAL_UNSUPPORTED_SCHEMA, f"not a DecisionRecord: {d.get('__type__')!r}")

    def dt(v):  # noqa: ANN001
        return None if v is None else datetime.fromisoformat(v)

    try:
        fills = tuple(Fill(f["order_id"], float(f["quantity"]) if not isinstance(f["quantity"], str) else float(f["quantity"]),
                           float(f["price"]), dt(f["timestamp"]), FillType(f["fill_type"]), f["fill_id"])
                      for f in d.get("fills", []))  # fmt: skip
        return DecisionRecord(
            instrument_id=d["instrument_id"], cycle_timestamp=dt(d["cycle_timestamp"]), autonomy_level=d["autonomy_level"],
            input_snapshot_id=d["input_snapshot_id"],
            data_sources=tuple(DataSourceRef(s["source"], s["version"], dt(s["timestamp"])) for s in d["data_sources"]),
            terminal_state=TerminalState(d["terminal_state"]), risk_rule_version_id=d["risk_rule_version_id"],
            config_version_id=d["config_version_id"], decision_id=d["decision_id"],
            candidate_trade_id=d.get("candidate_trade_id"), rationale=d.get("rationale"),
            strategy_version_id=d.get("strategy_version_id"), model_version_id=d.get("model_version_id"),
            cost_estimate_id=d.get("cost_estimate_id"), risk_decision_id=d.get("risk_decision_id"),
            order_request_id=d.get("order_request_id"), order_id=d.get("order_id"), fills=fills,
            actual_cost_id=d.get("actual_cost_id"),
            realized_pnl_delta=None if d.get("realized_pnl_delta") is None else float(d["realized_pnl_delta"]),
            finalized_at=dt(d.get("finalized_at")),
        )  # fmt: skip
    except (KeyError, ValueError, TypeError) as e:
        raise JournalError(ErrorCode.JOURNAL_UNSUPPORTED_SCHEMA, f"cannot read DecisionRecord: {type(e).__name__}: {e}") from e
