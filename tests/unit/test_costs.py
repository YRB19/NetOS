"""
Unit tests for shared.costs (Slice 4).

Covers: input validation, per-component calculation, rounding, versioning,
independence, and serialization-adjacent round-trip behavior, per the
Slice 4 specification's §22 test matrix.
"""

import ast
import unittest
from decimal import Decimal
from pathlib import Path

from shared.costs import (
    INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED,
    INDIA_EQUITY_SCHEDULE_V2_VERIFIED,
    CostEstimate,
    CostInputs,
    CostModel,
    IndiaEquityCostSchedule,
    ScheduleRegistry,
    TradeType,
    TransactionSide,
    default_registry,
)

SCHEDULE_V1 = INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED.version_id
SCHEDULE_V2 = INDIA_EQUITY_SCHEDULE_V2_VERIFIED.version_id


def make_inputs(**overrides):
    defaults = dict(
        side=TransactionSide.BUY,
        trade_type=TradeType.DELIVERY,
        quantity=100,
        price=Decimal("250.00"),
        schedule_version=SCHEDULE_V1,
    )
    defaults.update(overrides)
    return CostInputs(**defaults)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
class TestCostInputsValidation(unittest.TestCase):
    def test_valid_buy(self):
        inputs = make_inputs(side=TransactionSide.BUY)
        self.assertEqual(inputs.side, TransactionSide.BUY)

    def test_valid_sell(self):
        inputs = make_inputs(side=TransactionSide.SELL)
        self.assertEqual(inputs.side, TransactionSide.SELL)

    def test_invalid_side_type_rejected(self):
        with self.assertRaises(ValueError):
            CostInputs(
                side="BUY",  # not a TransactionSide
                trade_type=TradeType.DELIVERY,
                quantity=10,
                price=Decimal("100"),
                schedule_version=SCHEDULE_V1,
            )

    def test_invalid_trade_type_rejected(self):
        with self.assertRaises(ValueError):
            CostInputs(
                side=TransactionSide.BUY,
                trade_type="INTRADAY",  # not a TradeType
                quantity=10,
                price=Decimal("100"),
                schedule_version=SCHEDULE_V1,
            )

    def test_zero_quantity_allowed(self):
        inputs = make_inputs(quantity=0, price=Decimal("0"))
        self.assertTrue(inputs.is_zero_value)

    def test_negative_quantity_rejected(self):
        with self.assertRaises(ValueError):
            make_inputs(quantity=-5)

    def test_negative_price_rejected(self):
        with self.assertRaises(ValueError):
            make_inputs(price=Decimal("-1"))

    def test_zero_price_with_positive_quantity_rejected(self):
        with self.assertRaises(ValueError):
            make_inputs(quantity=10, price=Decimal("0"))

    def test_zero_price_with_zero_quantity_allowed(self):
        inputs = make_inputs(quantity=0, price=Decimal("0"))
        self.assertEqual(inputs.gross_turnover, Decimal("0"))

    def test_nan_price_rejected(self):
        with self.assertRaises(ValueError):
            make_inputs(price=float("nan"))

    def test_infinite_price_rejected(self):
        with self.assertRaises(ValueError):
            make_inputs(price=float("inf"))

    def test_invalid_schedule_version_empty_string_rejected(self):
        with self.assertRaises(ValueError):
            make_inputs(schedule_version="")

    def test_malformed_schedule_version_type_rejected(self):
        with self.assertRaises(ValueError):
            make_inputs(schedule_version=None)

    def test_float_price_coerced_via_string(self):
        # Guards against binary float error leaking into Decimal price.
        inputs = make_inputs(price=19.99)
        self.assertEqual(inputs.price, Decimal("19.99"))

    def test_unknown_schedule_version_raises_at_calculation_time(self):
        inputs = make_inputs(schedule_version="not-a-real-schedule")
        model = CostModel()
        with self.assertRaises(ValueError):
            model.estimate(inputs)


# ---------------------------------------------------------------------------
# Calculation — components, sides, trade types
# ---------------------------------------------------------------------------
class TestCostCalculation(unittest.TestCase):
    def setUp(self):
        self.model = CostModel()

    def test_delivery_buy_basic(self):
        inputs = make_inputs(
            side=TransactionSide.BUY,
            trade_type=TradeType.DELIVERY,
            quantity=100,
            price=Decimal("250.00"),
        )
        est = self.model.estimate(inputs)
        self.assertEqual(est.gross_turnover, Decimal("25000.00"))
        self.assertEqual(est.brokerage, Decimal("0.00"))  # delivery flat = 0 in v1 schedule
        self.assertEqual(est.stt, Decimal("25.00"))  # 25000 * 0.001
        self.assertGreater(est.exchange_txn_charges, Decimal("0"))
        self.assertGreater(est.sebi_charges, Decimal("0"))
        self.assertGreater(est.gst, Decimal("0"))
        self.assertGreater(est.stamp_duty, Decimal("0"))  # buy side -> stamp duty applies

    def test_delivery_sell_has_no_stamp_duty(self):
        inputs = make_inputs(
            side=TransactionSide.SELL,
            trade_type=TradeType.DELIVERY,
            quantity=100,
            price=Decimal("250.00"),
        )
        est = self.model.estimate(inputs)
        self.assertEqual(est.stamp_duty, Decimal("0.00"))
        self.assertEqual(est.stt, Decimal("25.00"))  # STT applies both sides for delivery

    def test_intraday_buy_has_no_stt(self):
        inputs = make_inputs(
            side=TransactionSide.BUY,
            trade_type=TradeType.INTRADAY,
            quantity=100,
            price=Decimal("250.00"),
        )
        est = self.model.estimate(inputs)
        self.assertEqual(est.stt, Decimal("0.00"))  # STT is sell-only, intraday
        self.assertGreater(est.stamp_duty, Decimal("0"))  # stamp duty still applies to buy

    def test_intraday_sell_has_stt_and_no_stamp_duty(self):
        inputs = make_inputs(
            side=TransactionSide.SELL,
            trade_type=TradeType.INTRADAY,
            quantity=100,
            price=Decimal("250.00"),
        )
        est = self.model.estimate(inputs)
        self.assertGreater(est.stt, Decimal("0"))
        self.assertEqual(est.stamp_duty, Decimal("0.00"))

    def test_intraday_brokerage_is_lower_of_flat_and_pct(self):
        # Large turnover: pct amount should be capped by the flat fee.
        inputs = make_inputs(
            side=TransactionSide.BUY,
            trade_type=TradeType.INTRADAY,
            quantity=10000,
            price=Decimal("500.00"),
        )
        est = self.model.estimate(inputs)
        # turnover = 5,000,000; pct amount = 5,000,000 * 0.0003 = 1500; flat = 20
        self.assertEqual(est.brokerage, Decimal("20.00"))

    def test_intraday_brokerage_pct_used_for_small_trade(self):
        inputs = make_inputs(
            side=TransactionSide.BUY,
            trade_type=TradeType.INTRADAY,
            quantity=1,
            price=Decimal("100.00"),
        )
        est = self.model.estimate(inputs)
        # turnover = 100; pct amount = 100*0.0003 = 0.03; flat = 20 -> min is 0.03
        self.assertEqual(est.brokerage, Decimal("0.03"))

    def test_zero_quantity_transaction_is_all_zero(self):
        inputs = make_inputs(quantity=0, price=Decimal("0"))
        est = self.model.estimate(inputs)
        self.assertEqual(est.total_cost, Decimal("0"))
        for component in (
            est.brokerage,
            est.stt,
            est.exchange_txn_charges,
            est.sebi_charges,
            est.gst,
            est.stamp_duty,
        ):
            self.assertEqual(component, Decimal("0"))

    def test_small_transaction(self):
        inputs = make_inputs(quantity=1, price=Decimal("10.00"))
        est = self.model.estimate(inputs)
        self.assertEqual(est.gross_turnover, Decimal("10.00"))
        self.assertGreaterEqual(est.total_cost, Decimal("0"))

    def test_large_transaction(self):
        inputs = make_inputs(quantity=1_000_000, price=Decimal("1500.00"))
        est = self.model.estimate(inputs)
        self.assertEqual(est.gross_turnover, Decimal("1500000000.00"))
        self.assertGreater(est.total_cost, Decimal("0"))

    def test_gst_base_excludes_stt_and_stamp_duty(self):
        inputs = make_inputs(
            side=TransactionSide.BUY,
            trade_type=TradeType.DELIVERY,
            quantity=100,
            price=Decimal("250.00"),
        )
        est = self.model.estimate(inputs)
        expected_gst_base = est.brokerage + est.exchange_txn_charges + est.sebi_charges
        schedule = INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED
        expected_gst = (expected_gst_base * schedule.gst_pct).quantize(Decimal("0.01"))
        self.assertEqual(est.gst, expected_gst)


# ---------------------------------------------------------------------------
# Total reconstruction
# ---------------------------------------------------------------------------
class TestTotalReconstruction(unittest.TestCase):
    def setUp(self):
        self.model = CostModel()

    def test_total_equals_component_sum_delivery(self):
        inputs = make_inputs(
            side=TransactionSide.BUY,
            trade_type=TradeType.DELIVERY,
            quantity=137,
            price=Decimal("312.45"),
        )
        est = self.model.estimate(inputs)
        self.assertEqual(est.total_cost, est.component_total())

    def test_total_equals_component_sum_intraday(self):
        inputs = make_inputs(
            side=TransactionSide.SELL,
            trade_type=TradeType.INTRADAY,
            quantity=53,
            price=Decimal("77.10"),
        )
        est = self.model.estimate(inputs)
        self.assertEqual(est.total_cost, est.component_total())

    def test_cost_pct_of_turnover_zero_when_turnover_zero(self):
        inputs = make_inputs(quantity=0, price=Decimal("0"))
        est = self.model.estimate(inputs)
        self.assertEqual(est.cost_pct_of_turnover(), Decimal("0"))

    def test_cost_pct_of_turnover_positive_for_normal_trade(self):
        inputs = make_inputs(quantity=100, price=Decimal("250.00"))
        est = self.model.estimate(inputs)
        self.assertGreater(est.cost_pct_of_turnover(), Decimal("0"))


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
class TestRounding(unittest.TestCase):
    def setUp(self):
        self.model = CostModel()

    def test_half_unit_rounds_up(self):
        # Construct a schedule/registry that forces a component to land
        # exactly on a X.XX5 boundary to exercise ROUND_HALF_UP explicitly.
        schedule = IndiaEquityCostSchedule(
            version_id="test-half-up",
            effective_date=None,
            source="test fixture",
            verified=False,
            brokerage_delivery_flat=Decimal("0"),
            brokerage_intraday_flat=Decimal("20"),
            brokerage_intraday_pct=Decimal("0.0003"),
            stt_delivery_pct=Decimal("0.005"),  # chosen to produce a X.XX5 case below
            stt_intraday_sell_pct=Decimal("0.00025"),
            exchange_txn_pct=Decimal("0"),
            sebi_charges_pct=Decimal("0"),
            gst_pct=Decimal("0"),
            stamp_duty_delivery_buy_pct=Decimal("0"),
            stamp_duty_intraday_buy_pct=Decimal("0"),
        )
        registry = ScheduleRegistry({schedule.version_id: schedule})
        model = CostModel(registry=registry)
        # turnover * 0.005 = 1000 * 0.005 = 5.000 exactly -> not a half-boundary case;
        # use a turnover that produces X.XX5 precisely: 1010 * 0.005 = 5.05 (not half either).
        # Choose turnover = 700 -> 700*0.005 = 3.500 -> still not a half-cent case.
        # turnover=350, rate=0.005 -> 1.750: not a half-cent boundary.
        # turnover=1, rate=0.005 -> 0.005 exactly at the half-cent boundary.
        inputs = CostInputs(
            side=TransactionSide.BUY,
            trade_type=TradeType.DELIVERY,
            quantity=1,
            price=Decimal("1.00"),
            schedule_version=schedule.version_id,
        )
        est = model.estimate(inputs)
        # 1 * 0.005 = 0.005 -> ROUND_HALF_UP -> 0.01
        self.assertEqual(est.stt, Decimal("0.01"))

    def test_repeated_calculation_is_identical(self):
        inputs = make_inputs(quantity=333, price=Decimal("199.99"))
        est1 = self.model.estimate(inputs)
        est2 = self.model.estimate(inputs)
        self.assertEqual(est1.total_cost, est2.total_cost)
        self.assertEqual(est1.component_total(), est2.component_total())

    def test_large_amount_rounding_stable(self):
        inputs = make_inputs(quantity=999_999, price=Decimal("9999.99"))
        est = self.model.estimate(inputs)
        self.assertEqual(est.total_cost, est.component_total())

    def test_sub_paisa_precision_input_still_rounds_to_two_decimals(self):
        inputs = make_inputs(quantity=3, price=Decimal("100.005"))
        est = self.model.estimate(inputs)
        # Every component must be quantized to exactly 2 decimal places.
        for component in (
            est.brokerage,
            est.stt,
            est.exchange_txn_charges,
            est.sebi_charges,
            est.gst,
            est.stamp_duty,
        ):
            self.assertEqual(component.as_tuple().exponent, -2)


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------
class TestVersioning(unittest.TestCase):
    def test_schedule_version_present_on_estimate(self):
        model = CostModel()
        inputs = make_inputs()
        est = model.estimate(inputs)
        self.assertEqual(est.schedule_version, SCHEDULE_V1)

    def test_changing_schedule_changes_result(self):
        cheap_schedule = IndiaEquityCostSchedule(
            version_id="cheap-test-schedule",
            effective_date=None,
            source="test fixture",
            verified=False,
            brokerage_delivery_flat=Decimal("0"),
            brokerage_intraday_flat=Decimal("0"),
            brokerage_intraday_pct=Decimal("0"),
            stt_delivery_pct=Decimal("0.0001"),
            stt_intraday_sell_pct=Decimal("0.0001"),
            exchange_txn_pct=Decimal("0"),
            sebi_charges_pct=Decimal("0"),
            gst_pct=Decimal("0"),
            stamp_duty_delivery_buy_pct=Decimal("0"),
            stamp_duty_intraday_buy_pct=Decimal("0"),
        )
        registry = ScheduleRegistry(
            {
                SCHEDULE_V1: INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED,
                cheap_schedule.version_id: cheap_schedule,
            }
        )
        model = CostModel(registry=registry)
        inputs_v1 = make_inputs(schedule_version=SCHEDULE_V1)
        inputs_cheap = make_inputs(schedule_version=cheap_schedule.version_id)

        est_v1 = model.estimate(inputs_v1)
        est_cheap = model.estimate(inputs_cheap)
        self.assertNotEqual(est_v1.total_cost, est_cheap.total_cost)
        self.assertEqual(est_cheap.schedule_version, "cheap-test-schedule")

    def test_same_schedule_produces_identical_result(self):
        model = CostModel()
        inputs = make_inputs(quantity=42, price=Decimal("64.50"))
        est1 = model.estimate(inputs)
        est2 = model.estimate(inputs)
        self.assertEqual(est1, est2)

    def test_registry_unknown_version_raises(self):
        registry = ScheduleRegistry({})
        with self.assertRaises(ValueError):
            registry.get("does-not-exist")


# ---------------------------------------------------------------------------
# Independence — architectural guarantees, checked directly here as well as
# by scripts/check_import_graph.py
# ---------------------------------------------------------------------------
class TestIndependence(unittest.TestCase):
    def test_no_broker_import_in_costs_source(self):
        self._assert_no_forbidden_import_in_package(
            "shared/costs", ["broker", "risk_execution.broker"]
        )

    def test_no_strategy_import_in_costs_source(self):
        self._assert_no_forbidden_import_in_package("shared/costs", ["intelligence", "baseline"])

    def test_no_network_libraries_imported(self):
        self._assert_no_forbidden_import_in_package(
            "shared/costs", ["requests", "urllib", "http", "socket", "aiohttp"]
        )

    def _assert_no_forbidden_import_in_package(self, relative_dir: str, banned_prefixes):
        repo_root = Path(__file__).resolve().parents[2]
        package_dir = repo_root / relative_dir
        for py_file in package_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names = [node.module]
                for name in names:
                    for banned in banned_prefixes:
                        self.assertFalse(
                            name == banned or name.startswith(banned + "."),
                            f"{py_file} imports forbidden module '{name}'",
                        )


# ---------------------------------------------------------------------------
# Determinism (no network/time/random dependence) — structural, not just behavioral
# ---------------------------------------------------------------------------
class TestDeterminism(unittest.TestCase):
    def test_estimate_is_pure_function_of_inputs(self):
        model = CostModel()
        inputs = make_inputs(quantity=17, price=Decimal("83.33"))
        est_list = [model.estimate(inputs) for _ in range(5)]
        first = est_list[0]
        for est in est_list[1:]:
            self.assertEqual(est.total_cost, first.total_cost)
            self.assertEqual(est.component_total(), first.component_total())


# ---------------------------------------------------------------------------
# "Serialization" round-trip — Decimal + enum fields survive a dict round trip
# ---------------------------------------------------------------------------
class TestRoundTrip(unittest.TestCase):
    def test_cost_inputs_field_round_trip(self):
        inputs = make_inputs(quantity=7, price=Decimal("321.00"))
        rebuilt = CostInputs(
            side=inputs.side,
            trade_type=inputs.trade_type,
            quantity=inputs.quantity,
            price=inputs.price,
            schedule_version=inputs.schedule_version,
        )
        self.assertEqual(inputs, rebuilt)

    def test_cost_estimate_field_round_trip(self):
        model = CostModel()
        inputs = make_inputs(quantity=7, price=Decimal("321.00"))
        est = model.estimate(inputs)
        rebuilt = CostEstimate(
            schedule_version=est.schedule_version,
            side=est.side,
            trade_type=est.trade_type,
            gross_turnover=est.gross_turnover,
            brokerage=est.brokerage,
            stt=est.stt,
            exchange_txn_charges=est.exchange_txn_charges,
            sebi_charges=est.sebi_charges,
            gst=est.gst,
            stamp_duty=est.stamp_duty,
            total_cost=est.total_cost,
            schedule_notes=est.schedule_notes,
        )
        self.assertEqual(est, rebuilt)


# ---------------------------------------------------------------------------
# Slice 4.5B — primary-source-verified schedule (india-equity-v2-2026-03-verified)
# ---------------------------------------------------------------------------


class TestVerifiedScheduleV2HandCalculatedFixtures(unittest.TestCase):
    """Exact-Decimal fixtures for the Slice 4.5B verified schedule.

    Each expected component is hand-derived from the primary-source rate
    (see docs/cost-rate-verification.md), independent of the calculator's
    own code, so these tests would catch a wrong-base or wrong-unit bug the
    calculator itself couldn't self-check.
    """

    def test_schedule_is_marked_verified(self):
        self.assertTrue(INDIA_EQUITY_SCHEDULE_V2_VERIFIED.verified)
        self.assertEqual(INDIA_EQUITY_SCHEDULE_V2_VERIFIED.effective_date, "2026-03-01")

    def test_delivery_buy_large_turnover(self):
        # 10,000 shares @ Rs 250.00 = Rs 25,00,000 turnover (Rs 25 lakh).
        model = CostModel()
        est = model.estimate(
            make_inputs(
                side=TransactionSide.BUY,
                trade_type=TradeType.DELIVERY,
                quantity=10_000,
                price=Decimal("250.00"),
                schedule_version=SCHEDULE_V2,
            )
        )
        turnover = Decimal("2500000.00")
        self.assertEqual(est.gross_turnover, turnover)
        # Brokerage: delivery flat = 0 (unverified assumption, unchanged).
        self.assertEqual(est.brokerage, Decimal("0.00"))
        # STT (statutory, verified): 0.1% of turnover = Rs 2500.00.
        self.assertEqual(est.stt, Decimal("2500.00"))
        # Exchange charges (verified, NSE/FA/73061): turnover * 0.0000307
        #   = 2,500,000 * 0.0000307 = Rs 76.75.
        self.assertEqual(est.exchange_txn_charges, Decimal("76.75"))
        # SEBI turnover fee (verified): turnover * 0.000001 = Rs 2.50.
        self.assertEqual(est.sebi_charges, Decimal("2.50"))
        # GST (verified rate, standard base): 18% of (0 + 76.75 + 2.50)
        #   = 18% of 79.25 = Rs 14.265 -> rounds to Rs 14.27 (HALF_UP).
        self.assertEqual(est.gst, Decimal("14.27"))
        # Stamp duty (statutory, verified), buy + delivery: 0.015% of
        #   turnover = 2,500,000 * 0.00015 = Rs 375.00.
        self.assertEqual(est.stamp_duty, Decimal("375.00"))
        expected_total = (
            Decimal("0.00")
            + Decimal("2500.00")
            + Decimal("76.75")
            + Decimal("2.50")
            + Decimal("14.27")
            + Decimal("375.00")
        )
        self.assertEqual(est.total_cost, expected_total)
        self.assertEqual(est.total_cost, est.component_total())

    def test_delivery_sell_no_stamp_duty_verified_schedule(self):
        model = CostModel()
        est = model.estimate(
            make_inputs(
                side=TransactionSide.SELL,
                trade_type=TradeType.DELIVERY,
                quantity=10_000,
                price=Decimal("250.00"),
                schedule_version=SCHEDULE_V2,
            )
        )
        # STT still charged on the sell leg for delivery (verified: both
        # legs taxed at the same 0.1% rate).
        self.assertEqual(est.stt, Decimal("2500.00"))
        # Stamp duty is buy-leg-only (verified): zero on a sell.
        self.assertEqual(est.stamp_duty, Decimal("0.00"))

    def test_intraday_sell_stt_and_exchange_charge(self):
        # 1,000 shares @ Rs 1,000.00 = Rs 10,00,000 turnover (Rs 10 lakh).
        model = CostModel()
        est = model.estimate(
            make_inputs(
                side=TransactionSide.SELL,
                trade_type=TradeType.INTRADAY,
                quantity=1_000,
                price=Decimal("1000.00"),
                schedule_version=SCHEDULE_V2,
            )
        )
        # STT intraday sell (verified): 0.025% of turnover = Rs 250.00.
        self.assertEqual(est.stt, Decimal("250.00"))
        # Exchange charge (verified): 1,000,000 * 0.0000307 = Rs 30.70.
        self.assertEqual(est.exchange_txn_charges, Decimal("30.70"))
        # SEBI charge (verified): 1,000,000 * 0.000001 = Rs 1.00.
        self.assertEqual(est.sebi_charges, Decimal("1.00"))
        # Stamp duty is buy-leg-only: zero on a sell.
        self.assertEqual(est.stamp_duty, Decimal("0.00"))

    def test_intraday_buy_stamp_duty_and_no_stt(self):
        model = CostModel()
        est = model.estimate(
            make_inputs(
                side=TransactionSide.BUY,
                trade_type=TradeType.INTRADAY,
                quantity=1_000,
                price=Decimal("1000.00"),
                schedule_version=SCHEDULE_V2,
            )
        )
        # STT: intraday buy leg is explicitly zero (verified).
        self.assertEqual(est.stt, Decimal("0.00"))
        # Stamp duty intraday buy (verified): 0.003% of 1,000,000 = Rs 30.00.
        self.assertEqual(est.stamp_duty, Decimal("30.00"))

    def test_sebi_turnover_fee_unit_conversion_rs_10_per_crore(self):
        """SEBI's rate is published as 'Rs.10 per crore' -- this test proves
        the schedule's fractional constant is the correct crore-to-fraction
        conversion (10 / 1,00,00,000), not an accidental lakh- or
        per-thousand-based conversion (Slice 4.5B §9's required test)."""
        one_crore = Decimal("10000000.00")  # Rs 1,00,00,000
        model = CostModel()
        est = model.estimate(
            make_inputs(
                side=TransactionSide.BUY,
                trade_type=TradeType.DELIVERY,
                quantity=1,
                price=one_crore,
                schedule_version=SCHEDULE_V2,
            )
        )
        self.assertEqual(est.sebi_charges, Decimal("10.00"))

    def test_exchange_charge_unit_conversion_rs_307_per_crore(self):
        """NSE/FA/73061 publishes Rs 307 per crore of traded value (each
        side); confirm the schedule's fractional constant reproduces that
        exact figure at exactly one crore of turnover."""
        one_crore = Decimal("10000000.00")
        model = CostModel()
        est = model.estimate(
            make_inputs(
                side=TransactionSide.BUY,
                trade_type=TradeType.DELIVERY,
                quantity=1,
                price=one_crore,
                schedule_version=SCHEDULE_V2,
            )
        )
        self.assertEqual(est.exchange_txn_charges, Decimal("307.00"))

    def test_small_turnover_verified_schedule(self):
        model = CostModel()
        est = model.estimate(
            make_inputs(
                side=TransactionSide.BUY,
                trade_type=TradeType.DELIVERY,
                quantity=1,
                price=Decimal("10.00"),
                schedule_version=SCHEDULE_V2,
            )
        )
        self.assertEqual(est.gross_turnover, Decimal("10.00"))
        self.assertEqual(est.total_cost, est.component_total())


class TestHistoricalScheduleReproducibility(unittest.TestCase):
    """Slice 4.5B §17: the old unverified schedule must remain selectable,
    unchanged, and must not be silently affected by the new schedule."""

    def test_v1_still_selectable_by_version_id(self):
        model = CostModel()
        est = model.estimate(make_inputs(schedule_version=SCHEDULE_V1))
        self.assertEqual(est.schedule_version, SCHEDULE_V1)

    def test_v1_rates_unchanged_by_v2_introduction(self):
        # Same fixture as TestCostCalculation.test_delivery_buy_basic would
        # use, evaluated explicitly against V1 to prove V1's numbers did not
        # drift when V2 was added.
        model = CostModel()
        est = model.estimate(
            make_inputs(
                side=TransactionSide.BUY,
                trade_type=TradeType.DELIVERY,
                quantity=10_000,
                price=Decimal("250.00"),
                schedule_version=SCHEDULE_V1,
            )
        )
        # V1's pre-verification exchange rate (Rs 297/crore), NOT V2's Rs 307.
        self.assertEqual(est.exchange_txn_charges, Decimal("74.25"))
        self.assertFalse(INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED.verified)

    def test_v1_and_v2_both_present_in_default_registry(self):
        registry = default_registry()
        self.assertIn(SCHEDULE_V1, registry)
        self.assertIn(SCHEDULE_V2, registry)

    def test_v1_and_v2_give_different_totals_for_identical_inputs(self):
        model = CostModel()
        base = dict(
            side=TransactionSide.BUY,
            trade_type=TradeType.DELIVERY,
            quantity=10_000,
            price=Decimal("250.00"),
        )
        est_v1 = model.estimate(make_inputs(**base, schedule_version=SCHEDULE_V1))
        est_v2 = model.estimate(make_inputs(**base, schedule_version=SCHEDULE_V2))
        self.assertNotEqual(est_v1.total_cost, est_v2.total_cost)
        self.assertEqual(est_v1.schedule_version, SCHEDULE_V1)
        self.assertEqual(est_v2.schedule_version, SCHEDULE_V2)


if __name__ == "__main__":
    unittest.main()
