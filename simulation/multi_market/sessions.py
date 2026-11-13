"""Session matrix: 2 lanes x 2 tiers x 2 execution branches = 8 sessions, each with its own identity."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from markets.lane import LANE_SPECS, MarketLane
from markets.readiness import BranchStatus, LaneReadiness
from shared.versioning.content_hash import hash_json_stable


class Tier(str, Enum):  # noqa: UP042
    TIER1 = "TIER1_EQUAL_WEIGHT"
    TIER2 = "TIER2_MOMENTUM_12_1"


class Branch(str, Enum):  # noqa: UP042
    INTERNAL = "NETOS_INTERNAL_SIMULATOR"
    EXTERNAL = "EXTERNAL_PAPER_PLATFORM"


@dataclass(frozen=True)
class SessionDefinition:
    lane: MarketLane
    tier: Tier
    branch: Branch
    session_id: str
    experiment_id: str
    strategy_config_id: str
    currency: str
    benchmark_id: str
    cost_schedule_id: str
    status: str
    reasons: tuple[str, ...]


def build_session_matrix(readiness: dict[MarketLane, LaneReadiness]) -> list[SessionDefinition]:
    out: list[SessionDefinition] = []
    for lane in MarketLane:
        spec, rd = LANE_SPECS[lane], readiness[lane]
        for tier in Tier:
            cfg = spec.tier1_config_id if tier is Tier.TIER1 else spec.tier2_config_id
            for br in Branch:
                key = {"lane": lane.value, "tier": tier.value, "branch": br.value, "cfg": cfg, "spec": spec.identity()}
                h = hash_json_stable(key)[:16]
                if br is Branch.INTERNAL:
                    status, reasons = rd.internal_execution_status.value, tuple(
                        r for r in rd.reasons if "internal" in r or "cost" in r)  # fmt: skip
                else:
                    status = rd.external_branch_status.value
                    reasons = tuple(r for r in rd.reasons if "external" in r)
                out.append(SessionDefinition(lane, tier, br, f"sess_{lane.value}_{h}", f"exp_{lane.value}_{h}",
                                             cfg, spec.currency, spec.benchmark_id, spec.cost_schedule_id,
                                             status, reasons))  # fmt: skip
    return out


_ = BranchStatus  # re-exported for callers
