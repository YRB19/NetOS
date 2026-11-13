"""Market lanes. Two independent experiments: US_EQUITIES and IN_EQUITIES (ADR-25).

A lane owns its currency, timezone/session rules, calendar, benchmark, cost schedule id and
strategy-config ids. Nothing in this module aggregates across lanes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from shared.versioning.content_hash import hash_json_stable


class MarketLane(str, Enum):  # noqa: UP042
    US_EQUITIES = "US_EQUITIES"
    IN_EQUITIES = "IN_EQUITIES"


class DataProvenance(str, Enum):  # noqa: UP042
    """What kind of data an observation is. Only LIVE can support live-data-shadow claims."""

    LIVE = "LIVE"
    REPLAY = "REPLAY"
    SYNTHETIC = "SYNTHETIC"


class SessionPhase(str, Enum):  # noqa: UP042
    PRE_MARKET = "PRE_MARKET"
    REGULAR = "REGULAR"
    POST_MARKET = "POST_MARKET"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class LaneSpec:
    lane: MarketLane
    currency: str
    timezone: str  # IANA zone used for PRESENTATION and session rules; persistence is always UTC
    exchanges: tuple[str, ...]
    calendar_id: str
    regular_open_local: str  # HH:MM, market-local
    regular_close_local: str
    benchmark_id: str
    cost_schedule_id: str  # lane-specific; never shared across lanes
    tier1_config_id: str
    tier2_config_id: str
    instrument_master_version: str
    universe_version: str
    notes: str = ""

    def identity(self) -> str:
        return hash_json_stable(
            {k: (v.value if isinstance(v, Enum) else v) for k, v in self.__dict__.items()}
        )[:24]


# Universe/benchmark identifiers are DECLARATIONS for protocol freezing. They do not assert that
# an instrument master or constituent list has been sourced; see docs/multi-market-shadow.md.
LANE_SPECS: dict[MarketLane, LaneSpec] = {
    MarketLane.US_EQUITIES: LaneSpec(
        lane=MarketLane.US_EQUITIES, currency="USD", timezone="America/New_York",
        exchanges=("NYSE", "NASDAQ", "ARCA", "IEX"), calendar_id="us-equities-regular-v1",
        regular_open_local="09:30", regular_close_local="16:00",
        benchmark_id="BENCH_US_UNSPECIFIED_v1", cost_schedule_id="us-equity-v1-unverified",
        tier1_config_id="tier1-equal-weight-us-v1", tier2_config_id="tier2-momentum-12-1-us-v1",
        instrument_master_version="us-master-UNSOURCED-v0", universe_version="us-universe-UNSOURCED-v0",
        notes="Benchmark, universe and instrument master are declared placeholders until sourced.",
    ),
    MarketLane.IN_EQUITIES: LaneSpec(
        lane=MarketLane.IN_EQUITIES, currency="INR", timezone="Asia/Kolkata",
        exchanges=("NSE", "BSE"), calendar_id="in-equities-regular-v1",
        regular_open_local="09:15", regular_close_local="15:30",
        benchmark_id="BENCH_IN_UNSPECIFIED_v1", cost_schedule_id="india-equity-v2-2026-03-verified",
        tier1_config_id="tier1-equal-weight-in-v1", tier2_config_id="tier2-momentum-12-1-in-v1",
        instrument_master_version="in-master-UNSOURCED-v0", universe_version="in-universe-UNSOURCED-v0",
        notes="V1 and V2 India cost schedules stay selectable; brokerage/BSE/GST-base gaps remain open.",
    ),
}


def lane_spec(lane: MarketLane) -> LaneSpec:
    if not isinstance(lane, MarketLane):
        raise ValueError(f"unknown market lane: {lane!r}")
    return LANE_SPECS[lane]
