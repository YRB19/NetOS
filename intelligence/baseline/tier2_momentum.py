"""Tier-2 baseline strategy: 12-1 month price momentum, monthly rebalance (Slice 6).

Stage 3 §12 (Tier 2) / ADR-7. A DETERMINISTIC research baseline — not an AI
strategy, and not a claim that momentum is profitable after costs.

Behaviour per decision cycle (all state arrives via FeatureSnapshots):
  * Not a rebalance date (`is_rebalance_date` == 0)      -> HOLD every permitted instrument.
  * Rebalance flag unavailable                           -> HOLD (fail safe, explicit rationale).
  * Rebalance date: eligible = permitted AND complete snapshot AND momentum present.
      - rank eligible by momentum DESC, ties broken by instrument_id ASC (stable, no randomness)
      - k = max(1, ceil(selection_fraction * n_eligible)); never zero when n_eligible >= 1
      - top-k  -> BUY, size_hint = 1/k (equal-weight target fraction of equity)
      - rest   -> SELL, size_hint = 0.0 (target allocation 0)
      - permitted but momentum missing / incomplete snapshot -> HOLD (never liquidated on missing data)
      - zero eligible -> HOLD all, with an explicit rationale.
  * Instrument removed from the permitted universe -> SELL (exit), any date.

The strategy emits ONLY CandidateTrade objects. `size_hint` is a target-weight
hint, never a share/rupee quantity; sizing is Plane 3's job (TR-3). It imports no
risk, sizing, broker, research or adapter code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from data.features.momentum import (
    FEATURE_MOMENTUM,
    FEATURE_REBALANCE,
    MomentumConfig,
    momentum_feature_set_id,
)
from data.features.universe import PermittedUniverse
from domain.models.enums import Action
from domain.models.feature_snapshot import FeatureSnapshot
from domain.models.trade import CandidateTrade
from domain.models.versions import Plane2Type, StrategyVersion
from shared.versioning.versioning import content_hash, make_version_id

STRATEGY_LABEL = "tier2_momentum_12_1_v1"
TOP_DECILE = 0.10
TOP_QUINTILE = 0.20


@dataclass(frozen=True)
class Tier2MomentumConfig:
    selection_fraction: float
    features: MomentumConfig = field(default_factory=MomentumConfig)

    def validate(self) -> list[str]:
        errs = list(self.features.validate())
        f = self.selection_fraction
        if isinstance(f, bool) or not isinstance(f, (int, float)):
            errs.append(f"selection_fraction must be a number, got {f!r}")
        elif not (math.isfinite(f) and 0.0 < f <= 1.0):
            errs.append(f"selection_fraction must be in (0, 1], got {f!r}")
        return errs

    def payload(self) -> dict:
        return {"selection_fraction": self.selection_fraction, **self.features.payload(),
                "ranking": "momentum desc, instrument_id asc",
                "rebalance": "first observation timestamp of each calendar month"}  # fmt: skip


def selected_count(n_eligible: int, fraction: float) -> int:
    """k = max(1, ceil(fraction * n)) using exact decimal arithmetic (no float fuzz)."""
    if n_eligible <= 0:
        return 0
    return max(1, math.ceil(Decimal(str(fraction)) * n_eligible))


class Tier2Momentum12_1:  # noqa: N801 - name mirrors the strategy label
    def __init__(self, config: Tier2MomentumConfig) -> None:
        errs = config.validate()
        if errs:
            raise ValueError("invalid Tier2MomentumConfig: " + "; ".join(errs))
        self.config = config
        self.strategy_version_id = make_version_id(STRATEGY_LABEL, config.payload())
        self.expected_feature_set_id = momentum_feature_set_id(config.features)

    def strategy_version(self) -> StrategyVersion:
        """Domain StrategyVersion record for this exact configuration."""
        return StrategyVersion(
            plane2_type=Plane2Type.BASELINE,
            code_or_config_hash=self.strategy_version_id,
            version_id=self.strategy_version_id,
        )

    # ------------------------------------------------------------------ API
    def generate_candidate_trades(
        self,
        snapshots: list[FeatureSnapshot],
        universe: PermittedUniverse,
        previous_universe: PermittedUniverse | None,
    ) -> list[CandidateTrade]:
        if not isinstance(universe, PermittedUniverse):
            raise ValueError("Tier2Momentum: universe must be a PermittedUniverse")
        if not universe.instrument_ids:
            raise ValueError("Tier2Momentum: permitted universe must not be empty")
        by_inst: dict[str, FeatureSnapshot] = {}
        as_of: datetime | None = None
        for s in snapshots:
            if not isinstance(s, FeatureSnapshot):
                raise ValueError("Tier2Momentum: all snapshots must be FeatureSnapshot instances")
            if s.feature_set_version != self.expected_feature_set_id:
                raise ValueError(
                    f"Tier2Momentum: snapshot for {s.instrument_id!r} was built with feature set "
                    f"{s.feature_set_version!r}, expected {self.expected_feature_set_id!r}"
                )
            if as_of is None:
                as_of = s.decision_timestamp
            elif s.decision_timestamp != as_of:
                raise ValueError("Tier2Momentum: snapshots must share one decision_timestamp")
            by_inst[s.instrument_id] = s

        permitted = sorted(universe.instrument_ids)
        for i in permitted:
            if i not in by_inst:
                raise ValueError(f"Tier2Momentum: no FeatureSnapshot for permitted instrument {i!r}")
        _added, removed = universe.diff(previous_universe)
        for i in sorted(removed):
            if i not in by_inst:
                raise ValueError(f"Tier2Momentum: no FeatureSnapshot for removed instrument {i!r}")

        flag = next(
            (by_inst[i].feature_values.get(FEATURE_REBALANCE) for i in permitted
             if FEATURE_REBALANCE in by_inst[i].feature_values), None)  # fmt: skip
        out: list[CandidateTrade] = []

        if flag is None:
            out += [self._hold(by_inst[i], "rebalance flag unavailable; holding (fail safe)", 0.0)
                    for i in permitted]  # fmt: skip
        elif flag != 1.0:
            out += [self._hold(by_inst[i], "not a monthly rebalance date; no trade", 1.0)
                    for i in permitted]  # fmt: skip
        else:
            out += self._rebalance(by_inst, permitted)

        out += [self._exit(by_inst[i]) for i in sorted(removed)]
        return out

    # ------------------------------------------------------------ internals
    def _rebalance(self, by_inst: dict[str, FeatureSnapshot], permitted: list[str]):
        eligible: list[tuple[str, float]] = []
        others: list[tuple[FeatureSnapshot, str]] = []
        for i in permitted:
            s = by_inst[i]
            if not s.is_complete:
                others.append((s, "market data missing/stale (SF-1/SF-2); holding"))
            elif FEATURE_MOMENTUM not in s.feature_values:
                others.append((s, "momentum unavailable (insufficient/stale history); holding"))
            else:
                eligible.append((i, float(s.feature_values[FEATURE_MOMENTUM])))
        out = [self._hold(s, why, 0.0) for s, why in others]
        n = len(eligible)
        if n == 0:
            return out
        ranked = sorted(eligible, key=lambda x: (-x[1], x[0]))  # momentum desc, id asc
        k = selected_count(n, self.config.selection_fraction)
        for rank, (i, mom) in enumerate(ranked, start=1):
            s = by_inst[i]
            conf = 1.0 - (rank - 1) / n
            base = (
                f"Tier-2 ({STRATEGY_LABEL}) rebalance: momentum(12-1)={mom:.6f}, rank {rank}/{n}, "
                f"select top {k} (fraction {self.config.selection_fraction})."
            )
            if rank <= k:
                out.append(self._cand(s, Action.BUY, 1.0 / k, conf,
                                      base + f" SELECTED: equal-weight target {1.0 / k:.6f}."))  # fmt: skip
            else:
                out.append(self._cand(s, Action.SELL, 0.0, conf,
                                      base + " NOT selected: target allocation 0.0."))  # fmt: skip
        return out

    def _hold(self, s: FeatureSnapshot, why: str, conf: float) -> CandidateTrade:
        return self._cand(s, Action.HOLD, None, conf, f"Tier-2 ({STRATEGY_LABEL}): {why}.")

    def _exit(self, s: FeatureSnapshot) -> CandidateTrade:
        return self._cand(s, Action.SELL, 0.0, 1.0,
                          f"Tier-2 ({STRATEGY_LABEL}): instrument removed from permitted universe; exit.")  # fmt: skip

    def _cand(self, s, action, hint, conf, rationale) -> CandidateTrade:
        digest = content_hash([s.snapshot_id, self.strategy_version_id, action.value])
        return CandidateTrade(
            candidate_id=str(UUID((digest * 2)[:32])),
            instrument_id=s.instrument_id,
            timestamp=s.decision_timestamp,
            action=action,
            size_hint=hint,
            confidence=conf,
            uncertainty_band=None,
            rationale=rationale,
            input_snapshot_id=s.snapshot_id,
            strategy_version_id=self.strategy_version_id,
            model_version_id=None,
        )
