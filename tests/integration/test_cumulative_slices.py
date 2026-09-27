"""Cross-slice contracts: ingestion, persistence, context, candidates and pure costs."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from data.adapters.nse_bhavcopy_csv import load_bhavcopy_csv
from data.features.context_builder import (
    build_feature_snapshots,
    compute_market_data_snapshot_version,
)
from data.features.universe import make_permitted_universe
from data.normalization.persistence import read_market_data_jsonl, write_market_data_jsonl
from data.normalization.pipeline import normalize_bhavcopy_batch
from domain.models import CandidateTrade, FeatureSnapshot
from domain.models.serialization import from_serializable, to_serializable
from domain.models.trade import CandidateTrade as Slice3Candidate
from intelligence.baseline.tier1_equal_weight import Tier1EqualWeightBuyHold
from shared.costs import CostInputs, CostModel, TradeType, TransactionSide


def test_ingestion_to_candidates_and_costs(tmp_path):
    raw = load_bhavcopy_csv(Path(__file__).parents[1] / "fixtures/historical_data/valid_sample.csv")
    normalized = normalize_bhavcopy_batch(raw.observations, raw_source_hash=raw.raw_source_hash)
    path = tmp_path / "market.jsonl"
    write_market_data_jsonl(normalized.accepted, path)
    records = list(read_market_data_jsonl(path))
    assert tuple(records) == tuple(sorted(normalized.accepted, key=lambda r: r.identity_key))
    as_of = max(r.timestamp for r in records)
    universe = make_permitted_universe([i.isin for i in normalized.instruments], as_of)
    snapshots = build_feature_snapshots(records, universe, as_of)
    candidates = Tier1EqualWeightBuyHold().generate_candidate_trades(snapshots, universe, None)
    assert Slice3Candidate is CandidateTrade
    assert len(candidates) == len(universe.instrument_ids)
    for snapshot, candidate in zip(snapshots, candidates, strict=True):
        assert isinstance(candidate, CandidateTrade)
        assert candidate.input_snapshot_id == snapshot.snapshot_id
        assert from_serializable(FeatureSnapshot, to_serializable(snapshot)) == snapshot
        assert from_serializable(CandidateTrade, to_serializable(candidate)) == candidate
        # Explicit hypothetical quantity for the pure calculator, never derived from size_hint.
        inputs = CostInputs(
            TransactionSide.BUY,
            TradeType.DELIVERY,
            10,
            Decimal(str(snapshot.reference_price)),
            "india-equity-v1-unverified",
        )
        estimate = CostModel().estimate(inputs)
        assert estimate.total_cost == estimate.component_total()
        assert estimate == CostModel().estimate(inputs)


def test_data_provenance_changes_context_version():
    raw = load_bhavcopy_csv(Path(__file__).parents[1] / "fixtures/historical_data/valid_sample.csv")
    record = normalize_bhavcopy_batch(
        raw.observations, raw_source_hash=raw.raw_source_hash
    ).accepted[0]
    corrected = replace(record, data_snapshot_version="corrected-source")
    assert compute_market_data_snapshot_version([record]) != compute_market_data_snapshot_version(
        [corrected]
    )


def test_snapshot_copies_mapping_proxy():
    from types import MappingProxyType

    values = {"close": 100.0}
    snapshot = FeatureSnapshot(
        "X", datetime(2024, 1, 1, tzinfo=UTC), MappingProxyType(values), "v1"
    )
    values["close"] = 200.0
    assert snapshot.value("close") == 100.0
