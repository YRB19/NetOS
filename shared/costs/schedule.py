"""
Versioned India-equity cost schedules.

A schedule is pure configuration/data — rates, not calculation logic — so a
schedule can be replaced (a new version issued) without touching
``calculator.py`` at all, per Stage 3 §6's separation-of-concerns
requirement and §19's cost_model_version discipline.

IMPORTANT — provenance and verification status (see also docs/cost-model.md
§"Provenance and assumptions", and Stage 3 prompt §7/§27):

The rate set below (``INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED``) reflects the
commonly-cited, widely-published structure of Indian equity transaction
costs (STT, exchange transaction charges, SEBI turnover fees, GST, stamp
duty, discount-broker-style brokerage) as commonly reproduced on retail
broker fee/charges pages. It has NOT been independently verified this
session against a primary regulatory source (SEBI circular, exchange
circular, or the Finance Act provisions governing STT/stamp duty). No prior
Stage 0-3 document in this project established a verified, cited rate table
for these specific components.

Per the Slice 4 specification's explicit instruction not to fabricate
regulatory verification, this schedule is marked ``verified=False`` and its
version id carries the "-unverified" suffix. It exists so the Cost Model is
buildable, testable, and usable today; it MUST be reviewed against primary
sources (and re-issued as a new, verified schedule version) before any
result computed from it is treated as authoritative for TR-2/PR-6/PR-9
purposes, or before live/paper trading relies on it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class IndiaEquityCostSchedule:
    """One versioned, immutable set of India-equity cost-calculation rates.

    All rates are expressed as fractions (e.g. Decimal("0.001") == 0.1%),
    not percentages, to avoid a *100/÷100 conversion bug class in the
    calculator.
    """

    version_id: str
    effective_date: str | None
    source: str
    verified: bool

    # Brokerage
    brokerage_delivery_flat: Decimal  # flat fee per delivery order
    brokerage_intraday_flat: Decimal  # flat fee cap per intraday order
    brokerage_intraday_pct: Decimal  # percentage of turnover, intraday

    # STT (Securities Transaction Tax)
    stt_delivery_pct: Decimal  # applied on BOTH buy and sell, delivery
    stt_intraday_sell_pct: Decimal  # applied on SELL only, intraday (0 on buy)

    # Exchange transaction charges (both sides)
    exchange_txn_pct: Decimal

    # SEBI turnover fee (both sides)
    sebi_charges_pct: Decimal

    # GST — applied to (brokerage + exchange_txn_charges + sebi_charges) only,
    # never to STT or stamp duty, per the commonly-documented tax-on-tax rule
    gst_pct: Decimal

    # Stamp duty — BUY side only, both delivery and intraday, per the
    # centrally-uniform stamp-duty-on-securities rules
    stamp_duty_delivery_buy_pct: Decimal
    stamp_duty_intraday_buy_pct: Decimal

    notes: Mapping[str, str] = field(default_factory=dict)


INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED = IndiaEquityCostSchedule(
    version_id="india-equity-v1-unverified",
    effective_date=None,
    source=(
        "Commonly-cited discount-broker charges-page structure (Zerodha/Upstox/"
        "FYERS-style published rate cards, as reproduced across multiple public "
        "broker fee pages). NOT independently verified against a primary SEBI "
        "circular, NSE/BSE exchange circular, or Finance Act provision in this "
        "session. Treat as a configuration default, not a regulatory citation."
    ),
    verified=False,
    brokerage_delivery_flat=Decimal("0"),
    brokerage_intraday_flat=Decimal("20"),
    brokerage_intraday_pct=Decimal("0.0003"),
    stt_delivery_pct=Decimal("0.001"),
    stt_intraday_sell_pct=Decimal("0.00025"),
    exchange_txn_pct=Decimal("0.0000297"),
    sebi_charges_pct=Decimal("0.0000010"),
    gst_pct=Decimal("0.18"),
    stamp_duty_delivery_buy_pct=Decimal("0.00015"),
    stamp_duty_intraday_buy_pct=Decimal("0.00003"),
    notes={
        "stt": (
            "Delivery: STT applied on both buy and sell legs at the same rate. "
            "Intraday: STT applied on the sell leg only; buy leg is zero."
        ),
        "stamp_duty": "Applied on the buy leg only, for both delivery and intraday.",
        "gst_base": "GST applies to (brokerage + exchange_txn_charges + sebi_charges) only.",
        "brokerage_intraday": (
            "min(flat_fee, pct_of_turnover) — the common 'whichever is lower' model."
        ),
        "verification_status": (
            "UNVERIFIED this session — see module docstring and docs/cost-model.md."
        ),
    },
)


class ScheduleRegistry:
    """A simple, explicit lookup of schedule_version -> IndiaEquityCostSchedule.

    Deliberately not a global/singleton default — a CostModel is constructed
    with an explicit registry (or the default one below), so Research code
    evaluating a historical period can pin a specific schedule set without
    depending on whatever the "current" live schedule happens to be (Stage 3
    §6's cost-model-drift concern).
    """

    def __init__(self, schedules: Mapping[str, IndiaEquityCostSchedule]):
        self._schedules: dict[str, IndiaEquityCostSchedule] = dict(schedules)

    def get(self, version_id: str) -> IndiaEquityCostSchedule:
        try:
            return self._schedules[version_id]
        except KeyError as exc:
            raise ValueError(
                f"Unknown cost schedule version_id={version_id!r}. "
                f"Known versions: {sorted(self._schedules)}"
            ) from exc

    def __contains__(self, version_id: str) -> bool:
        return version_id in self._schedules


def default_registry() -> ScheduleRegistry:
    """The registry a caller gets if it doesn't build its own.

    Contains only the single unverified v1 schedule today. Adding a future
    verified schedule is additive (a new entry with a new version_id), never
    an in-place edit of an existing one (Stage 1 DOC-6 versioning discipline).
    """
    return ScheduleRegistry(
        {INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED.version_id: INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED}
    )
