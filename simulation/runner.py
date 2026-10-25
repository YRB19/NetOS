"""Offline strategy -> risk -> sizing -> simulated-broker -> portfolio pipeline (Slice 6).

Extends the Slice 5 ResearchHarness (reusing its contamination guards, replay,
portfolio, candidate validation, marks, identity and result assembly) with the
execution-safe path. Nothing here is live: no broker SDK, credentials, network or
wall clock. The runner is strategy-agnostic (duck-typed) and never lets a strategy
reach sizing or the broker except through an APPROVED RiskDecision.

Per decision cycle t:
  0. broker executes resting orders accepted before t at the bar OPEN of t (NEXT_BAR_OPEN),
     fills book into the research portfolio, ledgers are reconciled (fail closed on drift)
  1-5. replay.visible(t) -> guards -> snapshots (feature builder) -> strategy -> validation
  6. mark to market at close of t; update peak equity; latch drawdown halt
  7. each non-HOLD candidate: RiskEngine.evaluate -> (APPROVE only) size_order -> OrderRequest
     -> broker.place_order. A REJECT ends the path: no sizing, no order, no fill.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal

from data.features.context_builder import compute_market_data_snapshot_version
from data.features.universe import PermittedUniverse
from domain.models.decision_record import DataSourceRef, DecisionRecord
from domain.models.enums import Action, OrderState, RiskVerdict, TerminalState
from domain.models.market_data import MarketData
from domain.models.order_request import OrderRequest
from domain.models.portfolio import PortfolioState, PortfolioStateSource, Position
from domain.models.risk_decision import RiskDecision
from domain.models.trade import CandidateTrade
from observability.decision_log.events import ErrorCode, JournalError
from observability.decision_log.recorder import JournalRecorder
from research.contamination import guards
from research.harness.config import (
    EvaluationPeriod,
    OrderRejectionPolicy,
    ResearchConfig,
    comparison_fingerprint,
    experiment_id_for,
    experiment_payload,
    resolved_capital,
    run_id_for,
    validate_config,
    window_bounds,
)
from research.harness.failures import FailureCategory, ResearchRunFailure, RunStatus
from research.harness.jsonio import jsonable
from research.harness.metrics import compute_metrics
from research.harness.portfolio import ResearchPortfolio
from research.harness.replay import HistoricalReplay
from research.harness.runner import (
    ResearchHarness,
    UniverseTimeline,
    _dec,
    _RunState,
    _safe_universe_schedule,
)
from risk_execution.broker.adapters.simulated import SimulatedBrokerAdapter
from risk_execution.broker.interface import BrokerFillReport, OrderStatus
from risk_execution.order_lifecycle import (
    BrokerEvent,
    EventKind,
    EventStatus,
    OrderLifecycleManager,
    SubmitOutcome,
    event_from_fill_report,
)
from risk_execution.reconciliation import LedgerView, reconcile_execution
from risk_execution.risk_engine.context import PendingIntent, RiskContext
from risk_execution.risk_engine.engine import RiskEngine
from risk_execution.sizing.sizer import SizingDecision, SizingInputs, SizingOutcome, size_order
from shared.time.clock import utc_now
from shared.versioning.content_hash import hash_json_stable
from simulation.config import PipelineConfig, capital_matches
from simulation.reconcile import reconcile
from simulation.journaling import RunJournal, portfolio_payload
from simulation.result import PipelineRunResult

PIPELINE_VERSION = "simulation-pipeline-v1"
_AUTONOMY = 0  # research simulation only


@dataclass
class _Live:
    broker_order_id: str
    order_id: str
    request: OrderRequest
    candidate: CandidateTrade
    snapshot: object
    trace: dict
    risk: RiskDecision
    sizing: SizingDecision
    decision_ts: datetime
    fills: list[BrokerFillReport] = field(default_factory=list)
    pnl: Decimal = Decimal(0)
    decision_id: str = ""

    @property
    def remaining(self) -> int:
        return int(self.request.quantity) - sum(int(f.fill.quantity) for f in self.fills)


class _PState(_RunState):
    def __init__(self) -> None:
        super().__init__()
        self.risk_rows: list[dict] = []
        self.sizing_rows: list[dict] = []
        self.order_rows: list[dict] = []
        self.fill_rows: list[dict] = []
        self.recon_rows: list[dict] = []
        self.risk_vetoes = 0
        self.orders_submitted = 0
        self.no_op_candidates = 0
        self.skipped_pending = 0
        self.rj: RunJournal | None = None  # Slice 8 required decision journal
        self.journal_obj = None
        self.incomplete_snapshots = 0
        self.lifecycle = None  # OrderLifecycleManager of the run (Slice 7), exposed for inspection


class PipelineHarness(ResearchHarness):
    def run(  # type: ignore[override]
        self,
        config: ResearchConfig,
        strategy: object,
        market_data: list[MarketData],
        universe_schedule: list[PermittedUniverse],
        pipeline: PipelineConfig,
        baseline_strategy_version_ids: tuple[str, ...] | None = None,
        created_at: datetime | None = None,
        broker_fault_injector=None,  # noqa: ANN001 - TEST HOOK ONLY, see docs/simulated-broker.md
        journal_factory=None,  # noqa: ANN001 - REQUIRED: callable(run_id) -> DecisionJournal (see docs/decision-journal-observability.md)
        evidence_class: str = "SIMULATION_UNSPECIFIED",
    ) -> PipelineRunResult:
        sv = str(getattr(strategy, "strategy_version_id", "UNKNOWN_STRATEGY"))
        baselines = tuple(baseline_strategy_version_ids or (sv,))
        try:
            data_version = compute_market_data_snapshot_version(list(market_data))
        except Exception:  # noqa: BLE001
            data_version = "UNAVAILABLE"
        uni_sched = _safe_universe_schedule(universe_schedule)
        payload = experiment_payload(
            config, strategy_version_id=sv, baseline_strategy_version_ids=baselines,
            data_snapshot_version=data_version, universe_schedule=uni_sched,
        )  # fmt: skip
        try:
            p_payload = pipeline.payload()
        except Exception as e:  # noqa: BLE001
            p_payload = {"unidentifiable_pipeline": f"{type(e).__name__}: {e}"}
        payload["pipeline"] = {"version": PIPELINE_VERSION, **p_payload}
        experiment_id = experiment_id_for(payload)
        run_id = run_id_for(experiment_id, PIPELINE_VERSION)
        created = created_at or utc_now()

        st = _PState()
        try:
            self._execute_pipeline(config, pipeline, strategy, market_data, universe_schedule,
                                   run_id, st, broker_fault_injector, journal_factory, evidence_class)  # fmt: skip
            status, failure = RunStatus.COMPLETED, None
        except ResearchRunFailure as f:
            status, failure = RunStatus.FAILED, self._failure_record(f, st)
        except Exception as e:  # noqa: BLE001
            status = RunStatus.FAILED
            failure = self._failure_record(
                ResearchRunFailure(FailureCategory.UNEXPECTED_ERROR, f"{type(e).__name__}: {e}",
                                   exception_type=type(e).__name__), st)  # fmt: skip

        if st.rj is not None and failure is not None:
            st.rj.failure(failure.category.value, failure.message, st.current_decision_ts)
        base = self._assemble(config, payload, experiment_id, run_id, sv, baselines, data_version,
                              uni_sched, status, failure, st, created)  # fmt: skip
        base = replace(
            base,
            comparison_fingerprint=hash_json_stable(
                {"base": comparison_fingerprint(payload), "pipeline": payload["pipeline"]}
            ),
            harness_version=PIPELINE_VERSION,
        )
        summary = {
            "risk_vetoes": st.risk_vetoes,
            "orders_submitted": st.orders_submitted,
            "orders_filled_or_partial": sum(1 for o in st.order_rows if o["final_state"] in ("FILLED", "PARTIALLY_FILLED")),
            "no_op_candidates": st.no_op_candidates,
            "skipped_pending_order": st.skipped_pending,
            "risk_decisions": len(st.risk_rows),
            "fills": len(st.fill_rows),
        }  # fmt: skip
        return PipelineRunResult(
            run=base, pipeline_identity=payload["pipeline"],
            risk_decisions=tuple(st.risk_rows), sizing_decisions=tuple(st.sizing_rows),
            orders=tuple(st.order_rows), broker_fills=tuple(st.fill_rows),
            reconciliations=tuple(st.recon_rows), summary=summary,
            journal_ref=st.journal_obj.reference() if st.journal_obj is not None else None,
            telemetry=self._telemetry(st),
        )  # fmt: skip

    @staticmethod
    def _telemetry(st: _PState) -> dict:
        j = st.journal_obj
        lat = list(j.append_latencies_ms) if j is not None else []
        return {
            "journal_events": len(j.events()) if j is not None else 0,
            "journal_append_failures": j.append_failures if j is not None else 0,
            "journal_append_latency_ms_mean": (sum(lat) / len(lat)) if lat else None,
            "journal_append_latency_ms_max": max(lat) if lat else None,
            "journal_head_hash": j.head_hash if j is not None else None,
            "stage_seconds": dict(st.rj.stage_seconds) if st.rj is not None else {},
            "incomplete_input_snapshots": st.incomplete_snapshots,
            "reconciliation_checks": len(st.recon_rows),
            "reconciliation_unresolved_mismatches": sum(1 for r in st.recon_rows if not r.get("ok", True)),
            "open_decisions": sorted(st.rj.open) if st.rj is not None else [],
        }  # fmt: skip

    # ------------------------------------------------------------------ core
    def _execute_pipeline(self, config, pc: PipelineConfig, strategy, market_data, universes,
                          run_id, st: _PState, injector, journal_factory=None, evidence_class="SIMULATION_UNSPECIFIED") -> None:  # noqa: ANN001
        errors = validate_config(config, set(self._registry._schedules))
        errors += pc.validate()
        if not errors:
            if not capital_matches(resolved_capital(config), pc.broker):
                errors.append("broker.initial_cash must equal the research initial_capital")
            if pc.broker.cost_schedule_version != config.cost_schedule_version:
                errors.append("broker.cost_schedule_version must equal config.cost_schedule_version")
        if errors:
            raise ResearchRunFailure(FailureCategory.INVALID_CONFIGURATION, "; ".join(errors), errors=errors)
        capital = resolved_capital(config)
        schedule = self._registry.get(config.cost_schedule_version)
        oos = config.evaluation_period is EvaluationPeriod.OUT_OF_SAMPLE
        w_start, w_end = window_bounds(config)
        st.window = (w_start, w_end)
        st.run_id = run_id
        if not callable(getattr(strategy, "generate_candidate_trades", None)):
            raise ResearchRunFailure(FailureCategory.INVALID_CONFIGURATION,
                                     "strategy must implement generate_candidate_trades(...)")  # fmt: skip
        sv = str(getattr(strategy, "strategy_version_id", ""))
        if not sv:
            raise ResearchRunFailure(FailureCategory.INVALID_CONFIGURATION, "strategy has no strategy_version_id")

        report: dict = {"checks_passed": []}
        st.contamination_report = report
        guards.check_split_separation(config.split)
        report["checks_passed"].append("split_strictly_separated")
        report.update(guards.check_strategy_configuration_cutoff(config.split, oos, config.strategy_configured_through))
        report["checks_passed"].append("strategy_configuration_cutoff")
        report.update(guards.check_cost_schedule_not_from_future(
            schedule.effective_date, w_start, config.acknowledge_future_cost_schedule, schedule.version_id))  # fmt: skip
        report["checks_passed"].append("cost_schedule_not_from_future")

        timeline = UniverseTimeline(list(universes))
        replay = HistoricalReplay(market_data)
        replay.require_instruments(timeline.all_instrument_ids())
        cycles = replay.decision_timestamps(w_start, w_end)
        if not cycles:
            raise ResearchRunFailure(FailureCategory.MISSING_DATA,
                                     f"no observations inside evaluation window {w_start.isoformat()}..{w_end.isoformat()}")  # fmt: skip

        portfolio = ResearchPortfolio(capital)
        st.portfolio = portfolio
        engine = RiskEngine(pc.risk)
        risk_version_id = engine.risk_rule_version_id
        cfg_id = "cfg_" + hash_json_stable({"run_config": jsonable(config.__dict__ if hasattr(config, "__dict__") else str(config)),
                                            "pipeline": pc.payload()})[:24]  # fmt: skip
        broker = SimulatedBrokerAdapter(pc.broker, cost_model=self._cost_model)
        session = broker.authenticate()
        staleness = timedelta(days=config.max_staleness_days)
        live: dict[str, _Live] = {}
        clock = {"t": cycles[0]}
        mgr = OrderLifecycleManager(risk_version_id, lambda: clock["t"])  # Slice 7: lifecycle + halts
        st.lifecycle = mgr
        if journal_factory is None:
            raise ResearchRunFailure(FailureCategory.JOURNAL_FAILURE,
                                     "a durable decision journal is required; none was supplied (no silent downgrade)")  # fmt: skip
        try:
            jr = journal_factory(run_id)
            if getattr(jr, "run_id", None) != run_id:
                raise JournalError(ErrorCode.JOURNAL_INVALID_EVENT, "journal run_id does not match the run")
        except JournalError as e:
            raise ResearchRunFailure(FailureCategory.JOURNAL_FAILURE, f"journal could not be opened: {e}",
                                     journal_error_code=e.code.value) from e  # fmt: skip
        st.journal_obj = jr
        rj = RunJournal(JournalRecorder(jr, PIPELINE_VERSION, PIPELINE_VERSION),
                        {"run_id": run_id, "config_version_id": cfg_id, "risk_rule_version_id": risk_version_id,
                         "evidence_class": evidence_class, "pipeline_version": PIPELINE_VERSION,
                         "cost_schedule_version": config.cost_schedule_version,
                         "sizing_config_label": pc.sizing.label, "broker_config_label": pc.broker.label},
                        PIPELINE_VERSION)  # fmt: skip
        st.rj = rj
        opening = LedgerView(capital, {}, {})
        order_ts: list[datetime] = []
        prev_universe: PermittedUniverse | None = None
        peak = capital
        latched = False
        last_marks: dict[str, Decimal] = {}

        for t in cycles:
            st.current_decision_ts = t
            st.cycles += 1
            broker.set_simulated_time(t)
            clock["t"] = t
            self._settle_pipeline(t, replay, broker, session, live, portfolio, config, cfg_id,
                                  risk_version_id, st, injector, mgr, opening)  # fmt: skip

            visible = replay.visible(t)
            guards.check_observations_not_from_future(visible, t, w_end)
            universe_t = timeline.at(t)
            if universe_t is None:
                raise ResearchRunFailure(FailureCategory.MISSING_DATA,
                                         f"no universe is in force at {t.isoformat()}")  # fmt: skip
            guards.check_universe_not_from_future(universe_t, t)
            _added, removed = universe_t.diff(prev_universe)
            targets = sorted(set(universe_t.instrument_ids) | set(removed))
            snap_version = compute_market_data_snapshot_version(visible)
            snapshots = pc.feature_builder.build(
                visible, universe_t, t, market_data_snapshot_version=snap_version,
                staleness_threshold=staleness, instrument_ids=targets)  # fmt: skip
            guards.check_snapshots_not_from_future(snapshots, t)
            st.feature_set_versions.add(pc.feature_builder.feature_set_id)
            candidates = self._invoke(strategy, snapshots, universe_t, prev_universe)
            st.incomplete_snapshots += sum(1 for s_ in snapshots if getattr(s_, "incomplete", False))
            try:
                self._validate_candidates(candidates, snapshots, universe_t, t, sv)
            except ResearchRunFailure as vf:
                self._journal_invalid(st, vf, snapshots, t, run_id, cfg_id, risk_version_id, sv, universe_t,
                                      portfolio, last_marks)  # fmt: skip
                raise

            marks = self._marks(portfolio, replay, t, config.carry_forward_marks, st)
            last_marks = marks
            equity = portfolio.equity(marks)
            peak = max(peak, equity)
            if not latched and engine.drawdown_breached(equity, peak):
                latched = True

            by_inst = {s.instrument_id: s for s in snapshots}
            prices: dict[str, Decimal] = {
                s.instrument_id: _dec(s.reference_price) for s in snapshots if s.reference_price is not None
            }
            prices.update(marks)
            snap_ids = {s.instrument_id: s.snapshot_id for s in snapshots}
            pf_state = self._portfolio_state(portfolio, marks, t)
            pf_before = portfolio_payload(portfolio, marks, t, "pre_decision")
            uv = getattr(universe_t, "version", None)

            for cand in sorted(candidates, key=lambda c: (c.action is not Action.SELL, c.instrument_id)):
                snap = by_inst[cand.instrument_id]
                trace = self._new_trace(cand, snap, t, equity)
                st.decisions.append(trace)
                did = rj.start(run_id, t, cand.instrument_id, cand.candidate_id, snap, pf_before, sv, uv)
                rj.candidate(did, cand, t)

                def _no_order(state, why, _c=cand, _s=snap, _d=did, **kw) -> None:  # noqa: ANN001
                    rj.finalize(_d, rj.no_order_record(state, t, _c.instrument_id, _s, _c, risk_version_id, cfg_id,
                                                       kw.get("risk_decision_id")), t, {"reason": why})  # fmt: skip

                if cand.action is Action.HOLD:
                    trace["outcome"] = "HOLD"
                    _no_order(TerminalState.HOLD, "strategy decided HOLD")
                    continue
                if cand.action is Action.SELL and portfolio.quantity(cand.instrument_id) == 0:
                    trace["outcome"] = "NO_TRADE"
                    trace["execution_translation"] = {"outcome": "NO_TRADE", "reason": "SELL requested but nothing is held"}
                    st.no_op_candidates += 1
                    _no_order(TerminalState.NO_TRADE, "SELL requested but nothing is held")
                    continue
                if any(lv.request.instrument_id == cand.instrument_id for lv in live.values()):
                    trace["outcome"] = "SKIPPED_PENDING_ORDER_EXISTS"
                    st.skipped_pending += 1
                    _no_order(TerminalState.SKIPPED_PENDING_ORDER, "an earlier order for this instrument is unfilled")
                    st.rejections.append({"decision_timestamp": t, "instrument_id": cand.instrument_id,
                                          "order_id": None, "kind": "SKIPPED_PENDING_ORDER_EXISTS",
                                          "reason": "an earlier order for this instrument is unfilled"})  # fmt: skip
                    continue

                pend = tuple(PendingIntent(lv.request.instrument_id, lv.request.side, lv.remaining)
                             for lv in live.values() if lv.remaining > 0)  # fmt: skip
                ctx = RiskContext(
                    evaluated_at=t, portfolio=pf_state, equity=equity, peak_equity=peak,
                    reference_prices=dict(prices), pending_intents=pend,
                    permitted_instrument_ids=frozenset(universe_t.instrument_ids),
                    universe_version=universe_t.version_id if hasattr(universe_t, "version_id") else None,
                    account_scope=pc.account_scope, kill_switch=pc.kill_switch,
                    drawdown_halt_latched=latched, recent_order_timestamps=tuple(order_ts),
                    snapshot_ids=snap_ids, research_run_id=run_id, config_version_id=cfg_id,
                    expected_risk_rule_version_id=risk_version_id,
                )  # fmt: skip
                rd = engine.evaluate(cand, ctx)
                rj.risk(did, rd, t)
                st.risk_rows.append(self._risk_row(t, cand, rd))
                trace["risk"] = {"risk_decision_id": rd.risk_decision_id, "verdict": rd.final_verdict.value,
                                 "reasons": list(rd.reasons), "risk_rule_version_id": rd.risk_rule_version_id}  # fmt: skip
                if rd.final_verdict is not RiskVerdict.APPROVE:
                    st.risk_vetoes += 1
                    trace["outcome"] = "RISK_VETO"
                    st.rejections.append({"decision_timestamp": t, "instrument_id": cand.instrument_id,
                                          "order_id": None, "kind": "RISK_VETO", "reason": "; ".join(rd.reasons)})  # fmt: skip
                    vr = self._veto_record(cand, snap, rd, t, cfg_id, run_id, risk_version_id)
                    st.decision_records.append(vr)
                    rj.finalize(did, vr, t, {"reason": "; ".join(rd.reasons)}, legacy_id=vr.decision_id)
                    continue

                inputs = SizingInputs(
                    portfolio=pf_state, equity=equity, reference_price=prices.get(cand.instrument_id),
                    pending_buy_qty=sum(lv.remaining for lv in live.values()
                                        if lv.request.instrument_id == cand.instrument_id and lv.request.side is Action.BUY),
                    pending_sell_qty=sum(lv.remaining for lv in live.values()
                                         if lv.request.instrument_id == cand.instrument_id and lv.request.side is Action.SELL),
                    research_run_id=run_id,
                )  # fmt: skip
                sd = size_order(cand, rd, inputs, pc.sizing)
                rj.sizing(did, sd, inputs, pc.sizing, rd.approved_qty, t)
                st.sizing_rows.append(self._sizing_row(t, cand, sd))
                trace["sizing"] = {"outcome": sd.outcome.value, "reason": sd.reason, "quantity": sd.quantity}
                if sd.outcome is SizingOutcome.NO_TRADE:
                    trace["outcome"] = "NO_TRADE"
                    st.no_op_candidates += 1
                    _no_order(TerminalState.NO_TRADE, "sizing: " + sd.reason, risk_decision_id=rd.risk_decision_id)
                    continue
                if sd.outcome is not SizingOutcome.ORDER or sd.order_request is None:
                    _no_order(TerminalState.NO_TRADE, f"sizing {sd.outcome.value}: {sd.reason}", risk_decision_id=rd.risk_decision_id)
                    kind = "SIZING_" + sd.outcome.value
                    self._reject(trace, kind, sd.reason, config, st)
                    continue

                if mgr.halted:  # an unresolved execution state blocks every new submission; the halt
                    # is surfaced as a run failure at the next settlement
                    trace["outcome"] = "BLOCKED_EXECUTION_HALT"
                    _no_order(TerminalState.NO_TRADE, "execution halted: no new submissions", risk_decision_id=rd.risk_decision_id)
                    continue
                rj.intent(did, sd.order_request, t)  # REQUIRED pre-submission evidence: a failure here means no broker call
                sub = mgr.submit(sd.order_request, rd, broker, session)
                try:
                    rj.submission(did, sub, sd.order_request.idempotency_key, t)
                except ResearchRunFailure:
                    mgr.halt_external("JOURNAL_FAILURE", "journal write failed after a possible broker submission; "
                                      "outcome unresolved until broker lookup/reconciliation", sd.order_request.idempotency_key)  # fmt: skip
                    raise
                if (sub.outcome not in (SubmitOutcome.ACCEPTED, SubmitOutcome.REJECTED_BY_BROKER)
                        and sub.record.order.broker_order_id is None):  # outcome truly unknown: nothing to track
                    raise ResearchRunFailure(FailureCategory.RECONCILIATION_REQUIRED,
                                             f"submission outcome {sub.outcome.value}: {sub.detail}")  # fmt: skip
                status = broker.get_order_status(session, sub.record.order.broker_order_id)
                st.orders_submitted += 1
                order_ts.append(t)
                lv = _Live(status.broker_order_id, status.order_id, sd.order_request, cand, snap,
                           trace, rd, sd, t, decision_id=did)  # fmt: skip
                trace.update(outcome="PENDING", order_id=status.order_id, side=sd.side.value if sd.side else None,
                             target_quantity=sd.quantity)  # fmt: skip
                if status.state is OrderState.REJECTED:
                    live[status.broker_order_id] = lv
                    self._on_broker_reject(lv, status, t, config, cfg_id, risk_version_id, st, live)
                    continue
                live[status.broker_order_id] = lv

            cand_insts = {c_.instrument_id for c_ in candidates}
            for s_ in snapshots:  # strategy produced no candidate for this instrument: explicit NO_CANDIDATE decision
                if s_.instrument_id not in cand_insts:
                    ndid = rj.start(run_id, t, s_.instrument_id, None, s_, pf_before, sv, uv)
                    rj.finalize(ndid, rj.no_order_record(TerminalState.NO_CANDIDATE, t, s_.instrument_id, s_, None,
                                                         risk_version_id, cfg_id), t, {"reason": "strategy emitted no candidate"})  # fmt: skip

            st.equity_curve.append({
                "timestamp": t, "cash": portfolio.cash, "market_value": portfolio.market_value(marks),
                "equity": equity, "cumulative_costs": portfolio.cumulative_costs,
                "positions": portfolio.positions_snapshot(), "carried_marks": sorted(st.carried_this_cycle),
                "peak_equity": peak, "drawdown_halt_latched": latched,
            })  # fmt: skip
            st.carried_this_cycle = set()
            prev_universe = universe_t

        # orders still open when the window ends
        for lv in list(live.values()):
            status = broker.get_order_status(session, lv.broker_order_id)
            lv.trace["outcome"] = "UNEXECUTED_END_OF_WINDOW" if not lv.fills else "PARTIALLY_FILLED_END_OF_WINDOW"
            st.rejections.append({"decision_timestamp": lv.decision_ts, "instrument_id": lv.request.instrument_id,
                                  "order_id": lv.order_id, "kind": lv.trace["outcome"],
                                  "reason": "no subsequent observation inside the window to complete the order"})  # fmt: skip
            st.unexecuted += 1
            self._finalize(lv, status, cycles[-1], cfg_id, risk_version_id, st)
        live.clear()
        if mgr.halted:
            raise ResearchRunFailure(FailureCategory.RECONCILIATION_REQUIRED,
                                     "execution halted: " + "; ".join(mgr.can_submit()[1]))  # fmt: skip
        st.current_decision_ts = None
        st.metrics = compute_metrics(portfolio, last_marks, rejected_orders=st.rejected,
                                     unexecuted_orders=st.unexecuted, decision_cycles=st.cycles)  # fmt: skip
        st.metrics["pipeline"] = {"risk_vetoes": st.risk_vetoes, "orders_submitted": st.orders_submitted,
                                  "no_op_candidates": st.no_op_candidates}  # fmt: skip
        report["checks_passed"].extend(["observations_not_from_future", "snapshots_not_from_future",
                                        "universe_not_from_future"])  # fmt: skip

    # --------------------------------------------------------------- settle
    def _settle_pipeline(self, t, replay, broker, session, live, portfolio, config, cfg_id,
                         risk_version_id, st, injector, mgr, opening) -> None:  # noqa: ANN001
        opens: dict[str, Decimal] = {}
        for lv in live.values():
            bar = replay.bar_at(lv.request.instrument_id, t)
            if bar is not None:
                opens[lv.request.instrument_id] = _dec(bar.open)
        rj = st.rj
        touched = {lv.decision_id for lv in live.values() if lv.decision_id}
        reports = broker.advance(t, opens)
        if injector is not None:
            injector(broker, t)
        for rep in reports:
            lv0 = live.get(rep.broker_order_id)
            if lv0 is not None and lv0.decision_id:  # persist the incoming evidence BEFORE processing it
                rj.broker_event(lv0.decision_id, "FILL", rep.broker_order_id, rep.fill.fill_id, None, t,
                                {"quantity": rep.fill.quantity, "price": rep.fill.price})  # fmt: skip
            res = mgr.apply_event(event_from_fill_report(rep))
            if res.status is EventStatus.DUPLICATE_IGNORED:
                continue  # already accounted: a re-delivered fill must never be booked twice
            if res.status is not EventStatus.APPLIED:
                raise ResearchRunFailure(FailureCategory.RECONCILIATION_REQUIRED,
                                         f"fill {rep.fill.fill_id} not applied: {res.status.value} {res.detail}")  # fmt: skip
            lv = live[rep.broker_order_id]
            rj.fill(lv.decision_id, rep, res.status.value, t)
            price = _dec(rep.fill.price)
            qty = int(rep.fill.quantity)
            app = portfolio.apply_fill(rep.fill.fill_id, lv.request.instrument_id, lv.request.side.value, qty, price,
                                       rep.charges.total_cost, order_id=rep.fill.order_id, source=rep.adapter_id)
            mgr.mark_portfolio_applied(rep.fill.fill_id)
            rj.settled(lv.decision_id, rep.fill.fill_id, portfolio_payload(portfolio, None, t, "post_settlement"),
                       app.change is not None, t)  # fmt: skip
            if app.change is None:  # portfolio had already booked this fill (ADR-13): confirmed, no second effect
                continue
            change = app.change
            lv.fills.append(rep)
            lv.pnl += change.realized_pnl_gross
            row = {
                "order_id": lv.order_id, "broker_order_id": rep.broker_order_id, "fill_id": rep.fill.fill_id,
                "decision_timestamp": lv.decision_ts, "instrument_id": lv.request.instrument_id,
                "candidate_id": lv.candidate.candidate_id, "snapshot_id": lv.snapshot.snapshot_id,
                "feature_set_version": lv.snapshot.feature_set_version,
                "strategy_version_id": lv.candidate.strategy_version_id, "risk_decision_id": rep.risk_decision_id,
                "rationale": lv.candidate.rationale, "fill_timestamp": t, "fill_price": price, "quantity": qty,
                "side": lv.request.side.value, "fill_type": rep.fill.fill_type.value,
                "execution_assumption": "NEXT_BAR_OPEN", "cost_estimate": rep.charges, "portfolio_change": change,
                "adapter": f"{rep.adapter_id}/{rep.adapter_version}", "order_state_after": rep.state_after.value,
            }  # fmt: skip
            st.trades.append(row)
            st.fill_rows.append(row)
            lv.trace.update(outcome=rep.state_after.value, fill=row)

        for lv in list(live.values()):
            status = broker.get_order_status(session, lv.broker_order_id)
            self._sync_terminal(mgr, lv, status)
            if lv.decision_id:
                mrec = mgr.record(lv.request.idempotency_key)
                if status.state in (OrderState.REJECTED, OrderState.CANCELLED):
                    rj.broker_event(lv.decision_id, status.state.value, lv.broker_order_id, f"{lv.order_id}:{status.state.value}",
                                    status.last_response, t)  # fmt: skip
                if mrec is not None:
                    rj.transitions(lv.decision_id, mrec.order, lv.request.idempotency_key)
            if status.state is OrderState.REJECTED:
                self._on_broker_reject(lv, status, t, config, cfg_id, risk_version_id, st, live)
            elif status.state is OrderState.RECONCILIATION_REQUIRED:
                self._finalize(lv, status, t, cfg_id, risk_version_id, st)
                live.pop(lv.broker_order_id, None)
                rj.recon("order-blocked:" + lv.order_id, False, [f"order {lv.order_id}: broker response ambiguous"],
                         {"kind": "order_reconciliation_required", "order_id": lv.order_id}, [lv.decision_id], t)  # fmt: skip
                raise ResearchRunFailure(FailureCategory.RECONCILIATION_REQUIRED,
                                         f"order {lv.order_id} requires reconciliation: {status.last_response}",
                                         order_id=lv.order_id)  # fmt: skip
            elif status.state in (OrderState.FILLED, OrderState.CANCELLED):
                self._finalize(lv, status, t, cfg_id, risk_version_id, st)
                live.pop(lv.broker_order_id, None)

        ledger = broker.ledger_snapshot()
        pf_pos = {i: portfolio.quantity(i) for i in portfolio.held_instruments()}
        rec = reconcile(portfolio.cash, pf_pos, ledger["cash"], ledger["positions"])
        st.recon_rows.append({"timestamp": t, "ok": rec.ok, "mismatches": list(rec.mismatches),
                              "portfolio_cash": rec.portfolio_cash, "broker_cash": rec.broker_cash,
                              "positions": rec.portfolio_positions})  # fmt: skip
        if touched or not rec.ok:
            rj.recon("simple:" + t.isoformat(), rec.ok, list(rec.mismatches),
                     {"kind": "portfolio_vs_broker_ledger", "portfolio_cash": rec.portfolio_cash, "broker_cash": rec.broker_cash,
                      "portfolio_positions": rec.portfolio_positions}, list(touched), t)  # fmt: skip
        if not rec.ok:
            raise ResearchRunFailure(FailureCategory.RECONCILIATION_REQUIRED,
                                     "portfolio/broker ledgers disagree: " + "; ".join(rec.mismatches))  # fmt: skip
        # Slice 7: order/fill/position/cash reconciliation across lifecycle, internal books and broker
        pf_avg = {p_["instrument_id"]: Decimal(p_["avg_cost"]) for p_ in portfolio.positions_snapshot()}
        full = reconcile_execution(mgr, opening, LedgerView(portfolio.cash, pf_pos, pf_avg),
                                   LedgerView(ledger["cash"], ledger["positions"], ledger["avg_costs"]),
                                   broker.order_statuses(session), broker.get_fills(session))
        halt = mgr.record_reconciliation(full)
        st.recon_rows[-1].update(execution_reconciliation={"run_id": full.run_id, "outcome": full.outcome.value,
                                                           "mismatches": [str(m) for m in full.mismatches]})  # fmt: skip
        if touched or not full.consistent or mgr.halted:
            rj.recon("exec:" + t.isoformat(), bool(full.consistent) and not mgr.halted, [str(m) for m in full.mismatches],
                     {"kind": "execution_reconciliation", "outcome": full.outcome.value, "reconciliation_run_id": full.run_id,
                      "halted": mgr.halted, "halt_id": halt.halt_id if halt else None}, list(touched), t)  # fmt: skip
        if mgr.halted and full.consistent:
            raise ResearchRunFailure(FailureCategory.RECONCILIATION_REQUIRED,
                                     "execution halted: " + "; ".join(mgr.can_submit()[1]))  # fmt: skip
        if not full.consistent:
            raise ResearchRunFailure(FailureCategory.RECONCILIATION_REQUIRED,
                                     f"execution reconciliation {full.outcome.value} (halt {halt.halt_id if halt else None}): "
                                     + "; ".join(str(m) for m in full.mismatches))  # fmt: skip

    @staticmethod
    def _sync_terminal(mgr, lv, status: OrderStatus) -> None:  # noqa: ANN001
        """Feed broker-side terminal outcomes to the lifecycle manager as ordinary (idempotent) events."""
        rec = mgr.record(lv.request.idempotency_key)
        if rec is None or rec.order.state is status.state:
            return
        kind = {OrderState.REJECTED: EventKind.REJECTED, OrderState.CANCELLED: EventKind.CANCEL_CONFIRMED}.get(status.state)
        if kind is not None:
            res = mgr.apply_event(BrokerEvent(kind, status.broker_order_id, lv.request.idempotency_key,
                                              detail=status.last_response))
            if res.status not in (EventStatus.APPLIED, EventStatus.DUPLICATE_IGNORED):
                raise ResearchRunFailure(FailureCategory.RECONCILIATION_REQUIRED,
                                         f"{kind.value} for {lv.order_id} not applied: {res.status.value} {res.detail}")  # fmt: skip

    def _on_broker_reject(self, lv, status: OrderStatus, t, config, cfg_id, risk_version_id, st, live) -> None:  # noqa: ANN001
        lv.trace["outcome"] = "REJECTED_BY_BROKER"
        lv.trace["rejection_reason"] = status.last_response
        st.rejected += 1
        st.rejections.append({"decision_timestamp": lv.decision_ts, "instrument_id": lv.request.instrument_id,
                              "order_id": lv.order_id, "kind": "REJECTED_BY_BROKER",
                              "reason": status.last_response})  # fmt: skip
        self._finalize(lv, status, t, cfg_id, risk_version_id, st)
        live.pop(lv.broker_order_id, None)
        if config.order_rejection_policy is OrderRejectionPolicy.FAIL_RUN:
            raise ResearchRunFailure(FailureCategory.BROKER_REJECTED, status.last_response,
                                     order_id=lv.order_id, instrument_id=lv.request.instrument_id)  # fmt: skip

    # ------------------------------------------------------------- records
    def _finalize(self, lv: _Live, status: OrderStatus, t, cfg_id, risk_version_id, st) -> None:  # noqa: ANN001
        term = {
            OrderState.FILLED: TerminalState.FILLED,
            OrderState.PARTIALLY_FILLED: TerminalState.PARTIALLY_FILLED,
            OrderState.CANCELLED: TerminalState.CANCELLED,
            OrderState.REJECTED: TerminalState.REJECTED_BY_BROKER,
            OrderState.RECONCILIATION_REQUIRED: TerminalState.RECONCILIATION_REQUIRED,
        }.get(status.state, TerminalState.SUBMITTED)
        st.order_rows.append({
            "order_id": lv.order_id, "broker_order_id": lv.broker_order_id,
            "idempotency_key": lv.request.idempotency_key, "instrument_id": lv.request.instrument_id,
            "side": lv.request.side.value, "quantity": int(lv.request.quantity),
            "filled_quantity": status.filled_quantity, "final_state": status.state.value,
            "last_response": status.last_response, "risk_decision_id": lv.risk.risk_decision_id,
            "candidate_id": lv.candidate.candidate_id, "decision_timestamp": lv.decision_ts,
            "state_history": [{"from": h.from_state.value, "to": h.to_state.value, "at": h.at, "detail": h.detail}
                              for h in status.state_history],
        })  # fmt: skip
        snap = lv.snapshot
        fills = tuple(r.fill for r in lv.fills)
        cost_ids = hash_json_stable(jsonable([r.charges for r in lv.fills]))[:24] if lv.fills else None
        drec = DecisionRecord(
            instrument_id=lv.request.instrument_id, cycle_timestamp=lv.decision_ts, autonomy_level=_AUTONOMY,
            input_snapshot_id=snap.snapshot_id,
            data_sources=tuple(DataSourceRef(r.source, snap.data_snapshot_version or "UNKNOWN", r.timestamp)
                               for r in snap.source_refs),
            terminal_state=term, risk_rule_version_id=risk_version_id, config_version_id=cfg_id,
            decision_id="dec_" + hash_json_stable({"run": st.run_id, "order": lv.order_id})[:24],
            candidate_trade_id=lv.candidate.candidate_id, rationale=lv.candidate.rationale,
            strategy_version_id=lv.candidate.strategy_version_id, model_version_id=lv.candidate.model_version_id,
            cost_estimate_id=("cost_" + cost_ids) if cost_ids else None,
            risk_decision_id=lv.risk.risk_decision_id, order_request_id=lv.request.idempotency_key,
            order_id=lv.order_id, fills=fills,
            realized_pnl_delta=float(lv.pnl) if lv.fills else None, finalized_at=t,
        )  # fmt: skip
        st.decision_records.append(drec)
        if lv.decision_id and st.rj is not None:
            mrec = st.lifecycle.record(lv.request.idempotency_key) if st.lifecycle is not None else None
            if mrec is not None:
                st.rj.transitions(lv.decision_id, mrec.order, lv.request.idempotency_key)
            st.rj.finalize(lv.decision_id, drec, t, {"order_final_state": status.state.value,
                                                      "fill_ids": [r.fill.fill_id for r in lv.fills],
                                                      "itemised_charges": [r.charges for r in lv.fills]},
                           legacy_id=drec.decision_id)  # fmt: skip

    def _journal_invalid(self, st, vf, snapshots, t, run_id, cfg_id, risk_version_id, sv, universe_t, portfolio, marks) -> None:  # noqa: ANN001
        """Record an invalid-candidate cycle in the journal (best effort is NOT acceptable: a journal failure
        here replaces the failure with JOURNAL_FAILURE). Re-raising the original is the caller's job."""
        rj = st.rj
        if rj is None or vf.category is not FailureCategory.INVALID_CANDIDATE:
            return
        inst = vf.context.get("instrument_id")
        snap = next((s_ for s_ in snapshots if s_.instrument_id == inst), None)
        if snap is None:
            return  # no attributable instrument/snapshot: the run-level OPERATIONAL_FAILURE records it
        pf = portfolio_payload(portfolio, None, t, "pre_decision_marks_not_computed")
        did = rj.start(run_id, t, inst, None, snap, pf, sv, getattr(universe_t, "version", None))
        from observability.decision_log.events import EventType
        rj._e(EventType.CANDIDATE_REJECTED, {"reason": vf.message, "error_code": vf.category.value}, did=did, at=t)  # noqa: SLF001
        rj.finalize(did, rj.no_order_record(TerminalState.REJECTED_INVALID_CANDIDATE, t, inst, snap, None, risk_version_id, cfg_id),
                    t, {"reason": vf.message})  # fmt: skip

    def _veto_record(self, cand, snap, rd, t, cfg_id, run_id, risk_version_id) -> DecisionRecord:  # noqa: ANN001
        return DecisionRecord(
            instrument_id=cand.instrument_id, cycle_timestamp=t, autonomy_level=_AUTONOMY,
            input_snapshot_id=snap.snapshot_id,
            data_sources=tuple(DataSourceRef(r.source, snap.data_snapshot_version or "UNKNOWN", r.timestamp)
                               for r in snap.source_refs),
            terminal_state=TerminalState.REJECTED_AT_RISK, risk_rule_version_id=risk_version_id,
            config_version_id=cfg_id,
            decision_id="dec_" + hash_json_stable({"run": run_id, "veto": rd.risk_decision_id})[:24],
            candidate_trade_id=cand.candidate_id, rationale=cand.rationale,
            strategy_version_id=cand.strategy_version_id, model_version_id=cand.model_version_id,
            risk_decision_id=rd.risk_decision_id, finalized_at=t,
        )  # fmt: skip

    @staticmethod
    def _risk_row(t, cand, rd: RiskDecision) -> dict:  # noqa: ANN001
        return {
            "decision_timestamp": t, "instrument_id": cand.instrument_id, "candidate_id": cand.candidate_id,
            "risk_decision_id": rd.risk_decision_id, "verdict": rd.final_verdict.value,
            "approved_qty_ceiling": rd.approved_qty, "risk_rule_version_id": rd.risk_rule_version_id,
            "reasons": list(rd.reasons),
            "checks": [{"check_id": c.check_id, "passed": c.passed, "detail": c.detail} for c in rd.checks_evaluated],
        }  # fmt: skip

    @staticmethod
    def _sizing_row(t, cand, sd: SizingDecision) -> dict:  # noqa: ANN001
        return {
            "decision_timestamp": t, "instrument_id": cand.instrument_id, "candidate_id": sd.candidate_id,
            "risk_decision_id": sd.risk_decision_id, "outcome": sd.outcome.value, "reason": sd.reason,
            "side": sd.side.value if sd.side else None, "quantity": sd.quantity,
            "target_notional": sd.target_notional, "reference_price": sd.reference_price,
            "estimated_residual_cash_before_costs": sd.estimated_residual_cash,
            "idempotency_key": sd.order_request.idempotency_key if sd.order_request else None,
        }  # fmt: skip

    @staticmethod
    def _portfolio_state(portfolio: ResearchPortfolio, marks, t) -> PortfolioState:  # noqa: ANN001
        pos = []
        for p in portfolio.positions_snapshot():
            pos.append(Position(p["instrument_id"], float(p["quantity"]), float(Decimal(p["avg_cost"]))))
        return PortfolioState(as_of_timestamp=t, positions=tuple(pos), cash_balance=float(portfolio.cash),
                              source=PortfolioStateSource.SYSTEM_BELIEF)  # fmt: skip
