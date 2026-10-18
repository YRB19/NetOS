"""Slice 6 — Tier-2 12-1 momentum: formula, no-lookahead, rebalance, ranking, provenance.

SYNTHETIC fixtures only; nothing here is evidence of trading performance.
"""

from __future__ import annotations

import math
import unittest
from datetime import timedelta

from data.features.calendar import shift_months
from data.features.momentum import (
    FEATURE_MOMENTUM,
    FEATURE_REBALANCE,
    MomentumConfig,
    MomentumFeatureBuilder,
)
from domain.models.enums import Action
from intelligence.baseline.tier2_momentum import (
    TOP_DECILE,
    TOP_QUINTILE,
    Tier2Momentum12_1,
    Tier2MomentumConfig,
    selected_count,
)
from tests.unit._pipeline_helpers import HIST_START, ISINS, tier2, universe, weekly_bars


def snaps(bars, w, builder, uni=None):
    t = HIST_START + timedelta(days=7 * w)
    u = uni or universe()
    vis = [b for b in bars if b.timestamp <= t]
    return t, builder.build(vis, u, t, market_data_snapshot_version="v1", instrument_ids=sorted(u.instrument_ids)), u


def first_of_month_week(after=60):
    """Independent re-derivation: first weekly bar index >= after that opens a calendar month."""
    for w in range(after, 78):
        t = HIST_START + timedelta(days=7 * w)
        prev = HIST_START + timedelta(days=7 * (w - 1))
        if (t.year, t.month) != (prev.year, prev.month):
            return w
    raise AssertionError


class MomentumFormulaTests(unittest.TestCase):
    def test_momentum_equals_close_t_minus_1m_over_close_t_minus_12m_minus_1(self):
        bars = weekly_bars()
        w = first_of_month_week()
        t, ss, _ = snaps(bars, w, MomentumFeatureBuilder())
        end_d, start_d = shift_months(t, -1).date(), shift_months(t, -12).date()
        for s in ss:
            mine = sorted((b for b in bars if b.instrument_id == s.instrument_id), key=lambda b: b.timestamp)
            p_end = [b for b in mine if b.timestamp.date() <= end_d][-1].close
            p_start = [b for b in mine if b.timestamp.date() <= start_d][-1].close
            self.assertAlmostEqual(s.feature_values[FEATURE_MOMENTUM], p_end / p_start - 1.0, places=12)

    def test_most_recent_month_is_excluded(self):
        w = first_of_month_week()
        t = HIST_START + timedelta(days=7 * w)
        b0 = weekly_bars()
        skipped = {(isin, k) for k in range(w - 3, w + 1) for isin in ISINS
                   if shift_months(t, -1).date() < (HIST_START + timedelta(days=7 * k)).date() <= t.date()}
        self.assertTrue(skipped)
        b1 = weekly_bars(override={key: 9999.0 for key in skipped})
        _, s0, _ = snaps(b0, w, MomentumFeatureBuilder())
        _, s1, _ = snaps(b1, w, MomentumFeatureBuilder())
        self.assertEqual([x.feature_values[FEATURE_MOMENTUM] for x in s0],
                         [x.feature_values[FEATURE_MOMENTUM] for x in s1])

    def test_price_at_t_minus_1m_IS_used(self):
        w = first_of_month_week()
        t = HIST_START + timedelta(days=7 * w)
        end_d = shift_months(t, -1).date()
        k = max(j for j in range(w) if (HIST_START + timedelta(days=7 * j)).date() <= end_d)
        b1 = weekly_bars(override={(ISINS[0], k): 1e6})
        _, s0, _ = snaps(weekly_bars(), w, MomentumFeatureBuilder())
        _, s1, _ = snaps(b1, w, MomentumFeatureBuilder())
        self.assertNotEqual(s0[0].feature_values[FEATURE_MOMENTUM], s1[0].feature_values[FEATURE_MOMENTUM])

    def test_calendar_shift_clamps_month_end(self):
        t = HIST_START.replace(year=2026, month=3, day=31)
        self.assertEqual(shift_months(t, -1).day, 28)

    def test_config_validation(self):
        self.assertTrue(MomentumConfig(lookback_months=1, skip_months=1).validate())
        self.assertTrue(MomentumConfig(skip_months=-1).validate())
        with self.assertRaises(ValueError):
            MomentumFeatureBuilder(MomentumConfig(lookback_months=0, skip_months=1))

    def test_insufficient_history_means_missing_not_zero(self):
        _, ss, _ = snaps(weekly_bars(), 20, MomentumFeatureBuilder())
        self.assertTrue(all(FEATURE_MOMENTUM not in s.feature_values for s in ss))


class NoLookaheadTests(unittest.TestCase):
    def test_future_bars_cannot_change_decision_even_if_passed_to_builder(self):
        w = first_of_month_week()
        clean = weekly_bars()
        poisoned = weekly_bars(override={(isin, k): 1.0 + i for k in range(w + 1, 78)
                                         for i, isin in enumerate(ISINS)})
        strat, b = tier2(0.3)
        t = HIST_START + timedelta(days=7 * w)
        u = universe()
        s_clean = b.build(clean, u, t, market_data_snapshot_version="v", instrument_ids=sorted(u.instrument_ids))
        s_pois = b.build(poisoned, u, t, market_data_snapshot_version="v", instrument_ids=sorted(u.instrument_ids))
        self.assertEqual([s.snapshot_id for s in s_clean], [s.snapshot_id for s in s_pois])
        self.assertEqual(strat.generate_candidate_trades(s_clean, u, None),
                         strat.generate_candidate_trades(s_pois, u, None))

    def test_one_future_observation_would_flip_ranking_but_is_not_consumed(self):
        w = first_of_month_week()
        t = HIST_START + timedelta(days=7 * w)
        from dataclasses import replace
        clean = weekly_bars()
        extra = replace([b for b in clean if b.instrument_id == ISINS[0]][w],
                        timestamp=t + timedelta(seconds=1), close=1e7, open=1e7, high=1e7 + 1, low=1e7 - 1)
        strat, b = tier2(0.3)
        u = universe()
        base = b.build([x for x in clean], u, t, market_data_snapshot_version="v", instrument_ids=sorted(u.instrument_ids))
        with_future = b.build([*clean, extra], u, t, market_data_snapshot_version="v", instrument_ids=sorted(u.instrument_ids))
        self.assertEqual(strat.generate_candidate_trades(base, u, None),
                         strat.generate_candidate_trades(with_future, u, None))
        top = {c.instrument_id for c in strat.generate_candidate_trades(with_future, u, None)
               if c.action is Action.BUY}
        self.assertNotIn(ISINS[0], top)


class RebalanceTests(unittest.TestCase):
    def test_only_first_observation_of_month_is_rebalance(self):
        bars, (strat, b) = weekly_bars(), tier2(0.3)
        flags = []
        for w in range(60, 78):
            _, ss, _ = snaps(bars, w, b)
            flags.append(ss[0].feature_values[FEATURE_REBALANCE])
        months = [(HIST_START + timedelta(days=7 * w)).month for w in range(60, 78)]
        expect = [1.0 if i == 0 or months[i] != months[i - 1] else 0.0 for i in range(len(months))]
        expect[0] = 1.0 if (HIST_START + timedelta(days=7 * 59)).month != months[0] else 0.0
        self.assertEqual(flags, expect)
        self.assertGreater(sum(flags), 0)
        self.assertLess(sum(flags), len(flags))

    def test_non_rebalance_date_emits_only_holds(self):
        bars, (strat, b) = weekly_bars(), tier2(0.3)
        w = first_of_month_week() + 1
        t, ss, u = snaps(bars, w, b)
        out = strat.generate_candidate_trades(ss, u, None)
        self.assertTrue(out and all(c.action is Action.HOLD for c in out))

    def test_rebalance_flag_missing_fails_safe_to_hold(self):
        from dataclasses import replace
        strat, b = tier2(0.3)
        t, ss, u = snaps(weekly_bars(), first_of_month_week(), b)
        ss = [replace(s, feature_values={k: v for k, v in s.feature_values.items() if k != FEATURE_REBALANCE})
              for s in ss]
        out = strat.generate_candidate_trades(ss, u, None)
        self.assertTrue(all(c.action is Action.HOLD for c in out))


class RankingTests(unittest.TestCase):
    def test_top_fraction_buys_rest_sell(self):
        strat, b = tier2(0.3)
        t, ss, u = snaps(weekly_bars(), first_of_month_week(), b)
        out = {c.instrument_id: c for c in strat.generate_candidate_trades(ss, u, None)}
        buys = sorted(i for i, c in out.items() if c.action is Action.BUY)
        self.assertEqual(buys, sorted(ISINS[-3:]))
        for i in buys:
            self.assertAlmostEqual(out[i].size_hint, 1 / 3)
        sells = [c for c in out.values() if c.action is Action.SELL]
        self.assertEqual(len(sells), 7)
        self.assertTrue(all(c.size_hint == 0.0 for c in sells))

    def test_ties_broken_by_instrument_id_ascending(self):
        bars = weekly_bars(growth=lambda i: 0.002)
        strat, b = tier2(0.3)
        t, ss, u = snaps(bars, first_of_month_week(), b)
        buys = sorted(c.instrument_id for c in strat.generate_candidate_trades(ss, u, None) if c.action is Action.BUY)
        self.assertEqual(buys, sorted(ISINS)[:3])

    def test_ordering_independent_of_input_order(self):
        strat, b = tier2(0.3)
        t, ss, u = snaps(weekly_bars(), first_of_month_week(), b)
        a = strat.generate_candidate_trades(ss, u, None)
        c = strat.generate_candidate_trades(list(reversed(ss)), u, None)
        self.assertEqual(sorted(a, key=lambda x: x.instrument_id), sorted(c, key=lambda x: x.instrument_id))

    def test_missing_momentum_is_held_not_ranked_not_liquidated(self):
        bars = [x for x in weekly_bars() if not (x.instrument_id == ISINS[9] and x.timestamp < HIST_START + timedelta(days=7 * 45))]
        strat, b = tier2(0.3)
        t, ss, u = snaps(bars, first_of_month_week(), b)
        out = {c.instrument_id: c for c in strat.generate_candidate_trades(ss, u, None)}
        self.assertIs(out[ISINS[9]].action, Action.HOLD)
        self.assertIn("momentum unavailable", out[ISINS[9]].rationale)
        self.assertEqual(sorted(i for i, c in out.items() if c.action is Action.BUY), sorted(ISINS[-4:-1]))

    def test_presets_and_small_universe_never_select_zero(self):
        self.assertEqual((TOP_DECILE, TOP_QUINTILE), (0.10, 0.20))
        self.assertEqual(selected_count(30, 0.1), 3)
        self.assertEqual(selected_count(10, 0.1), 1)
        self.assertEqual(selected_count(3, 0.1), 1)
        self.assertEqual(selected_count(1, 0.2), 1)
        self.assertEqual(selected_count(7, 0.2), 2)
        self.assertEqual(selected_count(5, 1.0), 5)
        self.assertEqual(selected_count(0, 0.2), 0)

    def test_small_universe_end_to_end(self):
        strat, b = tier2(TOP_DECILE)
        u = universe(ISINS[:3])
        bars = weekly_bars(ISINS[:3])
        t, ss, _ = snaps(bars, first_of_month_week(), b, u)
        buys = [c for c in strat.generate_candidate_trades(ss, u, None) if c.action is Action.BUY]
        self.assertEqual(len(buys), 1)
        self.assertEqual(buys[0].size_hint, 1.0)

    def test_removed_instrument_is_exited_any_date(self):
        strat, b = tier2(0.3)
        u_prev = universe()
        u_now = universe(ISINS[:9])
        t, ss, _ = snaps(weekly_bars(), first_of_month_week() + 1, b, u_prev)
        vis = [x for x in weekly_bars() if x.timestamp <= t]
        ss = b.build(vis, u_now, t, market_data_snapshot_version="v", instrument_ids=sorted(u_prev.instrument_ids))
        out = {c.instrument_id: c for c in strat.generate_candidate_trades(ss, u_now, u_prev)}
        self.assertIs(out[ISINS[9]].action, Action.SELL)
        self.assertEqual(out[ISINS[9]].size_hint, 0.0)


class ProvenanceAndConfigTests(unittest.TestCase):
    def test_candidates_carry_strategy_version_snapshot_and_no_quantity(self):
        strat, b = tier2(0.3)
        t, ss, u = snaps(weekly_bars(), first_of_month_week(), b)
        ids = {s.snapshot_id for s in ss}
        for c in strat.generate_candidate_trades(ss, u, None):
            self.assertEqual(c.strategy_version_id, strat.strategy_version_id)
            self.assertIn(c.input_snapshot_id, ids)
            self.assertTrue(c.rationale.strip())
            self.assertTrue(0.0 <= c.confidence <= 1.0)
            self.assertIsNone(c.model_version_id)
            self.assertFalse(hasattr(c, "quantity"))
        self.assertTrue(strat.strategy_version_id.startswith("tier2_momentum_12_1_v1@"))

    def test_version_id_changes_with_every_config_value(self):
        a = tier2(0.2)[0].strategy_version_id
        self.assertNotEqual(a, tier2(0.1)[0].strategy_version_id)
        self.assertNotEqual(a, tier2(0.2, lookback_months=6)[0].strategy_version_id)
        self.assertEqual(a, tier2(0.2)[0].strategy_version_id)
        sv = tier2(0.2)[0].strategy_version()
        self.assertEqual(sv.version_id, a)

    def test_invalid_fractions_rejected(self):
        for bad in (0, -0.1, 1.01, math.nan, math.inf, True, "0.2", None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                Tier2Momentum12_1(Tier2MomentumConfig(selection_fraction=bad))  # type: ignore[arg-type]

    def test_mismatched_feature_set_is_refused(self):
        strat, _ = tier2(0.3)
        _, b6 = tier2(0.3, lookback_months=6)
        t, ss, u = snaps(weekly_bars(), first_of_month_week(), b6)
        with self.assertRaises(ValueError):
            strat.generate_candidate_trades(ss, u, None)

    def test_deterministic_repeat(self):
        strat, b = tier2(0.3)
        t, ss, u = snaps(weekly_bars(), first_of_month_week(), b)
        self.assertEqual(strat.generate_candidate_trades(ss, u, None), strat.generate_candidate_trades(ss, u, None))


if __name__ == "__main__":
    unittest.main()
