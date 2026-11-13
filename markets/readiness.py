"""Per-lane readiness gating (Slice 13 §4.2, §4.4, §5). ONE LANE AT A TIME.

Readiness is computed from verification records that are supplied per lane. No function here accepts
two lanes, so a verified US source can never make the Indian lane look complete (and vice versa).
Nothing in this module performs network I/O: status is `VERIFIED` only when a human-supplied record
cites a primary source and an access date for every required check. This slice shipped NO such record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from markets.lane import MarketLane


class VerificationStatus(str, Enum):  # noqa: UP042
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"  # no candidate exists
    REJECTED = "REJECTED"


class LaneStatus(str, Enum):  # noqa: UP042
    OPERATIONAL = "OPERATIONAL"
    ENGINEERING_ONLY = "ENGINEERING_ONLY"
    BLOCKED = "BLOCKED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class BranchStatus(str, Enum):  # noqa: UP042
    AVAILABLE = "AVAILABLE"
    MOCK_ONLY = "MOCK_ONLY"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    BLOCKED = "BLOCKED"


REQUIRED_SOURCE_CHECKS = (
    "account_entitlement", "realtime_or_delayed_status", "timestamp_semantics", "delivery_latency",
    "symbol_coverage", "corporate_action_handling", "symbol_change_handling", "outage_behaviour",
    "data_use_rights", "storage_retention_rights", "derived_data_rights", "ai_processing_rights",
    "cost",
)  # fmt: skip

REQUIRED_PLATFORM_CHECKS = (
    "paper_only_account_eligibility", "dedicated_paper_credentials", "official_paper_endpoint",
    "supported_symbols", "supported_order_types", "rate_limits", "order_lifecycle_semantics",
    "partial_fill_behaviour", "rejection_semantics", "cancellation", "status_read_back",
    "idempotency_limits", "usage_terms", "automated_trading_permission",
)  # fmt: skip


@dataclass(frozen=True)
class CheckResult:
    status: VerificationStatus
    primary_source_ref: str | None = None  # URL/doc id of a PRIMARY source
    accessed_on: str | None = None  # ISO date the source was read
    note: str = ""

    def counts_as_verified(self) -> bool:
        return (
            self.status is VerificationStatus.VERIFIED
            and bool(self.primary_source_ref)
            and bool(self.accessed_on)
        )


@dataclass(frozen=True)
class SourceVerification:
    lane: MarketLane
    provider: str
    product: str
    candidate_note: str
    checks: dict[str, CheckResult] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()

    @property
    def status(self) -> VerificationStatus:
        if self.provider == "NONE":
            return VerificationStatus.NOT_ESTABLISHED
        if any(c.status is VerificationStatus.REJECTED for c in self.checks.values()):
            return VerificationStatus.REJECTED
        ok = all(
            name in self.checks and self.checks[name].counts_as_verified()
            for name in REQUIRED_SOURCE_CHECKS
        )
        return VerificationStatus.VERIFIED if ok else VerificationStatus.UNVERIFIED

    def unverified_checks(self) -> tuple[str, ...]:
        return tuple(
            n for n in REQUIRED_SOURCE_CHECKS
            if n not in self.checks or not self.checks[n].counts_as_verified()
        )  # fmt: skip


@dataclass(frozen=True)
class ExternalPlatformVerification:
    lane: MarketLane
    platform: str  # "NONE" when no eligible platform was identified
    candidate_note: str
    checks: dict[str, CheckResult] = field(default_factory=dict)
    credentials_configured: bool = False  # set only by the operator's secure environment
    prohibited_reason: str | None = None

    @property
    def status(self) -> VerificationStatus:
        if self.platform == "NONE":
            return VerificationStatus.NOT_ESTABLISHED
        if self.prohibited_reason:
            return VerificationStatus.REJECTED
        ok = all(
            n in self.checks and self.checks[n].counts_as_verified() for n in REQUIRED_PLATFORM_CHECKS
        )
        return VerificationStatus.VERIFIED if ok else VerificationStatus.UNVERIFIED


@dataclass(frozen=True)
class LaneReadiness:
    lane: MarketLane
    data_status: LaneStatus
    internal_execution_status: LaneStatus
    external_branch_status: BranchStatus
    overall: LaneStatus
    reasons: tuple[str, ...]


def compute_lane_readiness(
    lane: MarketLane,
    source: SourceVerification,
    platform: ExternalPlatformVerification,
    *,
    internal_execution_integrated: bool,
    cost_schedule_fully_verified: bool,
    mock_external_available: bool = True,
) -> LaneReadiness:
    if source.lane is not lane or platform.lane is not lane:
        raise ValueError("verification records must belong to the lane being assessed")
    reasons: list[str] = []

    sv = source.status
    if sv is VerificationStatus.VERIFIED:
        data = LaneStatus.OPERATIONAL
    elif sv is VerificationStatus.NOT_ESTABLISHED:
        data = LaneStatus.BLOCKED
        reasons.append("no eligible market-data source established")
    else:
        data = LaneStatus.ENGINEERING_ONLY
        reasons.append(f"market-data source {sv.value}; unverified checks: {list(source.unverified_checks())}")

    if not internal_execution_integrated:
        internal = LaneStatus.BLOCKED
        reasons.append("internal simulated execution path is not integrated for this lane's costs")
    elif not cost_schedule_fully_verified:
        internal = LaneStatus.ENGINEERING_ONLY
        reasons.append("cost schedule not fully verified")
    else:
        internal = LaneStatus.OPERATIONAL

    pv = platform.status
    if pv is VerificationStatus.VERIFIED and platform.credentials_configured:
        ext = BranchStatus.AVAILABLE
    elif pv is VerificationStatus.REJECTED or pv is VerificationStatus.NOT_ESTABLISHED:
        ext = BranchStatus.BLOCKED
        reasons.append(f"external paper platform {pv.value}")
    elif mock_external_available:
        ext = BranchStatus.MOCK_ONLY
        reasons.append("external platform unverified/unconfigured: mock contract only, NOT platform integration")
    else:
        ext = BranchStatus.NOT_CONFIGURED

    order = [LaneStatus.BLOCKED, LaneStatus.NOT_CONFIGURED, LaneStatus.ENGINEERING_ONLY, LaneStatus.OPERATIONAL]
    overall = min(data, internal, key=order.index)
    return LaneReadiness(lane, data, internal, ext, overall, tuple(reasons))


def default_source_verification(lane: MarketLane) -> SourceVerification:
    if lane is MarketLane.US_EQUITIES:
        return SourceVerification(
            lane, "ALPACA_CANDIDATE", "market-data (IEX-entitled paper account — to be confirmed)",
            "Candidate only. A paper account's documented IEX entitlement is NOT complete US market "
            "coverage. No entitlement, coverage, timestamp, latency or data-rights check was verified "
            "in this slice (no network access).",
            limitations=("IEX-only coverage must not be treated as the whole US market",
                         "a second independent source may be needed for outcome verification"),
        )  # fmt: skip
    return SourceVerification(
        lane, "NONE", "none",
        "No Indian market-data source has been verified for algorithmic/AI research, paper trading, "
        "storage or outcome evaluation. Lane stays BLOCKED/ENGINEERING_ONLY.",
        limitations=("synthetic/replay engineering tests only",),
    )  # fmt: skip


def default_external_verification(lane: MarketLane) -> ExternalPlatformVerification:
    if lane is MarketLane.US_EQUITIES:
        return ExternalPlatformVerification(
            lane, "ALPACA_PAPER_CANDIDATE",
            "Candidate, not pre-approved. Account eligibility, credentials, endpoint, limits and terms "
            "were not verified here. Known documented limits to record: no market-impact modelling, no "
            "latency slippage, no queue position, no regulatory fees, no dividends, displayed liquidity "
            "not enforced as a fill cap, partial fills follow simulation assumptions.",
        )  # fmt: skip
    return ExternalPlatformVerification(
        lane, "NONE",
        "No Indian external paper platform is approved. Browser simulators/scrapers do not qualify; the "
        "NSE Test Market Facility is for members/vendors and is not assumed to be a personal paper API.",
    )  # fmt: skip
