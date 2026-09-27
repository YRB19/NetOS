# Feature / Context Formation — Slice 3

## Purpose

Transforms canonical `MarketData` (Plane 1 output) plus the explicit
`PermittedUniverse` into the immutable `FeatureSnapshot` objects that are
the **only** thing the intelligence layer (Plane 2) is allowed to
consume (Stage 3 §3.1). This is not a predictive-feature layer — its
job is deterministic context assembly, not signal generation.

## Input contract

`build_feature_snapshots(market_data, universe, as_of, market_data_snapshot_version=None, feature_set_id=TIER1_CONTEXT_FEATURE_SET_ID, staleness_threshold=5 days, instrument_ids=None)`

- `market_data: list[MarketData]` — canonical records only (never raw
  adapter output; the pipeline is adapter → validation → normalization
  → `MarketData` → this function).
- `universe: PermittedUniverse` — explicit, versioned, operator-supplied
  membership set (see `data/features/universe.py`). Never discovered or
  expanded by this module.
- `as_of: datetime` — must be timezone-aware UTC.
- `instrument_ids` — optional override of which instruments to build
  snapshots for; defaults to the permitted universe. Widened only to let
  a strategy request a snapshot for an instrument just *removed* from
  the universe (so an exit decision remains attributable — RR-7). Widening
  never changes whether an instrument is treated as *permitted*; that is
  computed independently against `universe`.

## Output contract

One `FeatureSnapshot` per target instrument, always — never silently
skipped. Each snapshot carries:
- `snapshot_id` — deterministic, content-addressed (same inputs → same id).
- `feature_set_id`, `universe_version`, `market_data_snapshot_version` —
  full provenance for reconstruction (FR-5).
- `is_permitted` — whether the instrument was in the permitted universe
  at `as_of`.
- `reference_price` — the canonical close price used downstream, or
  `None` if data is missing/stale.
- `source_refs` — pointer(s) to the exact `MarketData` record(s) used.
- `is_complete` (derived) — `True` only if `is_permitted and reference_price is not None`.

## Initial feature set

`tier1_context_v1` (`data/features/feature_sets.py`). Fields: `reference_price`
only. Deliberately excludes RSI, MACD, moving averages, momentum,
sentiment, technical indicators, news, fundamentals, and any
LLM-generated value — those are explicitly out of scope for this slice
and belong to Tier-2 (momentum, Slice 6) and the LLM component (Slice 13).

## Determinism

`build_feature_snapshots` is a pure function: identical
`(market_data, universe, as_of, feature_set_id, market_data_snapshot_version, instrument_ids)`
always produces identical output. No randomness, no wall-clock reads
(other than the explicitly-passed `as_of`), no hidden global state, no
network or provider calls. Verified by `tests/unit/test_context_builder.py::test_3_deterministic_output`
and `tests/unit/test_adapter_and_normalization.py::TestNormalization::test_deterministic_normalization`.

## Universe handling

`PermittedUniverse` (`data/features/universe.py`) is an explicit,
content-addressed-versioned frozenset of instrument ids. Its version is
a hash of its sorted membership, so two universes with identical
membership always compare equal on version regardless of construction
order. `diff(previous)` returns `(added, removed)` — the primitive the
Tier-1 baseline uses to decide BUY vs HOLD vs SELL. No dynamic
universe-selection algorithm exists in this module; membership is
always supplied by the caller (ultimately Plane 0 / the operator, in
later slices).

## Provenance

Every snapshot is reconstructable from its own fields alone: which
`MarketData` records fed it (`source_refs`), which universe version was
in force, which feature-set version, and which market-data-snapshot
version. No snapshot is ever mutated after construction (`@dataclass(frozen=True)`).

## Limitations (explicit, not silent)

- No corporate-action (splits/bonuses/dividends) adjustment is applied
  by this reconstruction (DR-2 is `Should`, not required to exercise
  Slice 3; the normalizer's docstring flags this explicitly).
- No order-book/microstructure data (DR-5) is used; `reference_price` is
  the daily close only.
- Staleness threshold (5 calendar days) is a reasonable default for
  daily-bar equities data, not an operator-reviewed threshold — Stage 1
  leaves exact thresholds as TBD/operator decisions; this default is
  clearly a placeholder, not a claimed-correct value.
- No persistence layer exists yet (Slice 2's minimal reconstruction does
  not include a database); `MarketData` batches are in-memory only in
  this repository state.
