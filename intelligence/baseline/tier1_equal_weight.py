"""Tier-1 baseline strategy: naive equal-weight buy-and-hold.

Stage 3 §12 (Tier 1), Slice 3 spec §8-§10.

Hypothesis / role: this is the DeMiguel-et-al.-standard naive-static
floor (Stage 0 02 §3.1, §9) that every later Plane 2 candidate must
clear via ER-1 comparison — it is not a claim that buy-and-hold is
expected to be profitable after costs, only the minimal, zero-parameter
comparator required to detect illusory sophistication.

Behavior (Slice 3 spec §10):
  - Initial universe: BUY every permitted instrument, equal-weighted.
  - No universe change: HOLD every existing constituent.
  - Instrument added: existing constituents HOLD; the new instrument BUYs.
  - Instrument removed: remaining constituents HOLD; the removed
    instrument SELLs (full exit, target allocation 0).
  - Missing/stale data for a permitted instrument: HOLD with confidence
    0.0 and an explicit rationale (SF-1/SF-2), never silently rebalanced
    around.

This module produces ONLY CandidateTrade objects. It has no access to
data/adapters, no network access, no broker credentials, and no
knowledge of position sizing arithmetic (Stage 3 §3.2/§8) — `size_hint`
here is a normalized ALLOCATION HINT (a fraction of the portfolio, e.g.
0.25 for a 4-instrument equal-weight book), never an executable
share/rupee quantity. Converting that hint into an actual order
quantity is exclusively Plane 3's job (Slice 6+), per TR-3.
"""

from __future__ import annotations

from datetime import datetime

from data.features.universe import PermittedUniverse
from domain.models.enums import Action
from domain.models.feature_snapshot import FeatureSnapshot
from domain.models.trade import CandidateTrade
from shared.versioning.versioning import content_hash

STRATEGY_VERSION_ID = "tier1_equal_weight_buy_hold_v1"


class Tier1EqualWeightBuyHold:
    """Deterministic, stateless (per-call) implementation of the Tier-1
    baseline. All state a call needs (current universe, previous
    universe) is passed in explicitly — no hidden mutable state, per
    Slice 3 spec §15 ("Decision Provenance")."""

    strategy_version_id = STRATEGY_VERSION_ID

    def generate_candidate_trades(
        self,
        snapshots: list[FeatureSnapshot],
        universe: PermittedUniverse,
        previous_universe: PermittedUniverse | None,
    ) -> list[CandidateTrade]:
        if not isinstance(universe, PermittedUniverse):
            raise ValueError("Tier1EqualWeightBuyHold: universe must be a PermittedUniverse")
        if not universe.instrument_ids:
            raise ValueError("Tier1EqualWeightBuyHold: permitted universe must not be empty")

        by_instrument: dict[str, FeatureSnapshot] = {}
        for snap in snapshots:
            if not isinstance(snap, FeatureSnapshot):
                raise ValueError(
                    "Tier1EqualWeightBuyHold: all snapshots must be FeatureSnapshot instances"
                )
            by_instrument[snap.instrument_id] = snap

        as_of: datetime | None = None
        for snap in snapshots:
            if as_of is None:
                as_of = snap.decision_timestamp
            elif snap.decision_timestamp != as_of:
                raise ValueError(
                    "Tier1EqualWeightBuyHold: all snapshots in one cycle must share the "
                    "same decision_timestamp; got a mix, which would make 'as of when' "
                    "for the resulting CandidateTrades ambiguous."
                )
        if as_of is None:
            as_of = universe.effective_from

        added, removed = universe.diff(previous_universe)
        n = len(universe.instrument_ids)
        equal_weight = 1.0 / n

        candidates: list[CandidateTrade] = []

        for instrument_id in sorted(universe.instrument_ids):
            snapshot = by_instrument.get(instrument_id)
            if snapshot is None:
                raise ValueError(
                    f"Tier1EqualWeightBuyHold: no FeatureSnapshot supplied for permitted "
                    f"instrument {instrument_id!r}; every permitted instrument must have "
                    f"an accompanying snapshot, even an incomplete one (SF-1)."
                )
            candidates.append(
                self._candidate_for_permitted_instrument(
                    snapshot,
                    instrument_id,
                    is_new=instrument_id in added,
                    equal_weight=equal_weight,
                )
            )

        for instrument_id in sorted(removed):
            snapshot = by_instrument.get(instrument_id)
            if snapshot is None:
                raise ValueError(
                    f"Tier1EqualWeightBuyHold: instrument {instrument_id!r} was removed from "
                    f"the permitted universe but no FeatureSnapshot was supplied for it; a "
                    f"snapshot (with is_permitted=False) is required to produce an "
                    f"attributable exit decision (RR-7). Build one via "
                    f"data.features.context_builder.build_feature_snapshots(..., "
                    f"instrument_ids=<current | removed>)."
                )
            candidates.append(self._candidate_for_removed_instrument(snapshot, instrument_id))

        return candidates

    def _candidate_for_permitted_instrument(
        self, snapshot: FeatureSnapshot, instrument_id: str, is_new: bool, equal_weight: float
    ) -> CandidateTrade:
        if not snapshot.is_complete:
            return self._hold_missing_data(snapshot, instrument_id)

        if is_new:
            action = Action.BUY
            rationale = (
                f"Tier-1 baseline ({STRATEGY_VERSION_ID}): initial allocation into permitted "
                f"universe. Equal-weight target allocation = {equal_weight:.6f} "
                f"(1 / current universe size)."
            )
        else:
            action = Action.HOLD
            rationale = (
                f"Tier-1 baseline ({STRATEGY_VERSION_ID}): permitted universe unchanged for "
                f"this instrument; continuing to hold. Equal-weight target allocation = "
                f"{equal_weight:.6f} (unchanged)."
            )

        return CandidateTrade(
            candidate_id=self._deterministic_candidate_id(snapshot, action),
            instrument_id=instrument_id,
            timestamp=snapshot.decision_timestamp,
            action=action,
            size_hint=equal_weight,
            confidence=1.0,
            uncertainty_band=None,
            rationale=rationale,
            input_snapshot_id=snapshot.snapshot_id,
            strategy_version_id=STRATEGY_VERSION_ID,
            model_version_id=None,
        )

    def _candidate_for_removed_instrument(
        self, snapshot: FeatureSnapshot, instrument_id: str
    ) -> CandidateTrade:
        rationale = (
            f"Tier-1 baseline ({STRATEGY_VERSION_ID}): instrument removed from permitted "
            f"universe (TR-1/TR-7); exiting position. Target allocation = 0.0."
        )
        return CandidateTrade(
            candidate_id=self._deterministic_candidate_id(snapshot, Action.SELL),
            instrument_id=instrument_id,
            timestamp=snapshot.decision_timestamp,
            action=Action.SELL,
            size_hint=0.0,
            confidence=1.0,
            uncertainty_band=None,
            rationale=rationale,
            input_snapshot_id=snapshot.snapshot_id,
            strategy_version_id=STRATEGY_VERSION_ID,
            model_version_id=None,
        )

    def _hold_missing_data(self, snapshot: FeatureSnapshot, instrument_id: str) -> CandidateTrade:
        rationale = (
            f"Tier-1 baseline ({STRATEGY_VERSION_ID}): market data for {instrument_id} is "
            f"missing or stale as of {snapshot.decision_timestamp.isoformat()}; holding "
            f"pending valid data rather than acting on an incomplete snapshot (SF-1/SF-2)."
        )
        return CandidateTrade(
            candidate_id=self._deterministic_candidate_id(snapshot, Action.HOLD),
            instrument_id=instrument_id,
            timestamp=snapshot.decision_timestamp,
            action=Action.HOLD,
            size_hint=None,
            confidence=0.0,
            uncertainty_band=None,
            rationale=rationale,
            input_snapshot_id=snapshot.snapshot_id,
            strategy_version_id=STRATEGY_VERSION_ID,
            model_version_id=None,
        )

    @staticmethod
    def _deterministic_candidate_id(snapshot: FeatureSnapshot, action: Action):
        from uuid import UUID

        digest = content_hash((snapshot.snapshot_id, STRATEGY_VERSION_ID, action.value))
        # Deterministic UUID derived from the content hash (valid UUID4-shaped hex string).
        padded = (digest * 2)[:32]
        return str(UUID(padded))
