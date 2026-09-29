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
version id carries the "-unverified" suffix. It is superseded for live/new
use by ``INDIA_EQUITY_SCHEDULE_V2_VERIFIED`` (see below) but is PRESERVED
UNCHANGED and remains independently selectable by version_id, since research
that already ran against ``india-equity-v1-unverified`` must remain
reproducible (Slice 4.5B §13/§17).

--- Slice 4.5B primary-source verification (session 2026-09-29) -----------

The statutory/exchange components below were checked against official
primary sources. Brokerage was NOT and is not a statutory rate; it remains a
documented, configurable, non-verified assumption. Per-component status:

  STATUTORY  stt_delivery_pct, stt_intraday_sell_pct      -- Finance Act,
             1899 (Indian Stamp Act) / Finance Act STT provisions, as
             tabulated on NSE's official investor page (see below).
  STATUTORY  stamp_duty_delivery_buy_pct,
             stamp_duty_intraday_buy_pct                  -- Indian Stamp
             Act, 1899 as amended by Finance Act 2019, uniform nationwide
             rates effective 1 July 2020.
  REGULATORY sebi_charges_pct                             -- SEBI turnover
             fee, per SEBI (Stock Brokers) Regulations Third Schedule, as
             tabulated by NSE.
  EXCHANGE   exchange_txn_pct                             -- NSE circular
             NSE/FA/73061 (27 Feb 2026), effective 1 Mar 2026; this is an
             NSE-specific rate (BSE's cash-market rate can differ) and is
             carried as a configurable exchange-charge default, not a
             cross-exchange statutory constant.
  REGULATORY gst_pct                                      -- CGST/SGST rate
             on stock-broker/MII services, per NSE's published rate (18%).
             The GST *base* used here (brokerage + exchange_txn + sebi
             charges, excluding STT and stamp duty, which are non-supply
             statutory levies outside GST's scope) follows universal
             industry contract-note practice; the primary source confirms
             the RATE, not an itemised BASE formula, so the base is recorded
             as CONFIGURABLE-BUT-STANDARD rather than independently
             verified line-by-line.
  ASSUMPTION brokerage_delivery_flat, brokerage_intraday_flat,
             brokerage_intraday_pct                       -- a generic,
             commonly-published discount-broker fee structure. NOT a
             statutory rate and NOT tied to one named broker's official,
             dated rate card. Remains an explicit configuration default.

Primary sources (see docs/cost-rate-verification.md for the full audit
trail, including exact excerpts, URLs, and verification date):
  - NSE, "SEBI Turnover Fees, STT and Other levies"
    (nseindia.com/invest/first-time-investor-sebi-turnover-fees-stt-other-levies),
    page states "Updated on: 17/04/2026" -- STT, SEBI turnover fee, GST rate.
  - NSE, "Stamp Duty"
    (nseindia.com/invest/first-time-investor-stamp-duty-charges-taxes),
    page states "Updated on: 03/10/2023" -- stamp duty rate table (rates
    themselves are the post-1-July-2020 uniform rates, unchanged since).
  - NSE circular NSE/FA/73061, 27 Feb 2026, "Revision in Transaction
    Charges", effective 1 Mar 2026 -- exchange transaction-charge + NSE
    IPFT-contribution total outflow for the Cash Market segment.
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


INDIA_EQUITY_SCHEDULE_V2_VERIFIED = IndiaEquityCostSchedule(
    version_id="india-equity-v2-2026-03-verified",
    effective_date="2026-03-01",
    source=(
        "Primary-source verified (Slice 4.5B, verification date 2026-09-29). "
        "STT, SEBI turnover fee, stamp duty and GST rate confirmed against "
        "NSE's official investor-education pages (updated 17/04/2026 and "
        "03/10/2023 respectively); exchange transaction charge confirmed "
        "against NSE circular NSE/FA/73061 (27 Feb 2026, effective 1 Mar "
        "2026). Brokerage remains an unverified, generic configuration "
        "assumption -- see module docstring and docs/cost-rate-verification.md "
        "for the full per-component classification and source excerpts."
    ),
    verified=True,
    # Brokerage: unchanged generic assumption -- NOT part of the "verified"
    # claim above (see module docstring's per-component classification).
    brokerage_delivery_flat=Decimal("0"),
    brokerage_intraday_flat=Decimal("20"),
    brokerage_intraday_pct=Decimal("0.0003"),
    # STT -- verified against NSE's official rate table, unchanged from V1.
    stt_delivery_pct=Decimal("0.001"),
    stt_intraday_sell_pct=Decimal("0.00025"),
    # Exchange transaction charges -- UPDATED per NSE/FA/73061: total Cash
    # Market outflow (transaction charge Rs 306.99/crore + NSE IPFT
    # contribution Rs 0.01/crore) = Rs 307.00 per crore of traded value,
    # each side = 307 / 1,00,00,000 = 0.0000307 (supersedes V1's
    # pre-1-Mar-2026 Rs 297/crore = 0.0000297).
    exchange_txn_pct=Decimal("0.0000307"),
    # SEBI turnover fee -- Rs 10 per crore = 10 / 1,00,00,000 = 0.000001,
    # i.e. 0.0001%, verified against NSE's published rate table; unchanged.
    sebi_charges_pct=Decimal("0.0000010"),
    # GST rate verified at 18% against NSE's published rate table; base
    # composition (brokerage + exchange_txn + sebi_charges only) is
    # standard industry contract-note practice, not itself itemised by the
    # primary source -- see module docstring.
    gst_pct=Decimal("0.18"),
    # Stamp duty -- verified against NSE's official rate table (0.015%
    # delivery / 0.003% non-delivery, buyer-borne); unchanged from V1.
    stamp_duty_delivery_buy_pct=Decimal("0.00015"),
    stamp_duty_intraday_buy_pct=Decimal("0.00003"),
    notes={
        "stt": (
            "VERIFIED (NSE, updated 17/04/2026). Delivery: STT on both buy "
            "and sell legs. Intraday: sell leg only; buy leg zero."
        ),
        "stamp_duty": (
            "VERIFIED (NSE, updated 03/10/2023; rates unchanged since the "
            "1 July 2020 uniform-stamp-duty reform). Buy leg only."
        ),
        "sebi_charges": "VERIFIED (NSE, updated 17/04/2026): Rs 10 per crore = 0.0001%.",
        "exchange_txn": (
            "VERIFIED, NSE-specific (NSE/FA/73061, effective 2026-03-01): "
            "Rs 307 per crore of traded value each side, being the total "
            "outflow of transaction charge (Rs 306.99) plus NSE IPFT "
            "contribution (Rs 0.01). BSE's cash-market rate is separately "
            "published and may differ."
        ),
        "gst_rate": "VERIFIED (NSE, updated 17/04/2026): 18% on stock-broker/MII services.",
        "gst_base": (
            "CONFIGURABLE-BUT-STANDARD: applies to (brokerage + "
            "exchange_txn_charges + sebi_charges) only, per universal "
            "contract-note practice; STT and stamp duty are non-supply "
            "statutory levies outside GST's scope, so excluded."
        ),
        "brokerage": (
            "ASSUMPTION, NOT VERIFIED: a generic discount-broker-style fee "
            "structure (delivery free; intraday whichever-is-lower of a "
            "flat fee or a percentage of turnover). Not tied to any one "
            "named broker's dated, official rate card."
        ),
        "brokerage_intraday": (
            "min(flat_fee, pct_of_turnover) -- the common 'whichever is lower' model."
        ),
        "verification_status": (
            "Statutory/regulatory/exchange components VERIFIED against "
            "primary sources 2026-09-29; brokerage remains an unverified "
            "configuration assumption. See docs/cost-rate-verification.md."
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

    Contains both the original unverified v1 schedule (preserved unchanged,
    for historical reproducibility -- Slice 4.5B §13/§17) and the Slice 4.5B
    primary-source-verified v2 schedule, added additively per Stage 1 DOC-6's
    versioning discipline: neither entry is ever edited in place.
    """
    return ScheduleRegistry(
        {
            INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED.version_id: INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED,
            INDIA_EQUITY_SCHEDULE_V2_VERIFIED.version_id: INDIA_EQUITY_SCHEDULE_V2_VERIFIED,
        }
    )
