"""The research harness runner (Slice 5).

Decision-cycle sequence for each decision timestamp t (docs/research-harness.md):

  0. Settle pending orders from earlier cycles at the OPEN of their instrument's bar at t
     (NEXT_BAR_OPEN); apply CostEstimate; update portfolio.
  1. Load observations available at t  (replay.visible(t): timestamp <= t ONLY)
  2. Validate temporal availability    (contamination guards)
  3. Build FeatureSnapshots as of t    (data.features.context_builder)
  4. Invoke the strategy               (snapshots, universe in force at t, previous universe)
  5. Receive + validate CandidateTrades
  6. Mark the portfolio to market at the close of t
  7. Translate candidates into pending simulated orders (sized from equity at t)
  8. Record decision traces, DecisionRecords (for fills), equity-curve point

Steps 1-5 never touch any bar later than t; fills consume only the bar AT the later cycle.
Orders still pending when the window ends are recorded as UNEXECUTED_END_OF_WINDOW.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from data.features.context_builder import (
    build_feature_snapshots,
    compute_market_data_snapshot_version,
)
from data.features.universe import PermittedUniverse
from domain.models.decision_record import DataSourceRef, DecisionRecord
from domain.models.enums import Action, FillType, TerminalState
from domain.models.feature_snapshot import FeatureSnapshot
from domain.models.market_data import MarketData
from domain.models.order_request import Fill
from domain.models.research_artifacts import EvaluationRun, Experiment
from domain.models.trade import CandidateTrade
from research.contamination import guards
from research.harness.config import (
    HARNESS_VERSION,
    EvaluationPeriod,
    OrderRejectionPolicy,
    ResearchConfig,
    comparison_fingerprint,
    config_payload,
    experiment_id_for,
    experiment_payload,
    resolved_buffer,
    resolved_capital,
    run_id_for,
    validate_config,
    window_bounds,
)
from research.harness.execution import PendingOrder, research_order_id, translate_candidate
from research.harness.failures import (
    FailureCategory,
    ResearchFailureRecord,
    ResearchRunFailure,
    RunStatus,
)
from research.harness.jsonio import jsonable
from research.harness.metrics import compute_metrics
from research.harness.portfolio import ResearchPortfolio
from research.harness.replay import HistoricalReplay
from research.harness.result import ResearchRunResult
from shared.costs import (
    CostInputs,
    CostModel,
    ScheduleRegistry,
    TradeType,
    TransactionSide,
    default_registry,
)
from shared.time.clock import utc_now
from shared.versioning.content_hash import hash_json_stable

NOT_APPLICABLE_RISK = "NOT_APPLICABLE_RESEARCH_HARNESS_NO_RISK_ENGINE"
_RESEARCH_AUTONOMY_LEVEL = 0  # research replay has no autonomy; Level 0 = advisory/no authority


class UniverseTimeline:
    """Explicit, sorted universe schedule. `at(t)` never returns a future universe."""

    def __init__(self, universes: list[PermittedUniverse]) -> None:
        if not universes:
            raise ResearchRunFailure(
                FailureCategory.INVALID_CONFIGURATION, "universe schedule must not be empty"
            )
        for u in universes:
            if not isinstance(u, PermittedUniverse):
                raise ResearchRunFailure(
                    FailureCategory.INVALID_CONFIGURATION,
                    "universe schedule entries must be PermittedUniverse instances",
                )
        ordered = sorted(universes, key=lambda u: u.effective_from)
        stamps = [u.effective_from for u in ordered]
        if len(set(stamps)) != len(stamps):
            raise ResearchRunFailure(
                FailureCategory.INVALID_CONFIGURATION,
                "two universes share the same effective_from; membership would be ambiguous",
            )
        self._ordered = ordered

    def at(self, t: datetime) -> PermittedUniverse | None:
        current = None
        for u in self._ordered:
            if u.effective_from <= t:
                current = u
            else:
                break
        return current

    def all_instrument_ids(self) -> set[str]:
        return {i for u in self._ordered for i in u.instrument_ids}

    def schedule(self) -> list[tuple[str, str]]:
        return [(u.version, u.effective_from.isoformat()) for u in self._ordered]


def _safe_universe_schedule(universes: object) -> list[tuple[str, str]]:
    try:
        return UniverseTimeline(list(universes)).schedule()  # type: ignore[arg-type]
    except Exception:
        return []


def _dec(x: float | int) -> Decimal:
    return Decimal(str(x))


class ResearchHarness:
    """Runs one deterministic research experiment and returns a `ResearchRunResult`.

    The harness never raises for anticipated research failures; it returns a FAILED
    result carrying a `ResearchFailureRecord` (spec §24). It holds no broker, no
    credentials and no governance handle.
    """

    def __init__(self, cost_registry: ScheduleRegistry | None = None) -> None:
        self._registry = cost_registry if cost_registry is not None else default_registry()
        self._cost_model = CostModel(self._registry)

    # ------------------------------------------------------------------ public
    def run(
        self,
        config: ResearchConfig,
        strategy: object,
        market_data: list[MarketData],
        universe_schedule: list[PermittedUniverse],
        baseline_strategy_version_ids: tuple[str, ...] | None = None,
        created_at: datetime | None = None,
    ) -> ResearchRunResult:
        strategy_version_id = str(getattr(strategy, "strategy_version_id", "UNKNOWN_STRATEGY"))
        baselines = tuple(baseline_strategy_version_ids or (strategy_version_id,))
        try:
            data_version = compute_market_data_snapshot_version(list(market_data))
        except Exception:
            data_version = "UNAVAILABLE"
        uni_sched = _safe_universe_schedule(universe_schedule)
        payload = experiment_payload(
            config,
            strategy_version_id=strategy_version_id,
            baseline_strategy_version_ids=baselines,
            data_snapshot_version=data_version,
            universe_schedule=uni_sched,
        )
        experiment_id = experiment_id_for(payload)
        run_id = run_id_for(experiment_id)
        created = created_at or utc_now()

        state = _RunState()
        try:
            self._execute(config, strategy, market_data, universe_schedule, run_id, state)
            status, failure = RunStatus.COMPLETED, None
        except ResearchRunFailure as f:
            status, failure = RunStatus.FAILED, self._failure_record(f, state)
        except Exception as e:  # noqa: BLE001 - must never lose research context
            status = RunStatus.FAILED
            failure = self._failure_record(
                ResearchRunFailure(
                    FailureCategory.UNEXPECTED_ERROR,
                    f"{type(e).__name__}: {e}",
                    exception_type=type(e).__name__,
                ),
                state,
            )

        return self._assemble(
            config, payload, experiment_id, run_id, strategy_version_id, baselines, data_version,
            uni_sched, status, failure, state, created,
        )  # fmt: skip

    # ---------------------------------------------------------------- internals
    def _failure_record(self, f: ResearchRunFailure, state: _RunState) -> ResearchFailureRecord:
        return ResearchFailureRecord(
            category=f.category,
            message=f.message,
            failed_at_decision=state.current_decision_ts.isoformat()
            if state.current_decision_ts
            else None,
            context=_jsonsafe_ctx(f.context),
            contamination_detail=f.message if f.category is FailureCategory.CONTAMINATION else None,
        )

    def _execute(
        self,
        config: ResearchConfig,
        strategy: object,
        market_data: list[MarketData],
        universes: list[PermittedUniverse],
        run_id: str,
        st: _RunState,
    ) -> None:
        # ---- configuration -------------------------------------------------
        errors = validate_config(config, set(self._registry._schedules))
        if errors:
            raise ResearchRunFailure(
                FailureCategory.INVALID_CONFIGURATION, "; ".join(errors), errors=errors
            )
        capital = resolved_capital(config)
        buffer = resolved_buffer(config)
        schedule = self._registry.get(config.cost_schedule_version)
        oos = config.evaluation_period is EvaluationPeriod.OUT_OF_SAMPLE
        w_start, w_end = window_bounds(config)
        st.window = (w_start, w_end)
        st.run_id = run_id

        if not callable(getattr(strategy, "generate_candidate_trades", None)):
            raise ResearchRunFailure(
                FailureCategory.INVALID_CONFIGURATION,
                "strategy must implement generate_candidate_trades(...)",
            )
        strategy_version_id = str(getattr(strategy, "strategy_version_id", ""))
        if not strategy_version_id:
            raise ResearchRunFailure(
                FailureCategory.INVALID_CONFIGURATION, "strategy has no strategy_version_id"
            )

        # ---- static contamination checks (fail the run, never continue) ----
        report: dict = {"checks_passed": []}
        st.contamination_report = report
        guards.check_split_separation(config.split)
        report["checks_passed"].append("split_strictly_separated")
        report.update(
            guards.check_strategy_configuration_cutoff(
                config.split, oos, config.strategy_configured_through
            )
        )
        report["checks_passed"].append("strategy_configuration_cutoff")
        report.update(
            guards.check_cost_schedule_not_from_future(
                schedule.effective_date,
                w_start,
                config.acknowledge_future_cost_schedule,
                schedule.version_id,
            )
        )
        report["checks_passed"].append("cost_schedule_not_from_future")

        # ---- data & universe ----------------------------------------------
        timeline = UniverseTimeline(list(universes))
        replay = HistoricalReplay(market_data)
        replay.require_instruments(timeline.all_instrument_ids())
        cycles = replay.decision_timestamps(w_start, w_end)
        if not cycles:
            raise ResearchRunFailure(
                FailureCategory.MISSING_DATA,
                f"no observations inside evaluation window {w_start.isoformat()}.."
                f"{w_end.isoformat()}",
            )

        portfolio = ResearchPortfolio(capital)
        st.portfolio = portfolio
        staleness = timedelta(days=config.max_staleness_days)
        prev_universe: PermittedUniverse | None = None
        pending: list[PendingOrder] = []
        seq = 0
        last_marks: dict[str, Decimal] = {}

        for t in cycles:
            st.current_decision_ts = t
            st.cycles += 1

            # 0. settle pending orders at the open of the bar at t
            self._settle(pending, t, replay, portfolio, config, strategy_version_id, st)

            # 1-2. observations available at t, temporally validated
            visible = replay.visible(t)
            guards.check_observations_not_from_future(visible, t, w_end)
            universe_t = timeline.at(t)
            if universe_t is None:
                raise ResearchRunFailure(
                    FailureCategory.MISSING_DATA,
                    f"no universe is in force at {t.isoformat()} (earliest universe is later)",
                )
            guards.check_universe_not_from_future(universe_t, t)

            # 3. snapshots (universe + any instrument just removed, so exits are attributable)
            added, removed = universe_t.diff(prev_universe)
            targets = sorted(set(universe_t.instrument_ids) | set(removed))
            snap_version = compute_market_data_snapshot_version(visible)
            snapshots = build_feature_snapshots(
                visible,
                universe_t,
                t,
                market_data_snapshot_version=snap_version,
                feature_set_id=config.feature_set_id,
                staleness_threshold=staleness,
                instrument_ids=targets,
            )
            guards.check_snapshots_not_from_future(snapshots, t)
            st.feature_set_versions.add(config.feature_set_id)

            # 4-5. strategy + candidate validation
            candidates = self._invoke(strategy, snapshots, universe_t, prev_universe)
            self._validate_candidates(candidates, snapshots, universe_t, t, strategy_version_id)

            # 6. mark to market at close of t
            marks = self._marks(portfolio, replay, t, config.carry_forward_marks, st)
            last_marks = marks
            equity = portfolio.equity(marks)

            # 7-8. translate candidates into pending orders + record traces
            by_inst = {s.instrument_id: s for s in snapshots}
            pending_instruments = {p.instrument_id for p in pending}
            for cand in sorted(candidates, key=lambda c: (c.action is not Action.SELL, c.instrument_id)):
                snap = by_inst[cand.instrument_id]
                trace = self._new_trace(cand, snap, t, equity)
                st.decisions.append(trace)
                if cand.action is not Action.HOLD and cand.instrument_id in pending_instruments:
                    self._reject(
                        trace, "REJECTED_PENDING_ORDER_EXISTS",
                        "an earlier order for this instrument is still unfilled", config, st,
                    )  # fmt: skip
                    continue
                tr = translate_candidate(
                    cand, snap, portfolio.quantity(cand.instrument_id), equity, buffer
                )
                trace["execution_translation"] = {"outcome": tr.outcome, "reason": tr.reason}
                if tr.outcome == "ORDER_CREATED":
                    seq += 1
                    oid = research_order_id(run_id, cand.candidate_id, seq)
                    assert tr.side is not None
                    pending.append(
                        PendingOrder(seq, oid, cand.instrument_id, tr.side, tr.quantity, t, cand, snap, trace)
                    )  # fmt: skip
                    pending_instruments.add(cand.instrument_id)
                    trace.update(
                        outcome="PENDING", order_id=oid, target_quantity=tr.quantity, side=tr.side.value
                    )
                elif tr.outcome == "REJECTED_NO_REFERENCE_PRICE":
                    self._reject(trace, tr.outcome, tr.reason, config, st)
                else:
                    trace["outcome"] = tr.outcome  # HOLD | NO_TRADE

            st.equity_curve.append(
                {
                    "timestamp": t,
                    "cash": portfolio.cash,
                    "market_value": portfolio.market_value(marks),
                    "equity": equity,
                    "cumulative_costs": portfolio.cumulative_costs,
                    "positions": portfolio.positions_snapshot(),
                    "carried_marks": sorted(st.carried_this_cycle),
                }
            )
            st.carried_this_cycle = set()
            prev_universe = universe_t

        # orders never filled inside the window
        for p in pending:
            p.decision_trace["outcome"] = "UNEXECUTED_END_OF_WINDOW"
            st.rejections.append(
                {
                    "decision_timestamp": p.decision_ts,
                    "instrument_id": p.instrument_id,
                    "order_id": p.order_id,
                    "kind": "UNEXECUTED_END_OF_WINDOW",
                    "reason": "no subsequent observation inside the evaluation window to fill at",
                }
            )
            st.unexecuted += 1
        st.current_decision_ts = None
        st.metrics = compute_metrics(
            portfolio,
            last_marks,
            rejected_orders=st.rejected,
            unexecuted_orders=st.unexecuted,
            decision_cycles=st.cycles,
        )
        report["checks_passed"].extend(
            ["observations_not_from_future", "snapshots_not_from_future", "universe_not_from_future"]
        )

    def _invoke(self, strategy, snapshots, universe, prev_universe) -> list[CandidateTrade]:
        try:
            out = strategy.generate_candidate_trades(list(snapshots), universe, prev_universe)
        except ResearchRunFailure:
            raise
        except Exception as e:  # noqa: BLE001
            raise ResearchRunFailure(
                FailureCategory.STRATEGY_ERROR,
                f"strategy raised {type(e).__name__}: {e}",
                exception_type=type(e).__name__,
            ) from e
        if not isinstance(out, list):
            raise ResearchRunFailure(
                FailureCategory.INVALID_CANDIDATE,
                f"strategy must return a list of CandidateTrade, got {type(out).__name__}",
            )
        return out

    def _validate_candidates(self, candidates, snapshots, universe, t, strategy_version_id) -> None:
        by_inst = {s.instrument_id: s for s in snapshots}
        seen: set[str] = set()
        for c in candidates:
            if not isinstance(c, CandidateTrade):
                raise ResearchRunFailure(
                    FailureCategory.INVALID_CANDIDATE,
                    f"strategy returned a non-CandidateTrade item: {type(c).__name__}",
                )
            if c.instrument_id not in by_inst:
                raise ResearchRunFailure(
                    FailureCategory.INVALID_CANDIDATE,
                    f"candidate for {c.instrument_id!r} has no snapshot in this cycle",
                    instrument_id=c.instrument_id,
                )
            if c.instrument_id in seen:
                raise ResearchRunFailure(
                    FailureCategory.INVALID_CANDIDATE,
                    f"duplicate candidates for {c.instrument_id!r} in one cycle",
                    instrument_id=c.instrument_id,
                )
            seen.add(c.instrument_id)
            if c.timestamp != t:
                raise ResearchRunFailure(
                    FailureCategory.INVALID_CANDIDATE,
                    f"candidate timestamp {c.timestamp.isoformat()} != decision time {t.isoformat()}",
                )
            if c.input_snapshot_id != by_inst[c.instrument_id].snapshot_id:
                raise ResearchRunFailure(
                    FailureCategory.INVALID_CANDIDATE,
                    f"candidate for {c.instrument_id!r} cites a snapshot it was not given",
                )
            if c.strategy_version_id != strategy_version_id:
                raise ResearchRunFailure(
                    FailureCategory.INVALID_CANDIDATE,
                    f"candidate strategy_version_id {c.strategy_version_id!r} != "
                    f"{strategy_version_id!r}",
                )
            if c.action is Action.BUY and not universe.contains(c.instrument_id):
                raise ResearchRunFailure(
                    FailureCategory.INVALID_CANDIDATE,
                    f"BUY for {c.instrument_id!r}, which is not in the universe in force",
                    instrument_id=c.instrument_id,
                )

    def _marks(self, portfolio, replay, t, carry, st) -> dict[str, Decimal]:
        marks: dict[str, Decimal] = {}
        for inst in portfolio.held_instruments():
            bar = replay.bar_at(inst, t)
            if bar is not None:
                marks[inst] = _dec(bar.close)
            elif carry:
                prior = replay.last_close_on_or_before(inst, t)
                if prior is None:  # pragma: no cover - a held instrument always has a prior bar
                    raise ResearchRunFailure(FailureCategory.MISSING_DATA, f"no mark for {inst}")
                marks[inst] = _dec(prior.close)
                st.carried_this_cycle.add(inst)
            else:
                raise ResearchRunFailure(
                    FailureCategory.MISSING_DATA,
                    f"no observation for held instrument {inst!r} at {t.isoformat()}; "
                    f"forward-filling is disabled (carry_forward_marks=False)",
                    instrument_id=inst,
                )
        return marks

    def _new_trace(self, cand: CandidateTrade, snap: FeatureSnapshot, t, equity) -> dict:
        return {
            "decision_timestamp": t,
            "instrument_id": cand.instrument_id,
            "candidate_id": cand.candidate_id,
            "action": cand.action.value,
            "size_hint": cand.size_hint,
            "confidence": cand.confidence,
            "rationale": cand.rationale,
            "snapshot_id": snap.snapshot_id,
            "feature_set_version": snap.feature_set_version,
            "snapshot_data_version": snap.data_snapshot_version,
            "universe_version": snap.universe_version,
            "reference_price": snap.reference_price,
            "snapshot_complete": snap.is_complete,
            "strategy_version_id": cand.strategy_version_id,
            "equity_at_decision": equity,
            "execution_assumption": "NEXT_BAR_OPEN",
            "outcome": "UNRESOLVED",
        }

    def _reject(self, trace, kind, reason, config, st) -> None:
        trace["outcome"] = kind
        trace["rejection_reason"] = reason
        st.rejected += 1
        st.rejections.append(
            {
                "decision_timestamp": trace["decision_timestamp"],
                "instrument_id": trace["instrument_id"],
                "order_id": trace.get("order_id"),
                "kind": kind,
                "reason": reason,
            }
        )
        if config.order_rejection_policy is OrderRejectionPolicy.FAIL_RUN:
            category = {
                "REJECTED_INSUFFICIENT_CASH": FailureCategory.INSUFFICIENT_CASH,
                "REJECTED_INSUFFICIENT_POSITION": FailureCategory.INSUFFICIENT_POSITION,
                "REJECTED_NO_REFERENCE_PRICE": FailureCategory.MISSING_EXECUTION_PRICE,
            }.get(kind, FailureCategory.INVALID_CANDIDATE)
            raise ResearchRunFailure(
                category, reason, rejection_kind=kind, instrument_id=trace["instrument_id"]
            )

    def _settle(self, pending, t, replay, portfolio, config, strategy_version_id, st) -> None:
        ready = [p for p in pending if p.decision_ts < t and replay.bar_at(p.instrument_id, t)]
        ready.sort(key=lambda p: (p.side is not Action.SELL, p.seq))
        for p in ready:
            pending.remove(p)
            bar = replay.bar_at(p.instrument_id, t)
            assert bar is not None
            price = _dec(bar.open)
            side = TransactionSide.BUY if p.side is Action.BUY else TransactionSide.SELL
            estimate = self._cost_model.estimate(
                CostInputs(side, TradeType.DELIVERY, p.quantity, price, config.cost_schedule_version)
            )
            try:
                if p.side is Action.BUY:
                    change = portfolio.buy(p.instrument_id, p.quantity, price, estimate.total_cost)
                else:
                    change = portfolio.sell(p.instrument_id, p.quantity, price, estimate.total_cost)
            except ResearchRunFailure as f:
                kind = {
                    FailureCategory.INSUFFICIENT_CASH: "REJECTED_INSUFFICIENT_CASH",
                    FailureCategory.INSUFFICIENT_POSITION: "REJECTED_INSUFFICIENT_POSITION",
                }.get(f.category)
                if kind is None:
                    raise
                self._reject(p.decision_trace, kind, f.message, config, st)
                continue
            fill_info = {
                "fill_timestamp": t,
                "fill_price": price,
                "quantity": p.quantity,
                "side": p.side.value,
                "execution_assumption": "NEXT_BAR_OPEN",
                "cost_estimate": estimate,
                "portfolio_change": change,
            }
            p.decision_trace.update(outcome="FILLED", fill=fill_info)
            st.trades.append(
                {
                    "order_id": p.order_id,
                    "decision_timestamp": p.decision_ts,
                    "instrument_id": p.instrument_id,
                    "candidate_id": p.candidate.candidate_id,
                    "snapshot_id": p.snapshot.snapshot_id,
                    "feature_set_version": p.snapshot.feature_set_version,
                    "strategy_version_id": strategy_version_id,
                    "rationale": p.candidate.rationale,
                    **fill_info,
                }
            )
            st.decision_records.append(self._decision_record(p, t, price, estimate, change, config, st))

    def _decision_record(self, p: PendingOrder, fill_ts, price, estimate, change, config, st):
        cand, snap = p.candidate, p.snapshot
        cfg_id = "cfg_" + hash_json_stable(config_payload(config))[:24]
        fill = Fill(
            order_id=p.order_id,
            quantity=float(p.quantity),
            price=float(price),
            timestamp=fill_ts,
            fill_type=FillType.FULL,
            fill_id="fill_" + hash_json_stable({"o": p.order_id, "t": fill_ts.isoformat()})[:24],
        )
        return DecisionRecord(
            instrument_id=p.instrument_id,
            cycle_timestamp=p.decision_ts,
            autonomy_level=_RESEARCH_AUTONOMY_LEVEL,
            input_snapshot_id=snap.snapshot_id,
            data_sources=tuple(
                DataSourceRef(r.source, snap.data_snapshot_version or "UNKNOWN", r.timestamp)
                for r in snap.source_refs
            ),
            terminal_state=TerminalState.FILLED,
            risk_rule_version_id=NOT_APPLICABLE_RISK,
            config_version_id=cfg_id,
            decision_id="dec_" + hash_json_stable({"run": st.run_id, "order": p.order_id})[:24],
            candidate_trade_id=cand.candidate_id,
            rationale=cand.rationale,
            strategy_version_id=cand.strategy_version_id,
            model_version_id=cand.model_version_id,
            cost_estimate_id="cost_" + hash_json_stable(jsonable(estimate))[:24],
            order_request_id=p.order_id,
            order_id=p.order_id,
            fills=(fill,),
            realized_pnl_delta=float(change.realized_pnl_gross),
            finalized_at=fill_ts,  # simulated time, keeps output deterministic
        )

    def _assemble(
        self, config, payload, experiment_id, run_id, strategy_version_id, baselines,
        data_version, uni_sched, status, failure, st, created,
    ) -> ResearchRunResult:  # fmt: skip
        experiment = evaluation_run = None
        try:
            experiment = Experiment(
                hypothesis=config.hypothesis,
                candidate_strategy_version=strategy_version_id,
                baseline_strategy_versions=baselines,
                evaluation_window=config.split,
                pre_registered_criteria=config.pre_registered_criteria,
                experiment_id=experiment_id,
                created_at=created,
            )
        except Exception:  # noqa: BLE001 - invalid configs may not satisfy Experiment's checks
            experiment = None
        contamination_failed = failure is not None and failure.category is FailureCategory.CONTAMINATION
        if experiment is not None and (status is RunStatus.COMPLETED or contamination_failed):
            try:
                check = (
                    guards.failed_result(failure.message)  # type: ignore[union-attr]
                    if contamination_failed
                    else guards.passed_result(
                        "all Slice 5 basic contamination guards passed",
                        checks=",".join(st.contamination_report.get("checks_passed", [])),
                    )
                )
                evaluation_run = EvaluationRun(
                    experiment_id=experiment_id,
                    data_version=data_version,
                    split=config.split,
                    contamination_check=check,
                    pbo_cscv_correction_applied=False,  # out of scope for Slice 5
                    regime_segmented_results={},  # out of scope for Slice 5
                    passed_pre_registered_criteria=False,  # NOT ASSESSED (see criteria_assessment)
                    run_id=run_id,
                )
            except Exception:  # noqa: BLE001
                evaluation_run = None

        w = st.window
        try:
            cap = str(resolved_capital(config))
        except Exception:  # noqa: BLE001
            cap = str(config.initial_capital)
        return ResearchRunResult(
            run_id=run_id,
            experiment_id=experiment_id,
            status=status,
            strategy_version_id=strategy_version_id,
            baseline_strategy_version_ids=tuple(baselines),
            feature_set_version=str(config.feature_set_id),
            cost_schedule_version=str(config.cost_schedule_version),
            data_snapshot_version=data_version,
            universe_schedule=tuple(uni_sched),
            config=payload["config"],
            comparison_fingerprint=comparison_fingerprint(payload),
            harness_version=HARNESS_VERSION,
            window_start=w[0].isoformat() if w else None,
            window_end=w[1].isoformat() if w else None,
            initial_capital=cap,
            metrics=st.metrics if status is RunStatus.COMPLETED else None,
            contamination_report=st.contamination_report,
            decisions=tuple(st.decisions),
            trades=tuple(st.trades),
            rejections=tuple(st.rejections),
            equity_curve=tuple(st.equity_curve),
            final_positions=tuple(st.portfolio.positions_snapshot()) if st.portfolio else (),
            decision_records=tuple(st.decision_records),
            failure=failure,
            experiment=experiment,
            evaluation_run=evaluation_run,
            created_at=created,
        )


def _jsonsafe_ctx(ctx: dict) -> dict:
    return jsonable(ctx)  # type: ignore[return-value]


class _RunState:
    def __init__(self) -> None:
        self.run_id = ""
        self.window: tuple[datetime, datetime] | None = None
        self.current_decision_ts: datetime | None = None
        self.contamination_report: dict = {}
        self.portfolio: ResearchPortfolio | None = None
        self.decisions: list[dict] = []
        self.trades: list[dict] = []
        self.rejections: list[dict] = []
        self.equity_curve: list[dict] = []
        self.decision_records: list[DecisionRecord] = []
        self.feature_set_versions: set[str] = set()
        self.carried_this_cycle: set[str] = set()
        self.metrics: dict | None = None
        self.cycles = 0
        self.rejected = 0
        self.unexecuted = 0
