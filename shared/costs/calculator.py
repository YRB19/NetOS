"""
Deterministic India-equity cost calculator.

Pure calculation logic only — no I/O, no broker, no strategy, no network,
no clock/time dependence, no randomness (Stage 3 §18 determinism
requirement). Every method is a pure function of its explicit arguments.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .models import CostEstimate, CostInputs, TradeType, TransactionSide
from .schedule import IndiaEquityCostSchedule, ScheduleRegistry, default_registry

# --- Rounding policy (Stage 3 §14) ---------------------------------------
# Every individual cost component is rounded independently to 2 decimal
# places (nearest paisa) using ROUND_HALF_UP, at the point that component is
# computed. The total is then the exact Decimal sum of the already-rounded
# components — it is NOT independently re-rounded. This guarantees
# total_cost == component_total() by construction (Stage 3 §16's
# reconstructability test), rather than as a coincidence of two separate
# roundings agreeing.
_CENT = Decimal("0.01")


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


class CostModel:
    """Stateless-except-for-its-registry cost calculator.

    `estimate()` is the single public entry point, matching the
    `CostInputs -> CostEstimate` contract required by the Slice 4
    specification.
    """

    def __init__(self, registry: ScheduleRegistry | None = None):
        self._registry = registry if registry is not None else default_registry()

    def estimate(self, inputs: CostInputs) -> CostEstimate:
        schedule = self._registry.get(inputs.schedule_version)

        if inputs.is_zero_value:
            # Explicit zero-value-transaction behavior (Stage 3 §4/§17):
            # a zero-quantity "transaction" costs nothing, by definition,
            # rather than raising or applying flat fees against a null trade.
            return CostEstimate(
                schedule_version=schedule.version_id,
                side=inputs.side,
                trade_type=inputs.trade_type,
                gross_turnover=Decimal("0"),
                brokerage=Decimal("0"),
                stt=Decimal("0"),
                exchange_txn_charges=Decimal("0"),
                sebi_charges=Decimal("0"),
                gst=Decimal("0"),
                stamp_duty=Decimal("0"),
                total_cost=Decimal("0"),
                schedule_notes=dict(schedule.notes),
            )

        turnover = inputs.gross_turnover

        brokerage = self._brokerage(inputs, schedule, turnover)
        stt = self._stt(inputs, schedule, turnover)
        exchange_txn = _round_money(turnover * schedule.exchange_txn_pct)
        sebi_charges = _round_money(turnover * schedule.sebi_charges_pct)
        gst = _round_money((brokerage + exchange_txn + sebi_charges) * schedule.gst_pct)
        stamp_duty = self._stamp_duty(inputs, schedule, turnover)

        total_cost = brokerage + stt + exchange_txn + sebi_charges + gst + stamp_duty

        return CostEstimate(
            schedule_version=schedule.version_id,
            side=inputs.side,
            trade_type=inputs.trade_type,
            gross_turnover=turnover,
            brokerage=brokerage,
            stt=stt,
            exchange_txn_charges=exchange_txn,
            sebi_charges=sebi_charges,
            gst=gst,
            stamp_duty=stamp_duty,
            total_cost=total_cost,
            schedule_notes=dict(schedule.notes),
        )

    # --- component calculations, each independently inspectable/testable ---

    @staticmethod
    def _brokerage(
        inputs: CostInputs, schedule: IndiaEquityCostSchedule, turnover: Decimal
    ) -> Decimal:
        if inputs.trade_type is TradeType.DELIVERY:
            return _round_money(schedule.brokerage_delivery_flat)
        # INTRADAY: min(flat, pct * turnover) — the common "whichever is lower" model
        pct_amount = turnover * schedule.brokerage_intraday_pct
        chosen = min(schedule.brokerage_intraday_flat, pct_amount)
        return _round_money(chosen)

    @staticmethod
    def _stt(inputs: CostInputs, schedule: IndiaEquityCostSchedule, turnover: Decimal) -> Decimal:
        if inputs.trade_type is TradeType.DELIVERY:
            # Both BUY and SELL taxed at the same delivery rate.
            return _round_money(turnover * schedule.stt_delivery_pct)
        # INTRADAY: SELL only; BUY leg is explicitly zero, not omitted.
        if inputs.side is TransactionSide.SELL:
            return _round_money(turnover * schedule.stt_intraday_sell_pct)
        return Decimal("0.00")

    @staticmethod
    def _stamp_duty(
        inputs: CostInputs, schedule: IndiaEquityCostSchedule, turnover: Decimal
    ) -> Decimal:
        if inputs.side is not TransactionSide.BUY:
            # Stamp duty applies to the buy leg only; SELL is explicitly zero.
            return Decimal("0.00")
        if inputs.trade_type is TradeType.DELIVERY:
            return _round_money(turnover * schedule.stamp_duty_delivery_buy_pct)
        return _round_money(turnover * schedule.stamp_duty_intraday_buy_pct)
