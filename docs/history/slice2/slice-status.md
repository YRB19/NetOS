# Slice Status

Tracks completion state of the Stage 3 §21 implementation sequence.

## Important note on this session's starting state

This session began in a **fresh sandbox with no pre-existing repository**. The prior session's
reported state ("Slice 0 and Slice 1 complete, 112 tests passing") could not be found on disk,
in any mounted directory, or anywhere else searched. Rather than fabricate a continuation from
an artifact that does not exist in this environment, this session:

1. Rebuilt the **minimum** Slice 0/Slice 1 foundation that Slice 2 actually depends on
   (repository scaffold per Stage 3 §1, the import-graph lint mechanism per ADR-6, and the
   `Instrument`/`MarketData`/`RawMarketObservation` domain models per Stage 3 §2).
2. Did **not** reconstruct the full ~20-object domain model from Stage 3 §2 (CandidateTrade,
   RiskDecision, Order, DecisionRecord, the versioning/experiment objects, etc.) — those belong
   to Plane 2/3/4 and the Research environment, which are out of scope for Slice 2's historical
   data-ingestion objective, and building them now would be scope creep into later slices, which
   the Slice 2 brief explicitly prohibits ("Do not implement Slice 3 or anything beyond it").
3. Then built Slice 2 (historical data ingestion) in full, per this document's status table.

**Consequence for the "112 tests" baseline referenced in the Slice 2 brief:** that number
cannot be honestly reconciled with what actually exists in this sandbox. The test count
reported for this session (see below) is a fresh count for what was actually built and
actually run, not a continuation of a number this session could not verify.

## Status table

| Slice | Status | Notes |
|---|---|---|
| Slice 0 — Repository scaffolding + import-graph lint | **Reconstructed (minimal)** | Full plane directory structure per Stage 3 §1; ADR-6 import-graph check implemented and tested (`scripts/check_import_graph.py`, `tests/adversarial/test_import_graph_isolation.py`) |
| Slice 1 — Core domain models | **Reconstructed (scoped to Slice 2's needs)** | `Instrument`, `MarketData`, `RawMarketObservation` implemented per Stage 3 §2 field contracts, with required-field/immutability enforcement and unit tests. The remaining Stage 3 §2 domain objects are deferred — see note above |
| **Slice 2 — Historical data ingestion** | **Complete** | See `docs/data-ingestion.md` for full detail |
| Slice 3 — Feature/context formation + Tier-1 baseline | Not started | Recommended next slice |
| Slice 4+ | Not started | — |

## Slice 2 — what was built

- One historical-data adapter: `data/adapters/nse_bhavcopy_csv.py` (NSE-bhavcopy-format CSV)
- Raw-data preservation: `domain/models/raw_observation.py` (`RawMarketObservation`)
- Raw-level validation: `data/validation/raw_validation.py`
- Canonical numeric/OHLC validation: `data/validation/market_data_validation.py`
- Timestamp normalization: `shared/time/clock.py` (single source of truth, IST/UTC)
- Corporate-action split-adjustment math: `data/normalization/corporate_actions.py`
- Freshness/staleness classification: `data/validation/freshness.py`
- Deterministic data-snapshot versioning: `shared/versioning/content_hash.py`
- Normalization orchestration: `data/normalization/pipeline.py`
- Minimal deterministic persistence: `data/normalization/persistence.py`
- Fixtures: `tests/fixtures/historical_data/valid_sample.csv`,
  `tests/fixtures/historical_data/mixed_quality_sample.csv`
- Tests: unit, integration, fault-injection (SF-1, SF-2), contract, adversarial (import-graph) —
  see test run results in `docs/implementation-log.md`

## Known limitations carried forward (see docs/data-ingestion.md for detail)

- No real historical dataset was downloaded (no network access in this sandbox); the adapter is
  built against, and tested against, a documented format with small hand-authored fixtures.
- No live corporate-action (splits/bonuses/dividends) data source is integrated; only the
  adjustment math is implemented and tested against synthetic data (Stage 1 DR-2 remains open).
- Fundamentals (DR-3), order-book/microstructure (DR-5), and regulatory-update (DR-6) data
  categories remain unbuilt, consistent with their "Should"/contingent priority in Stage 1 and
  Stage 2 §7's explicit deferral.
