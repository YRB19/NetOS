"""Slice 6 — Risk Engine (RR-1..RR-9, fail-closed, versioning). SYNTHETIC, example limits only."""

from __future__ import annotations

import dataclasses
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from domain.models.enums import Action, PortfolioStateSource, RiskVerdict
from domain.models.portfolio import PortfolioState, Position
from domain.models.trade import CandidateTrade
from risk_execution.risk_engine import (
    ChangeRequest,
    KillSwitchState,
    PendingIntent,
    RiskContext,
    RiskEngine,
)
from tests.unit._pipeline_helpers import SCOPE, risk_config

T = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)
A, B = "INE001X00001", "INE002X00002"


def cand(inst=A, action=Action.BUY, hint=0.3, **kw) -> CandidateTrade:
    args = dict(candidate_id=str(UUID(int=7)), instrument_id=inst, timestamp=T, action=action,
                size_hint=hint, confidence=0.9, uncertainty_band=None, rationale="because",
                input_snapshot_id="snap_1", strategy_version_id="strat@1", model_version_id=None)  # fmt: skip
    args.update(kw)
    return CandidateTrade(**args)


def ctx(engine: RiskEngine, **over) -> RiskContext:
    pf = PortfolioState(as_of_timestamp=T, positions=(), cash_balance=1_000_000.0,
                        source=PortfolioStateSource.SYSTEM_BELIEF)  # fmt: skip
    args = dict(
        evaluated_at=T, portfolio=pf, equity=Decimal("1000000"), peak_equity=Decimal("1000000"),
        reference_prices={A: Decimal("100"), B: Decimal("200")}, permitted_instrument_ids=frozenset({A, B}),
        account_scope=SCOPE, kill_switch=KillSwitchState.INACTIVE, recent_order_timestamps=(),
        snapshot_ids={A: "snap_1", B: "snap_2"}, research_run_id="run_1", config_version_id="cfg_1",
        expected_risk_rule_version_id=engine.risk_rule_version_id,
    )  # fmt: skip
    args.update(over)
    return RiskContext(**args)


def failed_ids(d) -> set[str]:
    return {c.check_id for c in d.checks_evaluated if not c.passed}


class RiskEngineTests(unittest.TestCase):
    def setUp(self):
        self.e = RiskEngine(risk_config())

    def test_clean_candidate_approved_with_quantity_ceiling_and_full_provenance(self):
        d = self.e.evaluate(cand(), ctx(self.e))
        self.assertIs(d.final_verdict, RiskVerdict.APPROVE)
        self.assertEqual(d.risk_rule_version_id, self.e.risk_rule_version_id)
        self.assertEqual(d.candidate_trade_id, cand().candidate_id)
        self.assertEqual({c.check_id for c in d.checks_evaluated},
                         {"RR-CONFIG", "RR-1", "RR-2", "RR-3", "RR-4", "RR-5", "RR-6", "RR-7", "RR-8", "RR-9"})
        self.assertTrue(all(c.passed for c in d.checks_evaluated))
        self.assertEqual(d.approved_qty, 4000.0)  # 0.40 * 1,000,000 / 100 (per-position headroom)

    def test_rr1_hint_above_position_limit_vetoed(self):
        d = self.e.evaluate(cand(hint=0.6), ctx(self.e))
        self.assertIs(d.final_verdict, RiskVerdict.REJECT)
        self.assertIn("RR-1", failed_ids(d))
        self.assertTrue(any(r.startswith("RR-1") for r in d.reasons))

    def test_rr1_gross_exposure_including_pending_orders(self):
        pend = (PendingIntent(B, Action.BUY, 4500),)  # 900,000 pending
        d = self.e.evaluate(cand(hint=0.3), ctx(self.e, pending_intents=pend))
        self.assertIn("RR-1", failed_ids(d))

    def test_rr2_leverage_limit(self):
        e = RiskEngine(risk_config(max_leverage=Decimal("0.5"), max_gross_exposure_fraction=Decimal("1.0")))
        d = e.evaluate(cand(hint=0.3), ctx(e, pending_intents=(PendingIntent(B, Action.BUY, 2000),)))
        self.assertIn("RR-2", failed_ids(d))

    def test_rr3_drawdown_halts_buy_but_not_sell(self):
        c = ctx(self.e, equity=Decimal("650000"))  # 35% drawdown vs 30% limit
        self.assertIn("RR-3", failed_ids(self.e.evaluate(cand(), c)))
        pf = PortfolioState(as_of_timestamp=T, positions=(Position(A, 100.0, 90.0),), cash_balance=1000.0,
                            source=PortfolioStateSource.SYSTEM_BELIEF)  # fmt: skip
        sell = self.e.evaluate(cand(action=Action.SELL, hint=0.0), ctx(self.e, equity=Decimal("650000"), portfolio=pf))
        self.assertIs(sell.final_verdict, RiskVerdict.APPROVE)
        self.assertEqual(sell.approved_qty, 100.0)

    def test_rr3_latch_vetoes_even_after_recovery(self):
        d = self.e.evaluate(cand(), ctx(self.e, drawdown_halt_latched=True))
        self.assertIn("RR-3", failed_ids(d))

    def test_rr4_unknown_instrument_hard_veto(self):
        d = self.e.evaluate(cand(inst="INE999X99999", input_snapshot_id="s"), ctx(self.e, snapshot_ids={"INE999X99999": "s"},
                            reference_prices={A: Decimal(1), "INE999X99999": Decimal(100)}))
        self.assertIn("RR-4", failed_ids(d))

    def test_rr4_removed_instrument_exit_only_if_configured_and_held(self):
        pf = PortfolioState(as_of_timestamp=T, positions=(Position(B, 10.0, 100.0),), cash_balance=1.0,
                            source=PortfolioStateSource.SYSTEM_BELIEF)  # fmt: skip
        c = cand(inst=B, action=Action.SELL, hint=0.0, input_snapshot_id="snap_2")
        base = ctx(self.e, portfolio=pf, permitted_instrument_ids=frozenset({A}))
        self.assertIs(self.e.evaluate(c, base).final_verdict, RiskVerdict.APPROVE)
        strict = RiskEngine(risk_config(allow_exit_of_removed_instruments=False))
        d = strict.evaluate(c, ctx(strict, portfolio=pf, permitted_instrument_ids=frozenset({A})))
        self.assertIn("RR-4", failed_ids(d))
        self.assertIn("RR-4", failed_ids(self.e.evaluate(cand(inst=B, input_snapshot_id="snap_2"),
                                                          ctx(self.e, permitted_instrument_ids=frozenset({A})))))

    def test_rr5_order_rate_limit(self):
        e = RiskEngine(risk_config(max_orders_per_window=3, order_rate_window_seconds=60))
        recent = tuple(T - timedelta(seconds=s) for s in (0, 10, 59))
        self.assertIn("RR-5", failed_ids(e.evaluate(cand(), ctx(e, recent_order_timestamps=recent))))
        old = tuple(T - timedelta(seconds=s) for s in (60, 100, 200))  # window is (T-60s, T]
        self.assertIs(e.evaluate(cand(), ctx(e, recent_order_timestamps=old)).final_verdict, RiskVerdict.APPROVE)

    def test_rr6_account_scope(self):
        self.assertIn("RR-6", failed_ids(self.e.evaluate(cand(), ctx(self.e, account_scope="someone-else"))))
        self.assertIn("RR-6", failed_ids(self.e.evaluate(cand(), ctx(self.e, account_scope=None))))

    def test_rr7_attribution(self):
        for over in ({"research_run_id": None}, {"config_version_id": ""},
                     {"snapshot_ids": {A: "not-the-candidates-snapshot"}}, {"snapshot_ids": None},
                     {"evaluated_at": T + timedelta(days=1)}):
            self.assertIn("RR-7", failed_ids(self.e.evaluate(cand(), ctx(self.e, **over))), msg=str(over))
        with self.assertRaises(ValueError):  # the domain type itself refuses missing provenance
            cand(strategy_version_id="  ")
        c = cand()
        object.__setattr__(c, "strategy_version_id", "")  # bypass the type: engine must still veto
        self.assertIn("RR-7", failed_ids(self.e.evaluate(c, ctx(self.e))))

    def test_rr8_kill_switch_active_or_unknown_or_missing_vetoes_everything(self):
        pf = PortfolioState(as_of_timestamp=T, positions=(Position(A, 100.0, 90.0),), cash_balance=1.0,
                            source=PortfolioStateSource.SYSTEM_BELIEF)  # fmt: skip
        for ks in (KillSwitchState.ACTIVE, KillSwitchState.UNKNOWN, None):
            for c in (cand(), cand(action=Action.SELL, hint=0.0)):
                d = self.e.evaluate(c, ctx(self.e, kill_switch=ks, portfolio=pf))
                self.assertIs(d.final_verdict, RiskVerdict.REJECT)
                self.assertIn("RR-8", failed_ids(d))

    def test_rr9_change_requests_for_protected_items_vetoed(self):
        for target in ("risk_rules", "kill_switch", "operator_constraints", "execution_authority", "autonomy_level"):
            d = self.e.evaluate(cand(), ctx(self.e, requested_changes=(ChangeRequest(target, "strategy"),)))
            self.assertIs(d.final_verdict, RiskVerdict.REJECT)
            self.assertIn("RR-9", failed_ids(d), msg=target)

    def test_rr9_tampered_config_detected_by_hash(self):
        object.__setattr__(self.e._config, "max_position_fraction", Decimal("1.0"))  # simulated tampering
        d = self.e.evaluate(cand(hint=0.9), ctx(self.e))
        self.assertIs(d.final_verdict, RiskVerdict.REJECT)
        self.assertIn("RR-9", failed_ids(d))

    def test_rr9_wrong_expected_version_vetoed(self):
        d = self.e.evaluate(cand(), ctx(self.e, expected_risk_rule_version_id="someone-elses-rules"))
        self.assertIn("RR-9", failed_ids(d))

    def test_config_is_immutable(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.e._config.max_leverage = Decimal("50")  # type: ignore[misc]


class FailClosedTests(unittest.TestCase):
    def setUp(self):
        self.e = RiskEngine(risk_config())

    def test_every_missing_state_vetoes(self):
        for field in ("portfolio", "equity", "peak_equity", "reference_prices", "permitted_instrument_ids",
                      "account_scope", "kill_switch", "recent_order_timestamps", "snapshot_ids",
                      "research_run_id", "config_version_id", "expected_risk_rule_version_id", "evaluated_at"):
            d = self.e.evaluate(cand(), ctx(self.e, **{field: None}))
            self.assertIs(d.final_verdict, RiskVerdict.REJECT, msg=field)
            self.assertIsNone(d.approved_qty, msg=field)

    def test_empty_universe_and_missing_price_veto(self):
        self.assertIs(self.e.evaluate(cand(), ctx(self.e, permitted_instrument_ids=frozenset())).final_verdict, RiskVerdict.REJECT)
        self.assertIs(self.e.evaluate(cand(), ctx(self.e, reference_prices={})).final_verdict, RiskVerdict.REJECT)

    def test_invalid_candidate_objects_veto_without_raising(self):
        for bad in (None, "BUY", object(), {"action": "BUY"}):
            d = self.e.evaluate(bad, ctx(self.e))
            self.assertIs(d.final_verdict, RiskVerdict.REJECT)

    def test_invalid_configuration_vetoes_everything(self):
        bad = RiskEngine(risk_config(max_drawdown_fraction=Decimal("0")))
        self.assertTrue(bad.config_errors)
        d = bad.evaluate(cand(), ctx(bad))
        self.assertIs(d.final_verdict, RiskVerdict.REJECT)
        self.assertIn("RR-CONFIG", failed_ids(d))
        self.assertEqual(d.risk_rule_version_id, "INVALID_RISK_CONFIG")
        junk = RiskEngine(object())  # type: ignore[arg-type]
        self.assertIs(junk.evaluate(cand(), ctx(junk)).final_verdict, RiskVerdict.REJECT)

    def test_nan_and_invalid_size_hint_vetoed(self):
        for h in (float("nan"), float("inf"), 1.5):
            d = self.e.evaluate(cand(hint=h), ctx(self.e))
            self.assertIs(d.final_verdict, RiskVerdict.REJECT, msg=str(h))

    def test_sell_with_nothing_held_vetoed_and_hold_never_approved(self):
        self.assertIs(self.e.evaluate(cand(action=Action.SELL, hint=0.0), ctx(self.e)).final_verdict, RiskVerdict.REJECT)
        h = self.e.evaluate(cand(action=Action.HOLD, hint=None), ctx(self.e))
        self.assertIs(h.final_verdict, RiskVerdict.REJECT)
        self.assertIn("RR-NO-EXECUTION", failed_ids(h))

    def test_veto_always_names_the_rule(self):
        d = self.e.evaluate(cand(), ctx(self.e, kill_switch=KillSwitchState.ACTIVE, account_scope="x"))
        self.assertTrue(all(r.split(":")[0].startswith("RR-") for r in d.reasons))
        self.assertEqual({r.split(":")[0] for r in d.reasons}, {"RR-8", "RR-6"})


class VersioningTests(unittest.TestCase):
    def test_version_changes_with_any_value_and_is_deterministic(self):
        a = risk_config().risk_rule_version().version_id
        self.assertEqual(a, risk_config().risk_rule_version().version_id)
        for over in (dict(max_position_fraction=Decimal("0.41")), dict(max_leverage=Decimal("1.1")),
                     dict(max_drawdown_fraction=Decimal("0.29")), dict(max_orders_per_window=99),
                     dict(order_rate_window_seconds=1), dict(permitted_account_scope="b"),
                     dict(allow_exit_of_removed_instruments=False), dict(label="risk_rules_v2")):
            self.assertNotEqual(a, risk_config(**over).risk_rule_version().version_id, msg=str(over))

    def test_configuration_version_is_deterministic(self):
        a, b = risk_config().configuration_version(), risk_config().configuration_version()
        self.assertEqual(a.version_id, b.version_id)
        self.assertEqual(a.set_by, "operator")

    def test_decisions_are_deterministic(self):
        e = RiskEngine(risk_config())
        self.assertEqual(e.evaluate(cand(), ctx(e)), e.evaluate(cand(), ctx(e)))


if __name__ == "__main__":
    unittest.main()
