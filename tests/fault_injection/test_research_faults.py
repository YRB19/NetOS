"""Fault-injection tests for the research harness (Slice 5, spec §24, §28).

Principle under test: the harness fails CLOSED and every failure is a persisted,
reconstructable artifact — never a lost exception and never a 'successful' run.
"""

import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal

from domain.models.enums import Action
from intelligence.baseline.tier1_equal_weight import Tier1EqualWeightBuyHold
from research.experiments.store import read_run_summary, write_run
from research.harness.config import EvaluationPeriod, OrderRejectionPolicy
from research.harness.failures import FailureCategory as FC
from research.harness.failures import RunStatus
from research.harness.runner import ResearchHarness
from tests.unit._research_helpers import (
    ISINS, V1, CallbackStrategy, ThresholdStrategy, _cand, bar, config, day, make_bars, universe,
)  # fmt: skip

H = ResearchHarness()
T1 = Tier1EqualWeightBuyHold
CONT = OrderRejectionPolicy.REJECT_AND_CONTINUE


def run(cfg=None, strat=None, data=None, uni=None):
    return H.run(cfg or config(), strat or T1(), data if data is not None else make_bars(),
                 uni if uni is not None else [universe()])  # fmt: skip


class FailedRunContract(unittest.TestCase):
    def assertFailedClosed(self, r, category):
        self.assertEqual(r.status, RunStatus.FAILED)
        self.assertFalse(r.succeeded)
        self.assertIsNotNone(r.failure)
        self.assertEqual(r.failure.category, category, r.failure.message)
        self.assertIsNone(r.metrics, "a failed run must not report metrics as a result")
        # persisted + reconstructable
        with tempfile.TemporaryDirectory() as d:
            p = write_run(r, d)
            self.assertTrue((p / "failure.json").exists())
            s = read_run_summary(d, r.run_id)
            self.assertEqual(s["status"], "FAILED")
            self.assertEqual(s["failure"]["category"], category.value)
            self.assertTrue(s["run_id"].startswith("run_"))
            self.assertIn("config", s)
            self.assertTrue(s["strategy_version_id"])


class ConfigurationFaults(FailedRunContract):
    def test_invalid_initial_capital(self):
        for bad in ("0", "-100", 0, -5, "abc", "NaN", "Infinity", 1000.5, "1000.123", None, True):
            with self.subTest(bad=bad):
                self.assertFailedClosed(run(config(initial_capital=bad)), FC.INVALID_CONFIGURATION)

    def test_invalid_cost_schedule(self):
        self.assertFailedClosed(run(config(cost_schedule_version="nope")), FC.INVALID_CONFIGURATION)
        self.assertFailedClosed(run(config(cost_schedule_version="")), FC.INVALID_CONFIGURATION)

    def test_other_invalid_config(self):
        for over in (
            {"hypothesis": ""}, {"pre_registered_criteria": "  "}, {"currency": "USD"},
            {"execution_assumption": "SAME_BAR_CLOSE"}, {"allocation_cash_buffer": "1"},
            {"allocation_cash_buffer": "-0.1"}, {"max_staleness_days": -1},
            {"carry_forward_marks": "yes"},
        ):  # fmt: skip
            with self.subTest(over=over):
                self.assertFailedClosed(run(config(**over)), FC.INVALID_CONFIGURATION)

    def test_intraday_not_supported(self):
        from shared.costs import TradeType

        self.assertFailedClosed(run(config(trade_type=TradeType.INTRADAY)), FC.INVALID_CONFIGURATION)

    def test_empty_universe_schedule(self):
        self.assertFailedClosed(run(uni=[]), FC.INVALID_CONFIGURATION)

    def test_invalid_config_still_has_deterministic_identity(self):
        a, b = run(config(initial_capital="-1")), run(config(initial_capital="-1"))
        self.assertEqual(a.run_id, b.run_id)


class DataFaults(FailedRunContract):
    def test_empty_market_data(self):
        self.assertFailedClosed(run(data=[]), FC.MISSING_DATA)

    def test_missing_instrument(self):
        self.assertFailedClosed(run(data=make_bars(ISINS[:2])), FC.MISSING_DATA)

    def test_no_observations_in_window(self):
        data = [bar(i, d, 100.0) for d in range(-10, -5) for i in ISINS]
        self.assertFailedClosed(run(data=data), FC.MISSING_DATA)

    def test_duplicate_data(self):
        self.assertFailedClosed(run(data=make_bars() + [bar(ISINS[1], 3, 77.0, source="DUP")]), FC.DUPLICATE_DATA)

    def test_invalid_data_type(self):
        self.assertFailedClosed(run(data=make_bars() + ["not market data"]), FC.INVALID_DATA)

    def test_missing_observation_for_held_instrument_fails_closed(self):
        self.assertFailedClosed(run(data=make_bars(skip={(ISINS[1], 5)})), FC.MISSING_DATA)

    def test_stale_data_is_never_silently_used(self):
        # instrument A has no bar on day 0: with staleness 0 its snapshot is incomplete
        data = make_bars(skip={(ISINS[0], 0)})
        r = run(data=data)
        first = [d for d in r.decisions if d["decision_timestamp"] == day(0)]
        a = next(d for d in first if d["instrument_id"] == ISINS[0])
        self.assertEqual(a["action"], "HOLD")
        self.assertFalse(a["snapshot_complete"])
        self.assertIsNone(a["reference_price"])
        # never forward-filled into a trade on day 0's data
        self.assertFalse([t for t in r.trades if t["instrument_id"] == ISINS[0] and t["decision_timestamp"] == day(0)])

    def test_staleness_allowance_is_explicit_config(self):
        data = make_bars(skip={(ISINS[0], 0)})
        r = run(config(max_staleness_days=0), data=data)
        r2 = run(config(max_staleness_days=2, carry_forward_marks=True), data=data)
        self.assertNotEqual(r.experiment_id, r2.experiment_id)


class StrategyFaults(FailedRunContract):
    def test_strategy_exception(self):
        def boom(*_):
            raise RuntimeError("model exploded")

        r = run(strat=CallbackStrategy(boom))
        self.assertFailedClosed(r, FC.STRATEGY_ERROR)
        self.assertEqual(r.failure.failed_at_decision, day(0).isoformat())

    def test_non_list_and_non_candidate(self):
        self.assertFailedClosed(run(strat=CallbackStrategy(lambda *_: None)), FC.INVALID_CANDIDATE)
        self.assertFailedClosed(run(strat=CallbackStrategy(lambda *_: ["junk"])), FC.INVALID_CANDIDATE)

    def test_candidate_for_unknown_instrument_or_wrong_snapshot(self):
        def wrong_snap(snaps, u, p):
            c = _cand(snaps[0], Action.HOLD, None, "test_callback_strategy_v1")
            from dataclasses import replace

            return [replace(c, input_snapshot_id="00000000-0000-0000-0000-000000000000")]

        self.assertFailedClosed(run(strat=CallbackStrategy(wrong_snap)), FC.INVALID_CANDIDATE)

    def test_duplicate_candidates_and_wrong_version(self):
        dup = lambda s, u, p: [_cand(s[0], Action.HOLD, None, "test_callback_strategy_v1")] * 2  # noqa: E731
        self.assertFailedClosed(run(strat=CallbackStrategy(dup)), FC.INVALID_CANDIDATE)
        wrongv = lambda s, u, p: [_cand(x, Action.HOLD, None, "other_version") for x in s]  # noqa: E731
        self.assertFailedClosed(run(strat=CallbackStrategy(wrongv)), FC.INVALID_CANDIDATE)

    def test_buy_outside_universe_rejected(self):
        u = universe(ISINS[:2])
        data = make_bars()

        def buy_c(snaps, uni, p):
            return [_cand(s, Action.BUY, 0.3, "test_callback_strategy_v1") for s in snaps]

        # snapshots only cover the universe, so craft an out-of-universe BUY through a removed instrument
        u0, u1 = universe(), universe(ISINS[:2], effective=3)
        r = run(strat=CallbackStrategy(buy_c), uni=[u0, u1], data=data, cfg=config(order_rejection_policy=CONT))
        self.assertFailedClosed(r, FC.INVALID_CANDIDATE)

    def test_strategy_without_version_or_interface(self):
        class Bad:
            pass

        self.assertFailedClosed(run(strat=Bad()), FC.INVALID_CONFIGURATION)


class AccountingFaults(FailedRunContract):
    def gap_up_data(self):
        # day 1 opens +25% above day 0 close: a 1%-buffered BUY cannot be afforded
        data = []
        for d in range(6):
            for i, isin in enumerate(ISINS):
                c = 100.0 * (i + 1)
                data.append(bar(isin, d, c * (1.25 if d >= 1 else 1.0), open_=c * (1.25 if d >= 1 else 1.0) - 0.0))
        return data

    def test_insufficient_cash_fails_closed_by_default(self):
        r = run(config(split=self._split(5)), data=self.gap_up_data())
        self.assertFailedClosed(r, FC.INSUFFICIENT_CASH)
        self.assertTrue(r.decisions, "partial decision context is preserved in the failure artifact")

    def test_reject_and_continue_records_rejections_and_completes(self):
        r = run(config(split=self._split(5), order_rejection_policy=CONT), data=self.gap_up_data())
        self.assertTrue(r.succeeded, r.failure)
        self.assertGreaterEqual(r.metrics["rejected_orders"], 1)
        self.assertTrue(any(x["kind"] == "REJECTED_INSUFFICIENT_CASH" for x in r.rejections))
        for t in r.trades:  # whatever did fill never overspent
            self.assertGreaterEqual(t["portfolio_change"].cash_after, Decimal(0))
        self.assertGreaterEqual(min(p["cash"] for p in r.equity_curve), Decimal(0))

    def _split(self, end):
        from research.harness.config import two_way_split

        return two_way_split(day(-30), day(-1), day(0), day(end))

    def test_overselling_via_direct_order_path(self):
        from research.harness.failures import ResearchRunFailure
        from research.harness.portfolio import ResearchPortfolio

        p = ResearchPortfolio(Decimal("1000"))
        with self.assertRaises(ResearchRunFailure) as c:
            p.sell("X", 1, Decimal("10"), Decimal("0"))
        self.assertEqual(c.exception.category, FC.INSUFFICIENT_POSITION)

    def test_pending_order_blocks_second_order_for_same_instrument(self):
        # instrument B has no bar on day 1, so an order placed on day 0 stays pending; a second
        # BUY on day 1 for B must be rejected rather than double-booked.
        data = make_bars(skip={(ISINS[1], 1)})
        buy_all = CallbackStrategy(
            lambda snaps, u, p: [_cand(s, Action.BUY, 0.3, "test_callback_strategy_v1") for s in snaps]
        )
        r = run(config(order_rejection_policy=CONT, carry_forward_marks=True), strat=buy_all, data=data)
        self.assertTrue(any(x["kind"] == "REJECTED_PENDING_ORDER_EXISTS" for x in r.rejections))


class RepeatabilityFaults(unittest.TestCase):
    def test_deterministic_repeated_run_including_failures(self):
        for cfg in (config(), config(initial_capital="-1"), config(cost_schedule_version=V1)):
            a, b = run(cfg), run(cfg)
            self.assertEqual(a.deterministic_summary(), b.deterministic_summary())
            self.assertEqual(a.trades, b.trades)
            self.assertEqual(a.decisions, b.decisions)
            self.assertEqual(a.equity_curve, b.equity_curve)
            self.assertEqual(a.decision_records, b.decision_records)


if __name__ == "__main__":
    unittest.main()
