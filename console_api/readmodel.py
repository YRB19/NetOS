"""Read models for the Operator Console. Every value is taken from a persisted artifact; nothing is recomputed from
today's configuration, nothing is fabricated. Unknown stays `None` and the UI renders it as Unknown/Unavailable."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from console_api.errors import ApiError, valid_id
from console_api.store import ArtifactStore, LoadedJournal, event_dict
from observability.decision_log.events import EventType as ET
from observability.decision_log.redaction import sanitize_text

EVIDENCE_LABELS = {
    "SYNTHETIC_INFRASTRUCTURE": "Synthetic infrastructure evidence",
    "SYNTHETIC_INTEGRATION": "Synthetic infrastructure evidence",
    "HISTORICAL_VERIFIED_FOR_STATED_CHECKS": "Historical replay, provenance verified (stated checks only)",
    "HISTORICAL_UNVERIFIED": "Historical replay, provenance UNVERIFIED",
    "PAPER_EXECUTION": "Paper execution",
    "BROKER_SANDBOX": "Broker sandbox",
    "LIVE": "Live evidence",
}
SYNTHETIC = {"SYNTHETIC_INFRASTRUCTURE", "SYNTHETIC_INTEGRATION"}
STAGES = [  # (stage key, event types)
    ("snapshot", (ET.INPUT_SNAPSHOT_LINKED,)),
    ("candidate", (ET.CANDIDATE_EMITTED, ET.CANDIDATE_REJECTED)),
    ("risk", (ET.RISK_EVALUATED,)),
    ("sizing", (ET.SIZING_EVALUATED,)),
    ("order_intent", (ET.ORDER_INTENT,)),
    ("submission", (ET.SUBMISSION_RESULT,)),
    ("order_lifecycle", (ET.ORDER_TRANSITION, ET.BROKER_EVENT)),
    ("fills", (ET.FILL_RECORDED,)),
    ("portfolio_settlement", (ET.PORTFOLIO_SETTLED,)),
    ("reconciliation", (ET.RECONCILIATION_RESULT,)),
    ("finalized", (ET.DECISION_FINALIZED,)),
]
HEADLINE = (
    "initial_capital",
    "final_equity",
    "net_pnl",
    "gross_pnl",
    "total_return",
    "total_transaction_costs",
    "ending_cash",
    "number_of_transactions",
    "rejected_orders",
    "unexecuted_orders",
    "decision_cycles",
    "realized_pnl_gross",
    "unrealized_pnl_gross",
)


def evidence(raw: str | None) -> dict:
    if not raw:
        return {"raw": None, "label": "Unknown (not recorded)", "synthetic": None}
    return {
        "raw": raw,
        "label": EVIDENCE_LABELS.get(raw, f"Unrecognised evidence class: {raw}"),
        "synthetic": raw in SYNTHETIC,
    }


def _dec(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _s(v):  # JSON-safe strings only; never echo raw filesystem paths
    return sanitize_text(v) if isinstance(v, str) else v


def paginate(rows: list, limit: int, offset: int) -> dict:
    return {
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "items": rows[offset : offset + limit],
    }


# ---------------------------------------------------------------- runs ----
def _reports_for(store: ArtifactStore, run_id: str) -> list[dict]:
    d = store._safe("validity", valid_id(run_id, "run_id"))
    out = []
    if d.is_dir():
        for p in sorted(d.glob("report*.json")):
            r = store.read_json(p)
            if not r or r.get("__unreadable__"):
                out.append({"report_id": p.stem, "unreadable": True})
                continue
            out.append(
                {
                    "report_id": p.stem,
                    "run_id": run_id,
                    "schema": r.get("schema"),
                    "verdict": r.get("verdict"),
                    "research_validity_verdict": r.get("research_validity_verdict"),
                    "criterion_outcome": r.get("criterion_outcome"),
                    "evidence_class": r.get("evidence_class"),
                    "protocol": r.get("protocol"),
                    "profitability_claim": r.get("profitability_claim"),
                }
            )
    return out


def run_summary(store: ArtifactStore, run_id: str) -> dict:
    valid_id(run_id, "run_id")
    rd = store.run_dir(run_id)
    result = store.read_json(rd / "result.json")
    exp = store.read_json(rd / "experiment.json")
    pipe = store.read_json(rd / "pipeline" / "pipeline.json")
    reports = _reports_for(store, run_id)
    lj = store.journal(run_id)
    has_any = (
        rd.is_dir()
        or lj.reader is not None
        or lj.error is not None
        and lj.error["code"] != "JOURNAL_NOT_FOUND"
        or reports
    )
    if not has_any:
        raise ApiError(404, "RUN_NOT_FOUND", "no artifacts recorded for this run")
    warnings: list[dict] = []
    ev_raw, ev_src = None, "unknown"
    n_dec = n_inc = 0
    if lj.reader is not None:
        first = next((e for e in lj.reader.events() if e.event_type is ET.DECISION_STARTED), None)
        if first:
            ev_raw = (first.payload.get("run_context") or {}).get("evidence_class")
            ev_src = "journal.run_context" if ev_raw else ev_src
        sums = _summaries(lj)
        n_dec, n_inc = len(sums), sum(1 for s in sums.values() if s.status == "INCOMPLETE")
    if ev_raw is None and reports and reports[0].get("evidence_class"):
        ev_raw, ev_src = reports[0]["evidence_class"], "validity_report"
    if ev_raw is None:
        warnings.append(
            w(
                "EVIDENCE_CLASS_UNKNOWN",
                "No evidence class was recorded; environment cannot be established.",
            )
        )
    if lj.error and lj.error["code"] != "JOURNAL_NOT_FOUND":
        warnings.append(w(lj.error["code"], lj.error["message"]))
    elif lj.reader is None:
        warnings.append(w("NO_JOURNAL", "No decision journal recorded for this run."))
    elif not lj.verified:
        warnings.append(w("JOURNAL_UNVERIFIED", "Journal failed integrity verification."))
    if n_inc:
        warnings.append(w("INCOMPLETE_DECISIONS", f"{n_inc} decision(s) never finalized."))
    metrics = (result or {}).get("metrics") or {}
    if metrics.get("exit_costs_included") is False:
        warnings.append(
            w(
                "EXIT_COSTS_EXCLUDED",
                "Reported P&L is unliquidated mark-to-market; exit costs are not included.",
            )
        )
    if result and result.get("failure"):
        warnings.append(w("RUN_FAILURE", str(result["failure"])[:200]))
    if result and result.get("criteria_assessment") == "NOT_ASSESSED":
        warnings.append(
            w("CRITERIA_NOT_ASSESSED", "Pre-registered criteria were not assessed for this run.")
        )
    if pipe is None and result is not None:
        warnings.append(
            w(
                "NO_PIPELINE_ARTIFACTS",
                "No simulation pipeline artifacts (risk/orders/reconciliation) for this run.",
            )
        )
    cfg = (result or {}).get("config") or {}
    ident = (pipe or {}).get("identity") or {}
    status = (result or {}).get("status") or (
        "INCOMPLETE" if n_inc else ("UNKNOWN" if lj.reader is None else "JOURNAL_ONLY")
    )
    return {
        "run_id": run_id,
        "run_type": (
            "SIMULATION_PIPELINE"
            if pipe
            else "RESEARCH_HARNESS"
            if result
            else "JOURNAL_ONLY"
            if lj.reader or lj.error
            else "REPORT_ONLY"
        ),
        "status": status,
        "evidence": evidence(ev_raw) | {"source": ev_src},
        "strategy_version_id": (result or exp or {}).get("strategy_version_id"),
        "baseline_strategy_version_ids": (result or exp or {}).get("baseline_strategy_version_ids"),
        "dataset": {
            "data_snapshot_version": (result or exp or {}).get("data_snapshot_version"),
            "window_start": (result or exp or {}).get("window_start"),
            "window_end": (result or exp or {}).get("window_end"),
            "universe_schedule": (result or exp or {}).get("universe_schedule"),
        },
        "versions": {
            "cost_schedule_version": (result or exp or {}).get("cost_schedule_version"),
            "feature_set_version": (result or {}).get("feature_set_version"),
            "harness_version": (result or {}).get("harness_version"),
            "risk_config": (ident.get("risk") or {}).get("label"),
            "broker_config": (ident.get("broker") or {}).get("label"),
            "kill_switch_at_run": ident.get("kill_switch"),
        },
        "hypothesis": cfg.get("hypothesis"),
        "evaluation_period": cfg.get("evaluation_period"),
        "criteria_assessment": (result or {}).get("criteria_assessment"),
        "metrics": {k: metrics.get(k) for k in HEADLINE if k in metrics},
        "metrics_basis": metrics.get("basis"),
        "pipeline_summary": (pipe or {}).get("summary"),
        "journal": {
            "present": lj.reader is not None,
            "verified": lj.verified if lj.reader else None,
            "decisions": n_dec if lj.reader else None,
            "incomplete_decisions": n_inc if lj.reader else None,
        },
        "reports": [
            {k: r.get(k) for k in ("report_id", "verdict", "criterion_outcome")} for r in reports
        ],
        "available": {
            "result": result is not None,
            "pipeline": pipe is not None,
            "journal": lj.reader is not None,
            "reports": len(reports),
            "equity_curve": (rd / "equity_curve.jsonl").is_file(),
        },
        "warnings": warnings,
    }


def w(code: str, message: str) -> dict:
    return {"code": code, "message": _s(message)}


def list_runs(store: ArtifactStore, q: dict, limit: int, offset: int) -> dict:
    rows = []
    for rid in store.run_ids():
        try:
            rows.append(run_summary(store, rid))
        except ApiError:
            continue
    text = (q.get("q") or "").lower()
    for key, path in (
        ("status", ("status",)),
        ("run_type", ("run_type",)),
        ("evidence_class", ("evidence", "raw")),
    ):
        val = q.get(key)
        if val:
            rows = [
                r for r in rows if (r[path[0]] if len(path) == 1 else r[path[0]][path[1]]) == val
            ]
    if text:
        rows = [
            r
            for r in rows
            if text
            in " ".join(
                str(x)
                for x in (
                    r["run_id"],
                    r["strategy_version_id"],
                    r["status"],
                    r["evidence"]["label"],
                )
            ).lower()
        ]
    rows.sort(key=lambda r: ((r["dataset"]["window_start"] or ""), r["run_id"]), reverse=True)
    out = paginate(rows, limit, offset)
    out["demo"] = store.demo
    return out


# ------------------------------------------------------------ decisions ----
def _summaries(lj: LoadedJournal) -> dict:
    """Per-decision summaries via the existing reader (paged: reader MAX_PAGE=1000). Cached per loaded journal."""
    if lj.reader is None:
        return {}
    cached = getattr(lj, "_sums", None)
    if cached is None:
        cached, off = {}, 0
        while True:
            page = lj.reader.list_decisions(limit=1000, offset=off)
            cached.update({s.decision_id: s for s in page})
            if len(page) < 1000:
                break
            off += 1000
        lj._sums = cached  # type: ignore[attr-defined]
    return cached


def _by_decision(lj: LoadedJournal) -> dict[str, list]:
    g: dict[str, list] = defaultdict(list)
    for e in lj.reader.events():
        ids = [e.decision_id] if e.decision_id else list(e.links.get("decision_ids") or [])
        for d in ids:
            g[d].append(e)
    return g


def _of(evs, t):
    return [e for e in evs if e.event_type is t]


def decision_row(s, evs) -> dict:
    cand = (_of(evs, ET.CANDIDATE_EMITTED) or [None])[0]
    rej = (_of(evs, ET.CANDIDATE_REJECTED) or [None])[0]
    risk = (_of(evs, ET.RISK_EVALUATED) or [None])[0]
    siz = (_of(evs, ET.SIZING_EVALUATED) or [None])[0]
    trans = _of(evs, ET.ORDER_TRANSITION)
    fills = _of(evs, ET.FILL_RECORDED)
    recon = _of(evs, ET.RECONCILIATION_RESULT)
    failed = [
        c["check_id"] for c in (risk.payload["checks"] if risk else []) if not c.get("passed")
    ]
    recon_status = (
        "NOT_RECORDED"
        if not recon
        else ("OK" if all(r.payload.get("ok") for r in recon) else "BLOCKED")
    )
    fq = sum((_dec(f.payload.get("quantity")) or Decimal(0)) for f in fills)
    tags = []
    action = cand.payload["action"] if cand else None
    if action == "HOLD":
        tags.append("HOLD")
    if not cand and s.status == "FINALIZED" and not rej:
        tags.append("NO_CANDIDATE")
    if rej:
        tags.append("CANDIDATE_REJECTED")
    if risk and risk.payload["verdict"] != "APPROVE" or failed:
        tags.append("RISK_VETO")
    if siz and siz.payload.get("outcome") != "ORDER":
        tags.append("NO_TRADE")
    if s.terminal_state and s.terminal_state not in ("FILLED",) and s.terminal_state not in tags:
        tags.append(s.terminal_state)  # recorded terminal state is always filterable
    if s.status == "INCOMPLETE":
        tags.append("INCOMPLETE")
    if recon_status == "BLOCKED":
        tags.append("RECONCILIATION_BLOCKED")
    if (
        fills
        and s.status == "FINALIZED"
        and trans
        and trans[-1].payload["to_state"] in ("PARTIALLY_FILLED", "CANCELLED")
    ):
        tags.append("PARTIAL_OR_CANCELLED")
    return {
        "decision_id": s.decision_id,
        "instrument_id": s.instrument_id,
        "cycle_timestamp": s.cycle_timestamp,
        "status": s.status,
        "terminal_state": s.terminal_state,
        "last_event_type": s.last_event_type,
        "event_count": s.event_count,
        "action": action,
        "confidence": cand.payload.get("confidence") if cand else None,
        "risk_verdict": risk.payload["verdict"] if risk else None,
        "failed_risk_checks": failed,
        "sizing_outcome": siz.payload.get("outcome") if siz else None,
        "sized_quantity": siz.payload.get("quantity") if siz else None,
        "last_order_state": trans[-1].payload["to_state"] if trans else None,
        "filled_quantity": str(fq) if fills else None,
        "reconciliation_status": recon_status,
        "tags": tags,
    }


def list_decisions(store, run_id, q, limit, offset, allow_unverified=False) -> dict:
    lj = store.verified_reader(run_id, allow_unverified)
    groups, sums = _by_decision(lj), _summaries(lj)
    rows = [decision_row(s, groups.get(d, [])) for d, s in sums.items()]
    for key in ("status", "terminal_state", "action", "instrument_id", "reconciliation_status"):
        if q.get(key):
            rows = [r for r in rows if r[key] == q[key]]
    if q.get("tag"):
        rows = [r for r in rows if q["tag"] in r["tags"]]
    out = paginate(rows, limit, offset)
    out["integrity"] = integrity(lj)
    return out


def decision_detail(store, run_id, decision_id, allow_unverified=False) -> dict:
    valid_id(decision_id, "decision_id")
    lj = store.verified_reader(run_id, allow_unverified)
    try:
        ch = lj.reader.decision_chain(decision_id)
    except Exception:  # noqa: BLE001
        raise ApiError(404, "DECISION_NOT_FOUND", "no such decision in this run") from None
    by_type: dict[ET, list] = defaultdict(list)
    for e in ch.events:
        by_type[e.event_type].append(e)
    last_idx = max(
        (i for i, (_, ts) in enumerate(STAGES) if any(by_type.get(t) for t in ts)), default=-1
    )
    stages = []
    for i, (key, types) in enumerate(STAGES):
        evs = [e for t in types for e in by_type.get(t, [])]
        evs.sort(key=lambda e: e.sequence)
        note = None
        if not evs:
            note = (
                "not recorded; decision never finalized, so this stage is unresolved"
                if ch.status == "INCOMPLETE" and i > last_idx
                else "no event recorded for this stage"
            )
        stages.append(
            {
                "stage": key,
                "status": "RECORDED" if evs else "NOT_RECORDED",
                "note": note,
                "event_ids": [e.event_id for e in evs],
                "event_time": evs[0].event_time if evs else None,
                "recorded_at": evs[0].recorded_at if evs else None,
                "data_available_at": evs[0].data_available_at if evs else None,
                "facts": [_facts(e) for e in evs],
            }
        )
    return {
        "decision_id": decision_id,
        "run_id": run_id,
        "status": ch.status,
        "terminal_state": ch.terminal_state,
        "last_stage": ch.last_stage,
        "reconciliation_status": ch.reconciliation_status,
        "versions": ch.versions,
        "stages": stages,
        "events": [event_dict(e) for e in ch.events],
        "decision_record": ch.decision_record,
        "missing_references": [
            {
                "kind": m.kind,
                "expected_id": m.expected_id,
                "expected_source": m.expected_source,
                "referenced_by": m.referenced_by,
            }
            for m in ch.missing_references
        ],
        "caveats": list(ch.caveats),
        "explanation": lj.reader.explain(decision_id),
        "integrity": integrity(lj),
    }


def _facts(e) -> dict:
    p, t = e.payload, e.event_type
    f: dict = {"event_id": e.event_id, "event_type": t.value, "sequence": e.sequence}
    if t is ET.CANDIDATE_EMITTED:
        f |= {
            k: p.get(k)
            for k in (
                "action",
                "confidence",
                "size_hint",
                "uncertainty_band",
                "rationale",
                "strategy_version_id",
                "model_version_id",
            )
        }
    elif t is ET.CANDIDATE_REJECTED:
        f |= {"reason": p.get("reason"), "error_code": p.get("error_code")}
    elif t is ET.RISK_EVALUATED:
        f |= {
            "verdict": p["verdict"],
            "risk_rule_version_id": p["risk_rule_version_id"],
            "approved_qty_ceiling": p.get("approved_qty_ceiling"),
            "checks": p["checks"],
        }
    elif t is ET.SIZING_EVALUATED:
        f |= {
            k: p.get(k)
            for k in (
                "outcome",
                "reason",
                "quantity",
                "side",
                "reference_price",
                "risk_quantity_ceiling",
                "inputs",
            )
        }
    elif t is ET.ORDER_INTENT:
        f |= {
            k: p.get(k)
            for k in (
                "idempotency_key",
                "instrument_id",
                "side",
                "quantity",
                "order_type",
                "limit_price",
                "risk_decision_id",
            )
        }
    elif t is ET.SUBMISSION_RESULT:
        f |= {
            k: p.get(k)
            for k in (
                "outcome",
                "submission_status",
                "order_id",
                "broker_order_id",
                "order_state",
                "detail",
            )
        }
    elif t is ET.ORDER_TRANSITION:
        f |= {
            k: p.get(k) for k in ("order_id", "from_state", "to_state", "transition_at", "detail")
        }
    elif t is ET.BROKER_EVENT:
        f |= {
            k: p.get(k)
            for k in ("kind", "broker_order_id", "price", "quantity", "detail", "identity")
        }
    elif t is ET.FILL_RECORDED:
        f |= {
            k: p.get(k)
            for k in (
                "fill_id",
                "order_id",
                "fill_type",
                "price",
                "quantity",
                "fill_timestamp",
                "lifecycle_event_status",
                "adapter",
                "cost_note",
            )
        }
        ch = p.get("charges")
        f["charges"] = (
            {
                k: ch.get(k)
                for k in (
                    "brokerage",
                    "exchange_txn_charges",
                    "stt",
                    "sebi_fee",
                    "gst",
                    "stamp_duty",
                    "total_cost",
                    "gross_turnover",
                )
            }
            if isinstance(ch, dict)
            else None
        )
        f["charges_basis"] = "ESTIMATE_FROM_SIMULATED_SCHEDULE_NOT_A_BROKER_CONTRACT_NOTE"
    elif t is ET.PORTFOLIO_SETTLED:
        ps = p.get("portfolio_snapshot") or {}
        f |= {
            "fill_id": p.get("fill_id"),
            "newly_applied": p.get("newly_applied"),
            "cash": ps.get("cash"),
            "equity": ps.get("equity"),
            "positions": ps.get("positions"),
            "cumulative_costs": ps.get("cumulative_costs"),
            "source": ps.get("source"),
            "stage": ps.get("stage"),
        }
    elif t is ET.RECONCILIATION_RESULT:
        f |= {"ok": p.get("ok"), "mismatches": p.get("mismatches")}
    elif t is ET.INPUT_SNAPSHOT_LINKED:
        f |= {
            "snapshot_id": p.get("snapshot_id"),
            "snapshot_content_hash": p.get("snapshot_content_hash"),
        }
    elif t is ET.DECISION_FINALIZED:
        f |= {"terminal_state": p.get("terminal_state")}
    return f


# ---------------------------------------------------- orders / recon / risk ----
def orders(store, run_id, allow_unverified=False) -> dict:
    lj = store.verified_reader(run_id, allow_unverified)
    od: dict[str, dict] = {}
    alias: dict[str, str] = {}

    def fresh(key: str) -> dict:
        return {
            "order_key": key,
            "order_id": None,
            "idempotency_key": None,
            "decision_ids": [],
            "instrument_id": None,
            "side": None,
            "quantity": None,
            "submission_outcome": None,
            "submission_detail": None,
            "state_history": [],
            "broker_events": [],
            "fills": [],
            "broker_order_id": None,
        }

    def resolve(*ids) -> dict | None:
        """Canonical order slot for any of (idempotency key, order id, broker order id); merges slots proven to be the same order."""
        ids = [i for i in ids if i]
        if not ids:
            return None
        keys = []
        for i in ids:
            k = alias.get(i)
            if k and k not in keys:
                keys.append(k)
        if not keys:
            keys = [ids[0]]
            od[ids[0]] = fresh(ids[0])
        main = od[keys[0]]
        for k in keys[1:]:
            other = od.pop(k)
            for f in ("state_history", "broker_events", "fills", "decision_ids"):
                main[f] += [x for x in other[f] if x not in main[f]]
            for f, v in other.items():
                if main.get(f) is None and v is not None and f != "order_key":
                    main[f] = v
            for i, kk in list(alias.items()):
                if kk == k:
                    alias[i] = keys[0]
        for i in ids:
            alias[i] = keys[0]
        return main

    for e in lj.reader.events():
        p, L = e.payload, e.links
        idem = L.get("idempotency_key") or p.get("idempotency_key")
        oid = L.get("order_id") or p.get("order_id")
        bo = p.get("broker_order_id")
        o = None
        if e.event_type is ET.ORDER_INTENT:
            o = resolve(idem)
            o |= {
                "idempotency_key": idem,
                "instrument_id": p.get("instrument_id"),
                "side": p.get("side"),
                "quantity": p.get("quantity"),
            }
        elif e.event_type is ET.SUBMISSION_RESULT:
            o = resolve(idem, oid, bo)
            o |= {
                "order_id": oid or o["order_id"],
                "submission_outcome": p.get("outcome"),
                "submission_detail": _s(p.get("detail")),
                "broker_order_id": bo or o["broker_order_id"],
                "idempotency_key": idem or o["idempotency_key"],
            }
        elif e.event_type is ET.ORDER_TRANSITION:
            o = resolve(idem, oid)
            o["order_id"] = oid or o["order_id"]
            o["state_history"].append(
                {
                    "from": p["from_state"],
                    "to": p["to_state"],
                    "at": p.get("transition_at"),
                    "detail": _s(p.get("detail")),
                }
            )
        elif e.event_type is ET.BROKER_EVENT:
            o = resolve(bo) if bo and bo in alias else resolve(oid, bo)
            if o is not None:
                o["broker_order_id"] = o["broker_order_id"] or bo
                o["broker_events"].append(
                    {
                        "kind": p.get("kind"),
                        "price": p.get("price"),
                        "quantity": p.get("quantity"),
                        "detail": _s(p.get("detail")),
                        "event_id": e.event_id,
                    }
                )
        elif e.event_type is ET.FILL_RECORDED:
            o = resolve(oid, bo)
            if o is not None:
                ch = p.get("charges")
                o["fills"].append(
                    {
                        "fill_id": p.get("fill_id"),
                        "fill_type": p.get("fill_type"),
                        "quantity": p.get("quantity"),
                        "price": p.get("price"),
                        "timestamp": p.get("fill_timestamp"),
                        "status": p.get("lifecycle_event_status"),
                        "total_charges": ch.get("total_cost") if isinstance(ch, dict) else None,
                    }
                )
        if o is not None and e.decision_id and e.decision_id not in o["decision_ids"]:
            o["decision_ids"].append(e.decision_id)
    rows = []
    for o in od.values():
        filled = sum((_dec(f["quantity"]) or Decimal(0)) for f in o["fills"])
        qty = _dec(o["quantity"])
        last = o["state_history"][-1]["to"] if o["state_history"] else None
        flags = []
        if o["submission_outcome"] != "ACCEPTED":
            flags.append("UNCERTAIN_SUBMISSION")
        if o["fills"] and qty is not None and 0 < filled < qty:
            flags.append("PARTIAL_FILL")
        if any(h["to"] == "CANCELLED" for h in o["state_history"]) and o["fills"]:
            flags.append("CANCELLED_AFTER_FILL")
        if any(b["kind"] not in ("FILL", "ACK", "ACKNOWLEDGED") for b in o["broker_events"]):
            flags.append("NON_FILL_BROKER_EVENTS")
        rows.append(o | {"last_known_state": last, "filled_quantity": str(filled), "flags": flags})
    return {
        "run_id": run_id,
        "total": len(rows),
        "items": rows,
        "integrity": integrity(lj),
        "note": "Orders with UNCERTAIN_SUBMISSION are never shown as complete; last_known_state is the last recorded lifecycle stage.",
    }


def reconciliation(store, run_id, allow_unverified=False) -> dict:
    lj = store.verified_reader(run_id, allow_unverified)
    items = [
        {
            "event_id": e.event_id,
            "decision_ids": list(
                e.links.get("decision_ids") or ([e.decision_id] if e.decision_id else [])
            ),
            "ok": e.payload.get("ok"),
            "mismatches": e.payload.get("mismatches") or [],
            "event_time": e.event_time,
            "recorded_at": e.recorded_at,
        }
        for e in lj.reader.events()
        if e.event_type is ET.RECONCILIATION_RESULT
    ]
    pr, ok = store.read_jsonl(store.run_dir(run_id) / "pipeline" / "reconciliation.jsonl")
    return {
        "run_id": run_id,
        "blocked": sum(1 for i in items if i["ok"] is False),
        "total": len(items),
        "items": items,
        "pipeline_reconciliation_rows": len(pr),
        "pipeline_reconciliation_readable": ok,
        "pipeline_reconciliation_mismatching": sum(1 for r in pr if r.get("ok") is False),
        "integrity": integrity(lj),
    }


def risk(store, run_id, allow_unverified=False) -> dict:
    lj = store.verified_reader(run_id, allow_unverified)
    stats: dict[str, dict] = {}
    vetoes, versions = [], set()
    for e in lj.reader.events():
        if e.event_type is not ET.RISK_EVALUATED:
            continue
        versions.add(e.payload["risk_rule_version_id"])
        for c in e.payload["checks"]:
            s = stats.setdefault(
                c["check_id"],
                {
                    "check_id": c["check_id"],
                    "pass": 0,
                    "fail": 0,
                    "not_evaluable": 0,
                    "examples": [],
                },
            )
            if c.get("evaluable") is False:
                s["not_evaluable"] += 1
            elif c.get("passed"):
                s["pass"] += 1
            else:
                s["fail"] += 1
                if len(s["examples"]) < 5:
                    s["examples"].append(
                        {
                            "decision_id": e.decision_id,
                            "detail": _s(c.get("detail")),
                            "evidence": c.get("evidence"),
                        }
                    )
        if e.payload["verdict"] != "APPROVE":
            vetoes.append(
                {
                    "decision_id": e.decision_id,
                    "verdict": e.payload["verdict"],
                    "event_id": e.event_id,
                    "failed": [c["check_id"] for c in e.payload["checks"] if not c.get("passed")],
                }
            )
    order = [f"RR-{i}" for i in range(1, 10)]
    present = sorted(stats, key=lambda k: (k not in order, order.index(k) if k in order else 0, k))
    rr_missing = [r for r in order if r not in stats]
    pipe = (store.read_json(store.run_dir(run_id) / "pipeline" / "pipeline.json") or {}).get(
        "identity"
    ) or {}
    return {
        "run_id": run_id,
        "risk_rule_versions": sorted(versions),
        "checks": [stats[k] for k in present],
        "rr_checks_with_no_recorded_evidence": rr_missing,
        "vetoes": vetoes,
        "kill_switch_at_run": pipe.get("kill_switch"),
        "risk_config_recorded": pipe.get("risk"),
        "drawdown_halt_latched_at_end": _last_equity(store, run_id).get("drawdown_halt_latched"),
        "unresolved_reconciliation": reconciliation(store, run_id, allow_unverified)["blocked"],
        "note": "Rule outcomes come from persisted RISK_EVALUATED events. RR-checks absent here were not recorded in this run.",
        "controls": "READ-ONLY. No limit editing or kill-switch control exists in the Operator Console.",
        "integrity": integrity(lj),
    }


def _last_equity(store, run_id) -> dict:
    rows, _ = store.read_jsonl(store.run_dir(run_id) / "equity_curve.jsonl")
    return rows[-1] if rows else {}


def equity(store, run_id, limit=1000) -> dict:
    rows, ok = store.read_jsonl(store.run_dir(run_id) / "equity_curve.jsonl")
    if not rows:
        return {
            "run_id": run_id,
            "available": False,
            "points": [],
            "reason": "no equity curve recorded for this run",
        }
    step = max(1, len(rows) // limit)
    pts = []
    peak = Decimal(0)
    for r in rows:
        eq = _dec(r.get("equity"))
        peak = max(peak, eq) if eq is not None else peak
        pts.append(
            {
                "timestamp": r.get("timestamp"),
                "equity": r.get("equity"),
                "cash": r.get("cash"),
                "market_value": r.get("market_value"),
                "drawdown": str((peak - eq) / peak) if eq is not None and peak > 0 else None,
            }
        )
    last = rows[-1]
    return {
        "run_id": run_id,
        "available": True,
        "readable": ok,
        "points": pts[::step],
        "last": last,
        "positions": last.get("positions"),
        "drawdown_basis": "derived from the recorded equity curve (peak-to-current)",
        "benchmark": None,
        "benchmark_note": "Benchmark comparison is not recorded for pipeline runs; shown as Unavailable.",
    }


def integrity(lj: LoadedJournal) -> dict:
    if lj.reader is None:
        return {
            "status": "UNAVAILABLE",
            "reason": (lj.error or {}).get("message"),
            "code": (lj.error or {}).get("code"),
        }
    r = lj.report
    sums = _summaries(lj)
    return {
        "status": "VERIFIED" if lj.verified else "FAILED",
        "event_count": r.event_count,
        "head_hash": r.head_hash,
        "content_digest": r.content_digest,
        "errors": [list(e) for e in r.errors][:20],
        "decisions": len(sums),
        "incomplete_decisions": sum(1 for s in sums.values() if s.status == "INCOMPLETE"),
        "missing_reference_count": _missing_count(lj, sums),
        "warning": None
        if lj.verified
        else "UNVERIFIED: journal contents may have been altered or truncated",
    }


def _missing_count(lj, sums) -> int:
    n = 0
    for d in sums:
        try:
            n += len(lj.reader.decision_chain(d).missing_references)
        except Exception:  # noqa: BLE001
            n += 1
    return n


def run_integrity(store, run_id) -> dict:
    lj = store.journal(run_id)
    out = integrity(lj)
    ref = store.read_json(store.run_dir(run_id) / "pipeline" / "journal_ref.json")
    cross = None
    if ref and lj.report and not ref.get("__unreadable__"):
        cross = {
            "pipeline_journal_ref_matches": ref.get("content_digest") == lj.report.content_digest
            and ref.get("event_count") == lj.report.event_count
        }
    return {"run_id": run_id, "journal": out, "pipeline_journal_ref": cross}


# ------------------------------------------------------------- research ----
def reports(store, limit, offset, run_id=None) -> dict:
    rows = []
    for rid in [valid_id(run_id, "run_id")] if run_id else store.run_ids():
        rows += _reports_for(store, rid)
    return paginate(rows, limit, offset)


def report_detail(store, run_id, report_id) -> dict:
    valid_id(report_id, "report_id")
    p = store._safe("validity", valid_id(run_id, "run_id"), f"{report_id}.json")
    r = store.read_json(p)
    if r is None:
        raise ApiError(404, "REPORT_NOT_FOUND", "no such evaluation report")
    if r.get("__unreadable__"):
        raise ApiError(422, "REPORT_CORRUPT", "evaluation report could not be parsed")
    # Two deliberately separate lenses; the UI must not merge them.
    return {
        "report_id": report_id,
        "run_id": run_id,
        "evidence": evidence(r.get("evidence_class")),
        "research_validity": {
            "verdict": r.get("research_validity_verdict") or r.get("verdict"),
            "meaning": r.get("verdict_meaning"),
            "verification_problems": r.get("verification_problems"),
            "contamination": r.get("contamination"),
            "dataset_quality": r.get("dataset_quality"),
            "walk_forward": r.get("walk_forward"),
            "statistical_validation": r.get("statistical_validation"),
            "trial_accounting": r.get("trial_accounting"),
            "purge_embargo": r.get("purge_embargo"),
            "holdout": r.get("holdout"),
            "reasons": r.get("reasons"),
        },
        "criteria_and_performance": {
            "criterion_outcome": r.get("criterion_outcome"),
            "admissible_as_evidence": r.get("criterion_outcome_admissible_as_evidence"),
            "criteria_assessment": r.get("criteria_assessment"),
            "metrics": r.get("metrics"),
            "profitability_claim": r.get("profitability_claim"),
        },
        "protocol": r.get("protocol"),
        "links": r.get("links"),
        "regimes": r.get("regimes"),
        "uncertainty_notice": r.get("uncertainty_notice"),
        "report_hash": r.get("report_hash"),
        "raw_schema": r.get("schema"),
    }


def protocols(store) -> dict:
    d = store.root / "protocols"
    items = []
    if d.is_dir():
        for fam in sorted(p for p in d.iterdir() if p.is_dir()):
            for f in sorted(fam.glob("v*.json")):
                j = store.read_json(f)
                items.append(
                    {
                        "protocol_id": fam.name,
                        "file": f.stem,
                        "unreadable": bool(j and j.get("__unreadable__")),
                        "version": (j or {}).get("version"),
                        "hash": (j or {}).get("protocol_hash") or (j or {}).get("hash"),
                        "hypothesis": (j or {}).get("hypothesis"),
                        "mode": (j or {}).get("mode"),
                        "registered_at": (j or {}).get("registered_at"),
                        "detail": None if (j or {}).get("__unreadable__") else j,
                    }
                )
    return {"total": len(items), "items": items}


def trials(store, limit, offset) -> dict:
    rows, ok = store.read_jsonl(store.root / "trials" / "ledger.jsonl")
    chain_ok, prev = True, "GENESIS"
    for r in rows:
        if r.get("prev_hash") != prev:
            chain_ok = False
        prev = r.get("entry_hash")
    items = [
        {
            k: r.get(k)
            for k in (
                "attempt_id",
                "protocol_id",
                "protocol_hash",
                "lifecycle",
                "outcome",
                "mode",
                "holdout_id",
                "holdout_exposed",
                "holdout_reused",
                "dataset_hash",
                "cost_schedule_version",
                "parent_trial_id",
                "entry_hash",
                "prev_hash",
            )
        }
        for r in rows
    ]
    out = paginate(items, limit, offset)
    out |= {
        "ledger_readable": ok,
        "chain_links_consistent": chain_ok and ok,
        "chain_note": "link continuity only; full hash re-verification is performed by the research ledger itself",
    }
    return out


# --------------------------------------------------------------- health ----
def health(store) -> dict:
    ids = store.run_ids()
    return {
        "status": "ok",
        "read_only": True,
        "demo": store.demo,
        "demo_warning": (store.demo_info or {}).get("warning") if store.demo else None,
        "runs": len(ids),
        "bind": "loopback-only",
        "trading_authority": "NONE",
    }


def overview(store, run_id) -> dict:
    s = run_summary(store, run_id)
    out = {
        "run": s,
        "equity": equity(store, run_id, 200),
        "windows": {"decisions": "all decisions in the selected run's journal"},
    }
    if s["journal"]["present"]:
        try:
            lj = store.verified_reader(run_id, allow_unverified=True)
            sums = _summaries(lj)
            groups = _by_decision(lj)
            rows = [decision_row(sm, groups.get(d, [])) for d, sm in sums.items()]
            by_t: dict[str, int] = defaultdict(int)
            tags: dict[str, int] = defaultdict(int)
            for r in rows:
                by_t[r["terminal_state"] or "INCOMPLETE"] += 1
                for t in r["tags"]:
                    tags[t] += 1
            out["decisions"] = {
                "total": len(rows),
                "by_terminal_state": dict(by_t),
                "by_tag": dict(tags),
                "recent": rows[-8:][::-1],
                "source": "decision journal",
            }
            out["orders"] = {
                "total": (o := orders(store, run_id, True))["total"],
                "by_last_state": _count(x["last_known_state"] or "UNKNOWN" for x in o["items"]),
                "flagged": sum(1 for x in o["items"] if x["flags"]),
            }
            out["reconciliation"] = {
                k: v
                for k, v in reconciliation(store, run_id, True).items()
                if k in ("blocked", "total")
            }
            out["integrity"] = integrity(lj)
        except ApiError as e:
            out["decisions_error"] = e.body()["error"]
    else:
        out["decisions"] = None
    return out


def _count(it) -> dict:
    d: dict[str, int] = defaultdict(int)
    for x in it:
        d[x] += 1
    return dict(d)


def _num(v):
    if v is None or v == "" or v == "None":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def ai_signals(store, run_id, allow_unverified: bool = False) -> dict:
    """Slice 11: read-only summary of the AI research-signal events recorded in this run's journal.

    Derived ONLY from persisted AI_SIGNAL_EVALUATED events. If none exist the panel reports AI as not
    used for this run (an AI-DISABLED run) - nothing is invented, no provider is contacted.
    """
    lj = store.verified_reader(run_id, allow_unverified=allow_unverified)
    evs = [e for e in lj.reader.events() if e.event_type is ET.AI_SIGNAL_EVALUATED]
    base = {"run_id": run_id, "label": "RESEARCH SIGNAL ONLY", "read_only": True}
    if not evs:
        return {**base, "ai_used": False, "run_label": "AI-DISABLED",
                "provider": "DISABLED", "disclosure_source": "NOT_CONNECTED",
                "reason": "no AI_SIGNAL_EVALUATED events in this run's journal"}  # fmt: skip
    status_counts: dict = {}
    applied = 0
    tokens_in = tokens_out = 0
    tokens_known = False
    cost = 0.0
    cost_known = False
    models, model_versions, prompts, schemas, providers, adjustments = (
        set(),
        set(),
        set(),
        set(),
        set(),
        set(),
    )
    rows = []
    for e in evs:
        p = e.payload
        sig = p.get("signal") or {}
        st = sig.get("provider_status") or p.get("provider_status") or "NO_SIGNAL_RECORD"
        status_counts[st] = status_counts.get(st, 0) + 1
        applied += 1 if p.get("applied") else 0
        # Journal payloads persist numbers as strings; coerce defensively and never invent a value.
        ti, to, co = (
            _num(sig.get("usage_input_units")),
            _num(sig.get("usage_output_units")),
            _num(sig.get("estimated_cost_usd")),
        )
        if ti is not None:
            tokens_in += int(ti)
            tokens_known = True
        if to is not None:
            tokens_out += int(to)
            tokens_known = True
        if co is not None:
            cost += co
            cost_known = True
        for bucket, key in ((models, "model_identifier"), (prompts, "prompt_hash"),
                            (schemas, "output_schema_version"), (providers, "provider_name")):  # fmt: skip
            if sig.get(key):
                bucket.add(sig[key])
        if p.get("model_version_id"):
            model_versions.add(p["model_version_id"])
        if p.get("adjustment_version"):
            adjustments.add(p["adjustment_version"])
        interp = sig.get("interpretation") or {}
        rows.append({
            "decision_id": e.decision_id, "candidate_id": p.get("candidate_id"), "instrument_id": sig.get("instrument_id"),
            "provider_status": st, "applied": bool(p.get("applied")), "outcome_reason": p.get("outcome_reason"),
            "status": interp.get("status"), "sentiment": interp.get("sentiment"), "materiality": interp.get("materiality"),
            "confidence_adjustment": interp.get("confidence_adjustment"),
            "original_confidence": p.get("original_confidence"), "adjusted_confidence": p.get("adjusted_confidence"),
            "document_ids": sig.get("document_ids") or [], "detail": sig.get("detail"),
        })  # fmt: skip
    real = bool(providers - {"STUB", "NONE"})
    return {
        **base, "ai_used": True, "run_label": "AI-ENABLED",
        "provider": "REAL_PROVIDER_RECORDED" if real else "STUB_OR_OFFLINE (no real model was called)",
        "provider_names": sorted(providers), "models": sorted(models), "model_versions": sorted(model_versions),
        "prompt_hashes": sorted(prompts), "output_schema_versions": sorted(schemas),
        "adjustment_versions": sorted(adjustments), "events": len(evs), "adjusted_confidence_events": applied,
        "status_counts": status_counts,
        "no_signal_or_unknown": sum(n for k, n in status_counts.items() if k != "OK"),
        "tokens": {"input": tokens_in, "output": tokens_out} if tokens_known else None,
        "estimated_cost_usd": cost if cost_known else None,
        "disclosure_source": "RECORDED_IN_JOURNAL", "rows": rows[:200],
    }  # fmt: skip
