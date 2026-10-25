"""Deterministic Risk Engine (Slice 6, Stage 3 §7; RR-1..RR-9).

Independent hard authority: pure function of (CandidateTrade, RiskContext, RiskConfig).
No strategy, LLM, broker, network, clock or randomness. FAIL CLOSED: anything that
cannot be positively established as safe is a REJECT (a "veto"). Every check is always
evaluated and recorded (no short-circuit), so a veto is fully attributable.

`approved_qty` on an APPROVE is the risk layer's QUANTITY CEILING (headroom under
RR-1/RR-2, or the sellable holding) — a limit sizing may never exceed, not an order
quantity. The only executable quantity is produced by sizing (TR-3).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Callable

from domain.models.enums import Action, RiskVerdict
from domain.models.risk_decision import RiskCheckResult, RiskDecision
from domain.models.trade import CandidateTrade
from risk_execution.risk_engine.config import (
    CONFIG_SENTINEL_INVALID,
    KillSwitchState,
    RiskConfig,
)
from risk_execution.risk_engine.context import PROTECTED_TARGETS, RiskContext
from shared.versioning.content_hash import hash_json_stable

ZERO = Decimal(0)


@dataclass(frozen=True)
class _Exposure:
    rr1_issues: tuple[str, ...]
    rr2_issues: tuple[str, ...]
    ceiling: int
    rr1_ok_detail: str
    rr2_ok_detail: str
    rr1_evidence: tuple = ()
    rr2_evidence: tuple = ()


def _floor(x: Decimal) -> int:
    return int(x.to_integral_value(rounding="ROUND_FLOOR"))


class RiskEngine:
    def __init__(self, config: RiskConfig) -> None:
        self._config = config
        self._config_errors: tuple[str, ...]
        try:
            self._config_errors = tuple(config.validate())  # type: ignore[union-attr]
        except Exception as e:  # noqa: BLE001
            self._config_errors = (f"config could not be validated: {type(e).__name__}: {e}",)
        self._hash: str | None = None
        self.risk_rule_version_id: str = CONFIG_SENTINEL_INVALID
        if not self._config_errors:
            self._hash = config.rule_set_hash()
            self.risk_rule_version_id = config.risk_rule_version().version_id

    # ---------------------------------------------------------------- public
    @property
    def config_errors(self) -> tuple[str, ...]:
        return self._config_errors

    def drawdown_breached(self, equity: Decimal, peak: Decimal) -> bool:
        if self._config_errors or peak <= 0:
            return True  # cannot establish safety -> treat as breached
        return (peak - equity) / peak >= Decimal(self._config.max_drawdown_fraction)

    def evaluate(
        self, candidate: object, context: RiskContext, decision_id: str | None = None
    ) -> RiskDecision:
        """Never raises; always returns a RiskDecision with full check provenance."""
        cid = str(getattr(candidate, "candidate_id", "") or "") or "UNKNOWN_CANDIDATE"
        try:
            checks, ceiling = self._run_checks(candidate, context)
        except Exception as e:  # noqa: BLE001 - last-resort fail-closed
            checks = [RiskCheckResult("RR-FAILSAFE", False, f"engine error: {type(e).__name__}: {e}")]
            ceiling = 0
        rid = decision_id or "risk_" + hash_json_stable(
            [getattr(context, "research_run_id", None), cid,
             str(getattr(context, "evaluated_at", None))]
        )[:24]  # fmt: skip
        failed = [c for c in checks if not c.passed]
        if failed or ceiling < 1:
            reasons = tuple(f"{c.check_id}: {c.detail}" for c in failed) or (
                "RR-FAILSAFE: no positive quantity ceiling could be established",
            )
            if not failed:
                checks = [*checks, RiskCheckResult("RR-FAILSAFE", False, reasons[0].split(": ", 1)[1])]
            return RiskDecision(cid, tuple(checks), RiskVerdict.REJECT, self.risk_rule_version_id,
                                None, reasons, rid)  # fmt: skip
        return RiskDecision(cid, tuple(checks), RiskVerdict.APPROVE, self.risk_rule_version_id,
                            float(ceiling), (), rid)  # fmt: skip

    # --------------------------------------------------------------- checks
    # Slice 8: every check records the exact observed inputs and configured limits it used as `evidence`
    # (name, exact-string) pairs, captured at evaluation time. `detail` remains human prose.
    @staticmethod
    def _ev(**kv: object) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((k, "None" if v is None else str(v)) for k, v in kv.items()))

    def _run_checks(self, c: object, ctx: RiskContext) -> tuple[list[RiskCheckResult], int]:
        if isinstance(c, CandidateTrade) and c.action is Action.HOLD:
            return [RiskCheckResult("RR-NO-EXECUTION", False,
                                    "HOLD requests no execution; there is nothing to approve",
                                    self._ev(action="HOLD"))], 0  # fmt: skip
        out: list[RiskCheckResult] = []
        out.append(self._guard("RR-CONFIG", lambda: self._chk_config()))
        out.append(self._guard("RR-8", lambda: self._chk_kill(ctx)))
        out.append(self._guard("RR-9", lambda: self._chk_boundary(ctx)))
        out.append(self._guard("RR-7", lambda: self._chk_attribution(c, ctx)))
        out.append(self._guard("RR-4", lambda: self._chk_universe(c, ctx)))
        out.append(self._guard("RR-6", lambda: self._chk_scope(ctx)))
        out.append(self._guard("RR-3", lambda: self._chk_drawdown(c, ctx)))
        out.append(self._guard("RR-5", lambda: self._chk_rate(ctx)))
        exposure: _Exposure | None = None
        exposure_err: str | None = None
        try:
            if self._config_errors:
                raise ValueError("risk configuration invalid")
            exposure = self._analyze(c, ctx)
        except Exception as e:  # noqa: BLE001
            exposure_err = f"exposure could not be evaluated: {type(e).__name__}: {e}"
        if exposure is None:
            ev = self._ev(error_type=exposure_err.split(":")[1].strip() if exposure_err else "unknown")
            out.append(RiskCheckResult("RR-1", False, exposure_err or "exposure unavailable", ev, False))
            out.append(RiskCheckResult("RR-2", False, exposure_err or "exposure unavailable", ev, False))
            return out, 0
        out.append(self._res("RR-1", exposure.rr1_issues, exposure.rr1_ok_detail, exposure.rr1_evidence))
        out.append(self._res("RR-2", exposure.rr2_issues, exposure.rr2_ok_detail, exposure.rr2_evidence))
        return out, exposure.ceiling

    @staticmethod
    def _res(check_id: str, issues: tuple[str, ...], ok: str, evidence: tuple = ()) -> RiskCheckResult:
        return RiskCheckResult(check_id, not issues, "; ".join(issues) if issues else ok, evidence)

    def _guard(self, check_id: str, fn: Callable[[], RiskCheckResult]) -> RiskCheckResult:
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            return RiskCheckResult(check_id, False, f"could not be evaluated ({type(e).__name__}: {e})",
                                   self._ev(error_type=type(e).__name__), False)  # fmt: skip

    def _chk_config(self) -> RiskCheckResult:
        ev = self._ev(label=getattr(self._config, "label", None), config_error_count=len(self._config_errors),
                      risk_rule_version_id=self.risk_rule_version_id)  # fmt: skip
        if self._config_errors:
            return RiskCheckResult("RR-CONFIG", False, "invalid risk config: " + "; ".join(self._config_errors), ev)
        return RiskCheckResult("RR-CONFIG", True, f"risk config valid ({self._config.label})", ev)

    def _chk_kill(self, ctx: RiskContext) -> RiskCheckResult:
        ks = ctx.kill_switch
        ev = self._ev(kill_switch=getattr(ks, "value", ks), required="INACTIVE")
        if ks is KillSwitchState.INACTIVE:
            return RiskCheckResult("RR-8", True, "kill switch INACTIVE", ev)
        return RiskCheckResult("RR-8", False, f"kill switch is {ks!r}; no execution may be approved", ev)

    def _chk_boundary(self, ctx: RiskContext) -> RiskCheckResult:
        issues: list[str] = []
        hash_ok = not (self._config_errors or self._hash is None) and self._config.rule_set_hash() == self._hash
        if self._config_errors or self._hash is None:
            issues.append("risk configuration not verifiable")
        elif self._config.rule_set_hash() != self._hash:
            issues.append("risk configuration was altered after engine construction (hash mismatch)")
        if ctx.expected_risk_rule_version_id != self.risk_rule_version_id:
            issues.append(
                f"expected risk rule version {ctx.expected_risk_rule_version_id!r} does not match "
                f"engine version {self.risk_rule_version_id!r}"
            )
        for ch in ctx.requested_changes:
            if str(ch.target).lower() in PROTECTED_TARGETS:
                issues.append(f"attempt by {ch.requester!r} to alter protected item {ch.target!r}")
        ev = self._ev(config_hash_verified=hash_ok, engine_risk_rule_version_id=self.risk_rule_version_id,
                      expected_risk_rule_version_id=ctx.expected_risk_rule_version_id,
                      change_requests=len(ctx.requested_changes))  # fmt: skip
        return self._res("RR-9", tuple(issues), "safety boundary intact (config hash + version verified, no change requests)", ev)

    def _chk_attribution(self, c: object, ctx: RiskContext) -> RiskCheckResult:
        issues: list[str] = []
        if not isinstance(c, CandidateTrade):
            return RiskCheckResult("RR-7", False, "candidate is not a CandidateTrade", self._ev(candidate_type=type(c).__name__))
        if not str(c.strategy_version_id or "").strip():
            issues.append("missing strategy_version_id")
        if not str(c.input_snapshot_id or "").strip():
            issues.append("missing input_snapshot_id")
        if not str(c.rationale or "").strip():
            issues.append("missing rationale")
        if not (ctx.research_run_id or "").strip():
            issues.append("missing research_run_id")
        if not (ctx.config_version_id or "").strip():
            issues.append("missing config_version_id")
        if ctx.snapshot_ids is None or ctx.snapshot_ids.get(c.instrument_id) != c.input_snapshot_id:
            issues.append("input_snapshot_id does not match this cycle's snapshot for the instrument")
        if ctx.evaluated_at is None or c.timestamp != ctx.evaluated_at:
            issues.append("candidate timestamp does not match evaluation cycle")
        ev = self._ev(
            strategy_version_id=c.strategy_version_id, candidate_input_snapshot_id=c.input_snapshot_id,
            cycle_snapshot_id=(ctx.snapshot_ids or {}).get(c.instrument_id), candidate_timestamp=c.timestamp.isoformat(),
            evaluated_at=ctx.evaluated_at.isoformat() if ctx.evaluated_at else None, research_run_id=ctx.research_run_id,
            config_version_id=ctx.config_version_id, rationale_present=bool(str(c.rationale or "").strip()),
        )  # fmt: skip
        return self._res("RR-7", tuple(issues), "candidate attributable to strategy version, snapshot, run and config", ev)

    def _chk_universe(self, c: object, ctx: RiskContext) -> RiskCheckResult:
        if not isinstance(c, CandidateTrade):
            return RiskCheckResult("RR-4", False, "candidate is not a CandidateTrade", self._ev(candidate_type=type(c).__name__))
        u = ctx.permitted_instrument_ids
        base = dict(instrument_id=c.instrument_id, action=c.action.value, universe_size=len(u) if u else 0,
                    universe_version=ctx.universe_version,
                    allow_exit_of_removed_instruments=self._config.allow_exit_of_removed_instruments)  # fmt: skip
        if not u:
            return RiskCheckResult("RR-4", False, "permitted universe missing or empty", self._ev(**base, in_universe=False))
        if c.instrument_id in u:
            return RiskCheckResult("RR-4", True, f"{c.instrument_id} is in the permitted universe", self._ev(**base, in_universe=True))
        if c.action is Action.SELL and self._config.allow_exit_of_removed_instruments:
            held = ctx.portfolio is not None and ctx.portfolio.position_for(c.instrument_id) is not None
            if held:
                return RiskCheckResult("RR-4", True, f"exit of held instrument {c.instrument_id} removed from universe (allowed by config)",
                                       self._ev(**base, in_universe=False, held=True))  # fmt: skip
        return RiskCheckResult("RR-4", False, f"{c.instrument_id} is outside the permitted universe", self._ev(**base, in_universe=False))

    def _chk_scope(self, ctx: RiskContext) -> RiskCheckResult:
        ev = self._ev(account_scope=ctx.account_scope, permitted_account_scope=self._config.permitted_account_scope)
        if not ctx.account_scope:
            return RiskCheckResult("RR-6", False, "account scope missing", ev)
        if ctx.account_scope != self._config.permitted_account_scope:
            return RiskCheckResult("RR-6", False, f"account scope {ctx.account_scope!r} is not the permitted scope {self._config.permitted_account_scope!r}", ev)
        return RiskCheckResult("RR-6", True, f"account scope {ctx.account_scope!r} permitted", ev)

    def _chk_drawdown(self, c: object, ctx: RiskContext) -> RiskCheckResult:
        if not isinstance(c, CandidateTrade):
            return RiskCheckResult("RR-3", False, "candidate is not a CandidateTrade", self._ev(candidate_type=type(c).__name__))
        if c.action is not Action.BUY:
            return RiskCheckResult("RR-3", True, "drawdown halt applies to BUY only; not applicable", self._ev(action=c.action.value, applicable=False))
        eq, pk = ctx.equity, ctx.peak_equity
        base = dict(equity=eq, peak_equity=pk, max_drawdown_fraction=self._config.max_drawdown_fraction,
                    drawdown_halt_latched=ctx.drawdown_halt_latched, applicable=True)  # fmt: skip
        if eq is None or pk is None or not (pk > 0) or eq < 0:
            return RiskCheckResult("RR-3", False, "equity/peak equity unavailable; cannot establish drawdown", self._ev(**base), False)
        dd = (pk - eq) / pk
        ev = self._ev(**base, drawdown=dd)
        if ctx.drawdown_halt_latched:
            return RiskCheckResult("RR-3", False, f"drawdown halt is latched (current drawdown {dd:.4f})", ev)
        if dd >= Decimal(self._config.max_drawdown_fraction):
            return RiskCheckResult("RR-3", False, f"drawdown {dd:.4f} >= limit {self._config.max_drawdown_fraction}; new BUY vetoed", ev)
        return RiskCheckResult("RR-3", True, f"drawdown {dd:.4f} below limit {self._config.max_drawdown_fraction}", ev)

    def _chk_rate(self, ctx: RiskContext) -> RiskCheckResult:
        base = dict(window_seconds=self._config.order_rate_window_seconds, max_orders_per_window=self._config.max_orders_per_window)
        if ctx.recent_order_timestamps is None or ctx.evaluated_at is None:
            return RiskCheckResult("RR-5", False, "order history unavailable; cannot apply order-rate limit", self._ev(**base), False)
        lo = ctx.evaluated_at - timedelta(seconds=self._config.order_rate_window_seconds)
        n = sum(1 for t in ctx.recent_order_timestamps if lo < t <= ctx.evaluated_at)
        ev = self._ev(**base, orders_in_window=n)
        if n >= self._config.max_orders_per_window:
            return RiskCheckResult("RR-5", False, f"{n} orders in the last {self._config.order_rate_window_seconds}s >= limit {self._config.max_orders_per_window}", ev)
        return RiskCheckResult("RR-5", True, f"{n} orders in window < limit {self._config.max_orders_per_window}", ev)

    # ------------------------------------------------------------- exposure
    def _analyze(self, c: object, ctx: RiskContext) -> _Exposure:
        if not isinstance(c, CandidateTrade):
            raise ValueError("candidate is not a CandidateTrade")
        pf, eq, prices = ctx.portfolio, ctx.equity, ctx.reference_prices
        if pf is None or eq is None or prices is None:
            raise ValueError("portfolio/equity/reference prices missing")
        if not (isinstance(eq, Decimal) and eq.is_finite() and eq > 0):
            raise ValueError(f"equity must be a positive finite Decimal, got {eq!r}")

        def px(i: str) -> Decimal:
            p = prices.get(i)
            if not isinstance(p, Decimal) or not p.is_finite() or p <= 0:
                raise ValueError(f"no valid reference price for {i}")
            return p

        held = {p.instrument_id: Decimal(str(p.quantity)) for p in pf.positions}
        buy_q: dict[str, int] = {}
        sell_q: dict[str, int] = {}
        for pi in ctx.pending_intents:
            d = buy_q if pi.side is Action.BUY else sell_q
            d[pi.instrument_id] = d.get(pi.instrument_id, 0) + int(pi.quantity)
        insts = set(held) | set(buy_q) | set(sell_q) | {c.instrument_id}
        proj = {
            i: max(ZERO, held.get(i, ZERO) * px(i) + Decimal(buy_q.get(i, 0)) * px(i)
                   - Decimal(sell_q.get(i, 0)) * px(i))
            for i in insts
        }  # fmt: skip
        gross = sum(proj.values(), ZERO)
        cfg = self._config
        p = px(c.instrument_id)

        if c.action is Action.SELL:
            avail = int(held.get(c.instrument_id, ZERO)) - sell_q.get(c.instrument_id, 0)
            issues = () if avail >= 1 else (f"no sellable position in {c.instrument_id} (available {avail})",)
            ev = self._ev(action="SELL", instrument_id=c.instrument_id, held_quantity=held.get(c.instrument_id, ZERO),
                          pending_sell_quantity=sell_q.get(c.instrument_id, 0), sellable=avail, equity=eq)  # fmt: skip
            return _Exposure(issues, (), max(avail, 0),
                             f"SELL reduces exposure; sellable {avail}", "SELL does not add leverage", ev, ev)  # fmt: skip
        if c.action is not Action.BUY:
            raise ValueError(f"unsupported action {c.action!r}")

        h = c.size_hint
        if isinstance(h, bool) or not isinstance(h, (int, float)) or not math.isfinite(h) or not (0 <= h <= 1):
            raise ValueError(f"size_hint must be a finite number in [0,1], got {h!r}")
        hd = Decimal(str(h))
        target = hd * eq
        incr = max(ZERO, target - proj[c.instrument_id])
        max_pos = Decimal(cfg.max_position_fraction)
        max_gross = Decimal(cfg.max_gross_exposure_fraction)
        max_lev = Decimal(cfg.max_leverage)
        pos_head = _floor((max_pos * eq - proj[c.instrument_id]) / p)
        gross_head = _floor((max_gross * eq - gross) / p)
        lev_head = _floor((max_lev * eq - gross) / p)
        rr1: list[str] = []
        rr2: list[str] = []
        if hd > max_pos:
            rr1.append(f"size_hint {hd} implies target weight above per-position limit {max_pos}")
        if gross + incr > max_gross * eq:
            rr1.append(f"projected gross {gross + incr:.2f} exceeds {max_gross} x equity {eq:.2f}")
        if pos_head < 1:
            rr1.append("no per-position headroom for one share")
        if gross_head < 1:
            rr1.append("no gross-exposure headroom for one share")
        if gross + incr > max_lev * eq:
            rr2.append(f"projected leverage {(gross + incr) / eq:.4f} exceeds limit {max_lev}")
        if lev_head < 1:
            rr2.append("no leverage headroom for one share")
        ceiling = max(min(pos_head, gross_head, lev_head), 0)
        common = dict(action="BUY", instrument_id=c.instrument_id, equity=eq, gross_exposure=gross,
                      reference_price=p, size_hint=hd, target_notional=target, incremental_notional=incr)  # fmt: skip
        ev1 = self._ev(**common, max_position_fraction=max_pos, max_gross_exposure_fraction=max_gross,
                       position_headroom_shares=pos_head, gross_headroom_shares=gross_head)  # fmt: skip
        ev2 = self._ev(**common, max_leverage=max_lev, leverage_headroom_shares=lev_head)
        return _Exposure(tuple(rr1), tuple(rr2), ceiling,
                         f"within exposure limits; ceiling {ceiling} shares",
                         f"leverage within limit {max_lev}", ev1, ev2)  # fmt: skip
