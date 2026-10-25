"""Pipeline-side journaling adapter (Slice 8). Builds typed payloads from execution-side objects and
writes them through `observability.decision_log` so the journal package itself stays free of execution code.

Every call is REQUIRED: a journal failure becomes `ResearchRunFailure(JOURNAL_FAILURE)`, never a silent
downgrade. Nothing here recomputes historical facts: payloads are captured from the objects that existed
at the moment of the decision.
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from domain.models.decision_record import DataSourceRef, DecisionRecord
from domain.models.enums import TerminalState
from observability.decision_log.events import EventType, JournalError
from observability.decision_log.recorder import JournalRecorder, decision_id_for
from research.harness.failures import FailureCategory, ResearchRunFailure
from research.harness.jsonio import jsonable
from shared.versioning.content_hash import hash_json_stable

AUTONOMY = 0


def snapshot_payload(snap) -> dict:  # noqa: ANN001
    body = {
        "snapshot_id": snap.snapshot_id, "instrument_id": snap.instrument_id,
        "decision_timestamp": snap.decision_timestamp, "feature_values": dict(snap.feature_values),
        "feature_set_version": snap.feature_set_version, "data_snapshot_version": snap.data_snapshot_version,
        "universe_version": snap.universe_version, "is_permitted": snap.is_permitted,
        "reference_price": snap.reference_price, "incomplete": snap.incomplete,
        "missing_fields": list(snap.missing_fields),
        "source_refs": [{"instrument_id": r.instrument_id, "bar_timestamp": r.timestamp, "source": r.source}
                        for r in snap.source_refs],
    }  # fmt: skip
    return {"snapshot_id": snap.snapshot_id, "snapshot_content_hash": hash_json_stable(jsonable(body)), "snapshot": body}


def portfolio_payload(portfolio, marks: dict, as_of: datetime, stage: str) -> dict:  # noqa: ANN001
    """`marks=None` means 'not marked at this stage': value/equity/unrealized are then None (unknown), never guessed."""
    mv = portfolio.market_value(marks) if marks is not None else None
    return {
        "stage": stage, "as_of": as_of, "cash": portfolio.cash, "positions": portfolio.positions_snapshot(),
        "market_value": mv, "equity": None if mv is None else portfolio.cash + mv,
        "unrealized_pnl_gross": portfolio.unrealized_pnl_gross(marks) if marks is not None else None,
        "realized_pnl_gross": portfolio.realized_pnl_gross, "cumulative_costs": portfolio.cumulative_costs,
        "source": "RESEARCH_PORTFOLIO_IN_MEMORY",
    }  # fmt: skip


class RunJournal:
    def __init__(self, recorder: JournalRecorder, run_context: dict, version: str) -> None:
        self.rec = recorder
        self.ctx = run_context
        self.version = version
        self.open: dict[str, str] = {}  # decision_id -> last stage
        self.failed_fatally = False
        self.stage_seconds: dict[str, float] = {}

    # -- core ---------------------------------------------------------------
    def _e(self, et: EventType, payload: dict, *, did: str | None = None, key: str = "", links: dict | None = None,
           at: datetime | None = None) -> None:
        t0 = time.perf_counter()
        try:
            self.rec.emit(et, payload, decision_id=did, key=key, links=links, event_time=at)
        except JournalError as e:
            self.failed_fatally = True
            raise ResearchRunFailure(FailureCategory.JOURNAL_FAILURE, f"required journal write failed ({et.value}): {e}",
                                     journal_error_code=e.code.value, event_type=et.value) from e  # fmt: skip
        finally:
            self.stage_seconds["journal_append"] = self.stage_seconds.get("journal_append", 0.0) + (time.perf_counter() - t0)
        if did:
            self.open[did] = et.value

    # -- decision lifecycle ---------------------------------------------------
    def start(self, run_id: str, t: datetime, instrument_id: str, candidate_id: str | None, snap, portfolio_before: dict,
              strategy_version_id: str, universe_version: str | None) -> str:  # noqa: ANN001
        did = decision_id_for(run_id, t, instrument_id, candidate_id)
        ctx = {**self.ctx, "strategy_version_id": strategy_version_id, "universe_version": universe_version,
               "autonomy_level": AUTONOMY}  # fmt: skip
        self._e(EventType.DECISION_STARTED, {"instrument_id": instrument_id, "cycle_timestamp": t, "run_context": ctx,
                                             "portfolio_before": portfolio_before}, did=did, at=t)  # fmt: skip
        self._e(EventType.INPUT_SNAPSHOT_LINKED, snapshot_payload(snap), did=did, at=t)
        return did

    def candidate(self, did: str, c, t: datetime) -> None:  # noqa: ANN001
        self._e(EventType.CANDIDATE_EMITTED, {
            "candidate_id": c.candidate_id, "action": c.action, "size_hint": c.size_hint, "confidence": c.confidence,
            "uncertainty_band": getattr(c, "uncertainty_band", None), "rationale": c.rationale,
            "strategy_version_id": c.strategy_version_id, "model_version_id": c.model_version_id,
            "input_snapshot_id": c.input_snapshot_id, "candidate_timestamp": c.timestamp,
        }, did=did, at=t)  # fmt: skip

    def risk(self, did: str, rd, t: datetime) -> None:  # noqa: ANN001
        checks = [{"check_id": k.check_id, "passed": k.passed, "evaluable": k.evaluable, "detail": k.detail,
                   "evidence": dict(k.evidence), "outcome": "PASS" if k.passed else ("FAIL" if k.evaluable else "NOT_EVALUABLE")}
                  for k in rd.checks_evaluated]  # fmt: skip
        self._e(EventType.RISK_EVALUATED, {
            "risk_decision_id": rd.risk_decision_id, "candidate_id": rd.candidate_trade_id, "verdict": rd.final_verdict,
            "approved_qty_ceiling": rd.approved_qty, "risk_rule_version_id": rd.risk_rule_version_id,
            "config_version_id": self.ctx["config_version_id"], "reasons": list(rd.reasons), "checks": checks,
        }, did=did, at=t)  # fmt: skip

    def sizing(self, did: str, sd, inputs, cfg, ceiling, t: datetime) -> None:  # noqa: ANN001
        pf = inputs.portfolio
        self._e(EventType.SIZING_EVALUATED, {
            "candidate_id": sd.candidate_id, "risk_decision_id": sd.risk_decision_id, "outcome": sd.outcome,
            "reason": sd.reason, "quantity": sd.quantity, "side": sd.side, "target_notional": sd.target_notional,
            "reference_price": sd.reference_price, "estimated_residual_cash_before_costs": sd.estimated_residual_cash,
            "risk_quantity_ceiling": ceiling,
            "inputs": {"equity": inputs.equity, "reference_price": inputs.reference_price,
                       "pending_buy_qty": inputs.pending_buy_qty, "pending_sell_qty": inputs.pending_sell_qty,
                       "cash_balance": pf.cash_balance if pf else None,
                       "positions": [{"instrument_id": p.instrument_id, "quantity": p.quantity} for p in pf.positions] if pf else [],
                       "sizing_config": {"label": cfg.label, "cash_buffer": cfg.cash_buffer, "min_trade_notional": cfg.min_trade_notional}},
        }, did=did, at=t)  # fmt: skip

    def intent(self, did: str, req, t: datetime) -> None:  # noqa: ANN001
        self._e(EventType.ORDER_INTENT, {
            "idempotency_key": req.idempotency_key, "instrument_id": req.instrument_id, "side": req.side,
            "quantity": req.quantity, "order_type": req.order_type, "limit_price": req.limit_price,
            "risk_decision_id": req.risk_decision_id,
        }, did=did, links={"idempotency_key": req.idempotency_key}, at=t)  # fmt: skip

    def submission(self, did: str, sub, key: str, t: datetime) -> None:  # noqa: ANN001
        o = sub.record.order
        self._e(EventType.SUBMISSION_RESULT, {
            "idempotency_key": key, "outcome": sub.outcome, "detail": sub.detail, "order_id": o.order_id,
            "broker_order_id": o.broker_order_id, "order_state": o.state, "submission_status": sub.record.submission,
        }, did=did, links={"idempotency_key": key, "order_id": o.order_id}, at=t)  # fmt: skip
        self.transitions(did, sub.record.order, key)

    def transitions(self, did: str, order, key: str) -> None:  # noqa: ANN001
        for i, h in enumerate(order.state_history):  # idempotent by (order, index): re-calls add nothing
            self._e(EventType.ORDER_TRANSITION, {"order_id": order.order_id, "from_state": h.from_state, "to_state": h.to_state,
                                                 "transition_at": h.at, "detail": h.detail, "index": i},
                    did=did, key=f"{order.order_id}:{i}", links={"idempotency_key": key, "order_id": order.order_id})  # fmt: skip

    def broker_event(self, did: str, kind: str, broker_order_id: str, ident: str, detail: str | None, t: datetime,
                     extra: dict | None = None) -> None:
        self._e(EventType.BROKER_EVENT, {"kind": kind, "broker_order_id": broker_order_id, "identity": ident,
                                         "detail": detail, **(extra or {})}, did=did, key=ident, at=t)  # fmt: skip

    def fill(self, did: str, rep, apply_status: str, t: datetime) -> None:  # noqa: ANN001
        f = rep.fill
        self._e(EventType.FILL_RECORDED, {
            "fill_id": f.fill_id, "order_id": f.order_id, "broker_order_id": rep.broker_order_id, "quantity": f.quantity,
            "price": f.price, "fill_type": f.fill_type, "fill_timestamp": f.timestamp, "charges": rep.charges,
            "lifecycle_event_status": apply_status, "adapter": f"{rep.adapter_id}/{rep.adapter_version}",
            "cost_note": "charges are the simulated broker's itemised schedule output; not independently verified",
        }, did=did, key=f.fill_id, links={"fill_id": f.fill_id, "order_id": f.order_id}, at=t)  # fmt: skip

    def settled(self, did: str, fill_id: str, portfolio: dict, newly_applied: bool, t: datetime) -> None:
        self._e(EventType.PORTFOLIO_SETTLED, {"fill_id": fill_id, "portfolio_snapshot": portfolio,
                                              "newly_applied": newly_applied}, did=did, key=fill_id, at=t)  # fmt: skip

    def recon(self, key: str, ok: bool, mismatches: list, detail: dict, decision_ids: list[str], t: datetime) -> None:
        self._e(EventType.RECONCILIATION_RESULT, {"ok": ok, "mismatches": mismatches, **detail},
                key=key, links={"decision_ids": sorted(decision_ids)}, at=t)  # fmt: skip

    def finalize(self, did: str, record: DecisionRecord, t: datetime, extra: dict | None = None, legacy_id: str | None = None) -> None:
        rec = replace(record, decision_id=did)
        self._e(EventType.DECISION_FINALIZED, {
            "terminal_state": rec.terminal_state, "decision_record": rec, "legacy_decision_record_id": legacy_id,
            "record_schema": "DecisionRecord/v1 (ADR-14: no new fields)", "reconciliation_at_finalization": "PENDING_SEE_LATER_EVENTS",
            **(extra or {}),
        }, did=did, at=t)  # fmt: skip
        self.open.pop(did, None)

    def no_order_record(self, state: TerminalState, t: datetime, instrument_id: str, snap, cand, risk_rule_version_id: str,
                        cfg_id: str, risk_decision_id: str | None = None) -> DecisionRecord:  # noqa: ANN001
        return DecisionRecord(
            instrument_id=instrument_id, cycle_timestamp=t, autonomy_level=AUTONOMY, input_snapshot_id=snap.snapshot_id,
            data_sources=tuple(DataSourceRef(r.source, snap.data_snapshot_version or "UNKNOWN", r.timestamp) for r in snap.source_refs),
            terminal_state=state, risk_rule_version_id=risk_rule_version_id, config_version_id=cfg_id,
            candidate_trade_id=cand.candidate_id if cand is not None else None, rationale=cand.rationale if cand is not None else None,
            strategy_version_id=cand.strategy_version_id if cand is not None else None,
            model_version_id=cand.model_version_id if cand is not None else None,
            risk_decision_id=risk_decision_id, finalized_at=t,
        )  # fmt: skip

    def failure(self, code: str, message: str, t: datetime | None = None) -> None:
        if self.failed_fatally:
            return
        try:
            self.rec.emit(EventType.OPERATIONAL_FAILURE, {"error_code": code, "message": message,
                                                          "last_stage_by_decision": dict(self.open)},
                          key=f"{code}:{len(self.open)}", links={"decision_ids": sorted(self.open)}, event_time=t)  # fmt: skip
        except JournalError:
            self.failed_fatally = True


def money(x: Decimal | None) -> str | None:
    return None if x is None else str(x)
