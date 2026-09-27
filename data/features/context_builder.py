"""Feature/context formation. Slice 3 spec §3-§7.

Transforms canonical MarketData + the permitted universe into the
immutable FeatureSnapshot objects that are the ONLY thing the
intelligence layer (Plane 2) is allowed to consume (Stage 3 §3.1).
This module is Plane 1's responsibility; nothing in intelligence/ may
import data/adapters or data/normalization directly — only this
module's output type (enforced by the import-graph lint, tools/).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from data.features.feature_sets import TIER1_CONTEXT_FEATURE_SET_ID
from data.features.universe import PermittedUniverse
from data.validation.validators import is_stale
from domain.models.feature_snapshot import FeatureSnapshot, MarketDataRef
from domain.models.market_data import MarketData
from shared.time.clock import is_utc
from shared.versioning.versioning import content_hash

DEFAULT_STALENESS_THRESHOLD = timedelta(days=5)  # generous default for daily-bar equities data


def compute_market_data_snapshot_version(market_data: list[MarketData]) -> str:
    """Deterministic version identifier for a set of MarketData records
    used to build a batch of snapshots. Same records (regardless of
    order) -> same version (Slice 3 spec §6 determinism requirement)."""
    keys = sorted(
        (
            md.instrument_id,
            md.timestamp.isoformat(),
            md.source,
            md.ingestion_time.isoformat(),
            md.open,
            md.high,
            md.low,
            md.close,
            md.volume,
            md.data_snapshot_version,
            md.adjusted,
            md.raw_ref or "",
        )
        for md in market_data
    )
    return content_hash(keys)


def _latest_as_of(records: list[MarketData], as_of: datetime) -> MarketData | None:
    """Latest record with timestamp <= as_of, or None. Deterministic:
    ties broken by (timestamp, then insertion order via stable sort)."""
    eligible = [r for r in records if r.timestamp <= as_of]
    if not eligible:
        return None
    return max(eligible, key=lambda r: r.timestamp)


def build_feature_snapshots(
    market_data: list[MarketData],
    universe: PermittedUniverse,
    as_of: datetime,
    market_data_snapshot_version: str | None = None,
    feature_set_id: str = TIER1_CONTEXT_FEATURE_SET_ID,
    staleness_threshold: timedelta = DEFAULT_STALENESS_THRESHOLD,
    instrument_ids: Iterable[str] | None = None,
) -> list[FeatureSnapshot]:
    """Build one FeatureSnapshot per target instrument, as of `as_of`.
    Deterministic given identical inputs (Slice 3 spec §6): no
    randomness, no wall-clock reads, no network calls, no hidden state.

    `instrument_ids` defaults to the permitted universe. It may be
    widened (e.g. to include an instrument just REMOVED from the
    universe, so a strategy can still produce an attributable exit
    decision for it, per RR-7) — is_permitted is computed per instrument
    against `universe` regardless of which set was requested, so a
    caller can never accidentally mark a non-permitted instrument as
    permitted by including it here.

    An instrument with no MarketData at or before `as_of`, or whose
    latest record is stale relative to `staleness_threshold`, gets an
    INCOMPLETE snapshot (reference_price=None) rather than being silently
    skipped (Slice 3 spec §16 tests 8/9; Stage 3 §5 SF-1/SF-2) — SF-2
    staleness is explicitly routed through the same "treat as missing"
    path as SF-1, per Stage 3 §5.
    """
    if not is_utc(as_of):
        raise ValueError("build_feature_snapshots: as_of must be timezone-aware UTC")
    if not isinstance(universe, PermittedUniverse):
        raise ValueError("build_feature_snapshots: universe must be a PermittedUniverse")

    if market_data_snapshot_version is None:
        market_data_snapshot_version = compute_market_data_snapshot_version(market_data)

    target_ids = (
        sorted(instrument_ids) if instrument_ids is not None else sorted(universe.instrument_ids)
    )

    by_instrument: dict[str, list[MarketData]] = {}
    for record in market_data:
        by_instrument.setdefault(record.instrument_id, []).append(record)

    snapshots: list[FeatureSnapshot] = []
    for instrument_id in target_ids:
        is_permitted = universe.contains(instrument_id)
        records = by_instrument.get(instrument_id, [])
        latest = _latest_as_of(records, as_of)

        if latest is None:
            # SF-1: missing data. Construct an incomplete, auditable snapshot.
            snapshot_id = content_hash(
                (
                    "MISSING",
                    instrument_id,
                    as_of.isoformat(),
                    feature_set_id,
                    universe.version,
                    market_data_snapshot_version,
                )
            )
            snapshots.append(
                FeatureSnapshot(
                    snapshot_id=snapshot_id,
                    instrument_id=instrument_id,
                    decision_timestamp=as_of,
                    feature_set_version=feature_set_id,
                    universe_version=universe.version,
                    data_snapshot_version=market_data_snapshot_version,
                    is_permitted=is_permitted,
                    reference_price=None,
                    incomplete=True,
                    missing_fields=("reference_price",),
                    source_refs=(),
                    feature_values={},
                )
            )
            continue

        if is_stale(latest.timestamp, as_of, staleness_threshold):
            # SF-2: stale data treated as missing, not as current (Stage 3 §5).
            snapshot_id = content_hash(
                (
                    "STALE",
                    instrument_id,
                    as_of.isoformat(),
                    feature_set_id,
                    universe.version,
                    market_data_snapshot_version,
                )
            )
            snapshots.append(
                FeatureSnapshot(
                    snapshot_id=snapshot_id,
                    instrument_id=instrument_id,
                    decision_timestamp=as_of,
                    feature_set_version=feature_set_id,
                    universe_version=universe.version,
                    data_snapshot_version=market_data_snapshot_version,
                    is_permitted=is_permitted,
                    reference_price=None,
                    incomplete=True,
                    missing_fields=("reference_price",),
                    source_refs=(),
                    feature_values={},
                )
            )
            continue

        snapshot_id = content_hash(
            (
                "OK",
                instrument_id,
                as_of.isoformat(),
                feature_set_id,
                universe.version,
                market_data_snapshot_version,
                latest.close,
            )
        )
        snapshots.append(
            FeatureSnapshot(
                snapshot_id=snapshot_id,
                instrument_id=instrument_id,
                decision_timestamp=as_of,
                feature_set_version=feature_set_id,
                universe_version=universe.version,
                data_snapshot_version=market_data_snapshot_version,
                is_permitted=is_permitted,
                reference_price=latest.close,
                source_refs=(
                    MarketDataRef(
                        instrument_id=instrument_id,
                        timestamp=latest.timestamp,
                        source=latest.source,
                    ),
                ),
                feature_values={},
            )
        )

    return snapshots
