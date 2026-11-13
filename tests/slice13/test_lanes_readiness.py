import unittest
from decimal import Decimal

from markets import (
    CurrencyMismatch, LaneMoney, LaneStatus, MarketLane, SourceVerification, compute_lane_readiness,
    default_external_verification, default_source_verification, lane_spec,
)  # fmt: skip
from markets.readiness import REQUIRED_SOURCE_CHECKS, BranchStatus, CheckResult, VerificationStatus
from markets.us_costs import estimate_us_cost
from simulation.multi_market.report import build_lane_report, combined_index
from simulation.multi_market.sessions import Branch, build_session_matrix


def rd(lane, **kw):
    a = dict(internal_execution_integrated=lane is MarketLane.IN_EQUITIES, cost_schedule_fully_verified=False)
    a.update(kw)
    return compute_lane_readiness(lane, default_source_verification(lane), default_external_verification(lane), **a)


class LaneIdentity(unittest.TestCase):
    def test_lanes_have_distinct_currency_tz_cost_schedule(self):
        us, ind = lane_spec(MarketLane.US_EQUITIES), lane_spec(MarketLane.IN_EQUITIES)
        self.assertEqual((us.currency, ind.currency), ("USD", "INR"))
        self.assertNotEqual(us.timezone, ind.timezone)
        self.assertNotEqual(us.cost_schedule_id, ind.cost_schedule_id)
        self.assertNotIn("india", us.cost_schedule_id)
        self.assertNotEqual(us.identity(), ind.identity())

    def test_money_never_mixes_currencies(self):
        with self.assertRaises(CurrencyMismatch):
            LaneMoney(Decimal(1), "USD") + LaneMoney(Decimal(1), "INR")
        with self.assertRaises(CurrencyMismatch):
            LaneMoney(Decimal(1), "USD") + 1
        self.assertEqual((LaneMoney(Decimal(1), "USD") + LaneMoney(Decimal(2), "USD")).amount, Decimal(3))


class ReadinessIsPerLane(unittest.TestCase):
    def test_nothing_operational_by_default(self):
        for lane in MarketLane:
            self.assertNotEqual(rd(lane).overall, LaneStatus.OPERATIONAL)

    def test_india_data_blocked_without_established_source(self):
        r = rd(MarketLane.IN_EQUITIES)
        self.assertEqual(r.data_status, LaneStatus.BLOCKED)
        self.assertEqual(r.external_branch_status, BranchStatus.BLOCKED)

    def test_fully_verified_us_source_does_not_lift_india(self):
        checks = {n: CheckResult(VerificationStatus.VERIFIED, "https://primary.example/doc", "2026-11-10")
                  for n in REQUIRED_SOURCE_CHECKS}
        us_src = SourceVerification(MarketLane.US_EQUITIES, "P", "prod", "n", checks)
        self.assertEqual(us_src.status, VerificationStatus.VERIFIED)
        us = compute_lane_readiness(MarketLane.US_EQUITIES, us_src, default_external_verification(MarketLane.US_EQUITIES),
                                    internal_execution_integrated=True, cost_schedule_fully_verified=True)
        self.assertEqual(us.overall, LaneStatus.OPERATIONAL)
        self.assertNotEqual(rd(MarketLane.IN_EQUITIES).overall, LaneStatus.OPERATIONAL)

    def test_cross_lane_records_rejected(self):
        with self.assertRaises(ValueError):
            compute_lane_readiness(MarketLane.IN_EQUITIES, default_source_verification(MarketLane.US_EQUITIES),
                                   default_external_verification(MarketLane.IN_EQUITIES),
                                   internal_execution_integrated=True, cost_schedule_fully_verified=True)

    def test_verified_requires_primary_source_and_date(self):
        checks = {n: CheckResult(VerificationStatus.VERIFIED) for n in REQUIRED_SOURCE_CHECKS}
        self.assertEqual(SourceVerification(MarketLane.US_EQUITIES, "P", "p", "n", checks).status,
                         VerificationStatus.UNVERIFIED)

    def test_external_mock_is_not_platform_integration(self):
        self.assertEqual(rd(MarketLane.US_EQUITIES).external_branch_status, BranchStatus.MOCK_ONLY)
        self.assertNotEqual(rd(MarketLane.US_EQUITIES).external_branch_status, BranchStatus.AVAILABLE)

    def test_us_internal_blocked_until_cost_model_integrated(self):
        self.assertEqual(rd(MarketLane.US_EQUITIES).internal_execution_status, LaneStatus.BLOCKED)


class MatrixAndReports(unittest.TestCase):
    def setUp(self):
        self.r = {lane: rd(lane) for lane in MarketLane}

    def test_eight_sessions_with_unique_identities(self):
        m = build_session_matrix(self.r)
        self.assertEqual(len(m), 8)
        self.assertEqual(len({s.session_id for s in m}), 8)
        self.assertEqual(len({s.experiment_id for s in m}), 8)
        self.assertTrue(all(s.session_id.startswith("sess_" + s.lane.value) for s in m))
        self.assertEqual({s.currency for s in m if s.lane is MarketLane.US_EQUITIES}, {"USD"})

    def test_external_branch_never_labelled_available_for_mock(self):
        for s in build_session_matrix(self.r):
            if s.branch is Branch.EXTERNAL:
                self.assertNotEqual(s.status, "AVAILABLE")

    def test_combined_index_has_no_performance_claim(self):
        reps = [build_lane_report(lane, self.r[lane], {}) for lane in MarketLane]
        idx = combined_index(reps)
        self.assertIsNone(idx["combined_performance_claim"])
        self.assertEqual(len(idx["lanes"]), 2)
        self.assertNotIn("overall", idx)

    def test_report_rejects_combined_keys(self):
        with self.assertRaises(ValueError):
            build_lane_report(MarketLane.US_EQUITIES, self.r[MarketLane.US_EQUITIES], {"x": {"combined_pnl": 1}})


class UsCosts(unittest.TestCase):
    def test_us_costs_are_usd_and_flagged_unverified(self):
        e = estimate_us_cost("SELL", 100, Decimal("50"))
        self.assertEqual(e.currency, "USD")
        self.assertFalse(e.verified)
        self.assertEqual(e.total_cost, e.commission + e.sec_fee + e.finra_taf)

    def test_buy_has_no_sell_side_fees(self):
        e = estimate_us_cost("BUY", 100, Decimal("50"))
        self.assertEqual((e.sec_fee, e.finra_taf), (Decimal("0.00"), Decimal("0.00")))


if __name__ == "__main__":
    unittest.main()
