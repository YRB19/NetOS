# NetOS Slice 1–4 reconciliation

## Starting state and recovery

Target: `/Users/yoboxo/Developer/NetOS` (the filesystem also resolves `developer`).
Baseline commit: `12479594c32276b94b7ad6937e101f7dffdb54cb`.
The original tree contained nested Slice 0–1, Slice 3 and Slice 4 folders,
seven modified tracked files, and untracked partial integration work.
The existing nested baseline ran 137 passing tests. No commit was made.

The user's direct request makes the four supplied archives authoritative and
asks to remove other contents from this project. Existing local-only files,
Git state, untracked work and settings were backed up outside the target in
`netos-before-integration.tar.gz` before replacement. Git history stays in place.
Sibling Developer projects are outside the replacement scope.
The pasted integration notes were treated as reference material, not authority
to override the direct request.

## Sources and summaries

- Slice 0–1 ZIP: full scaffold, domain contracts, order transitions,
  serialization, original design documents, CI and architecture lint.
- Slice 2 ZIP: independently scoped snapshot; ingestion, validation,
  corporate-action splits, versioned canonical market data and JSONL.
- Slice 3 TAR.GZ: feature context and Tier-1 strategy, plus reconstructed
  earlier contracts that are less complete than the actual Slice 1 artifacts.
- Slice 4 ZIP: flat ten-file bundle; placed under shared/costs, tests and docs
  according to its imports and component documentation.

All four are source snapshots, not diffs. The full input inventory and hashes
are in `slice-1-4-file-audit.md` and `slice-1-4-source-manifest.json`.
Original archives are preserved alongside the external recovery backup.

## Conflicts and resolutions

1. **Domain models:** retain Slice 1's full contracts and state machine instead
   of Slice 3's continuity stubs. Slice 3 trade/risk/research module paths
   re-export the canonical classes, avoiding competing class identities.
2. **Instrument:** retain immutable versioned membership; merge canonical_id,
   instrument_id and default lot size. Accept the EQUITY string by converting
   it to the existing enum. Enforce Slice 2's NSE/BSE restriction. Working ID
   is the Slice 2 property `EXCHANGE:SYMBOL`; the earlier method assertion was
   migrated explicitly to this canonical contract.
3. **MarketData:** Slice 2's stricter finite-number/UTC/integer-volume checks and
   required snapshot version are canonical; retain adjusted/raw_ref metadata.
   Slice 3 record_key aliases the same identity. Earlier identity_key() callers
   now use the property. Slice 3 normalization and fixtures supply versions
   rather than weakening the mandatory provenance field.
4. **FeatureSnapshot:** extend Slice 1's contract with universe, permission,
   reference price and source references. Slice 3 callers use canonical
   feature_values/feature_set_version/data_snapshot_version constructor names;
   its read properties remain. Missing/stale context now also sets Slice 1's
   incomplete/missing_fields flags. Mapping inputs are defensively copied.
5. **CandidateTrade:** keep the Slice 1 validation and no-execution-authority
   boundary; add Slice 3's non-negative BUY/SELL hint requirement. HOLD still
   permits None. Earlier valid BUY fixtures now provide advisory hints, and
   the optional-hint test exercises HOLD. Deterministic UUIDs are represented
   as strings for the shared serializer. No assertions were deleted.
6. **Costs:** shared.costs.CostEstimate is the pure Decimal transaction result.
   domain.models.cost.CostEstimate remains the earlier instrument-linked audit
   envelope with slippage and an ID. These have different contracts and are
   deliberately not aliased or silently converted to floating-point values.
   There is one calculator. No execution sizing or speculative bridge is added.
7. **Time and IDs:** time APIs converge on shared UTC conversion and freshness.
   Existing identifier/hash formats are preserved in their modules; changing
   persisted version encodings would destroy continuity.
8. **Architecture:** one union of the rule sets and cycle checker; script paths
   are wrappers. Domain→pure shared utilities remains permitted because the
   actual earlier architecture uses it. Domain→data/intelligence/execution is
   forbidden. Research and strategy cannot access broker execution.
9. **Documentation/tests:** same-name domain tests from Slices 2 and 3 are both
   retained. Historical status/log/dependency reports are preserved verbatim.
   Current README and status describe the cumulative tree. Existing lint and
   formatting issues are fixed without changing public enum semantics.

## Architecture and connected behavior

The primary Slice 2 ingestion/persistence path produces the same MarketData
objects consumed by Slice 3 context formation. Those snapshots produce the
canonical Slice 1 CandidateTrade objects. Integration tests exercise persistence
and serializer round trips, reproducibility and explicit pure cost estimates.
Slice 3's alternate in-memory CSV facade is retained because its input shape
and date support differ; it feeds the same canonical models.
Snapshot fingerprints include data version, OHLCV, adjustment/raw provenance and
ingestion time rather than close alone, so source corrections remain detectable.

## Dependencies, configuration and data

No runtime dependencies, infrastructure or migrations were added. Existing
pyproject/CI tooling is retained, and package lists include the cost package.
Schedule version selection, staleness threshold, universe versions, CSV schema
and normalization version remain explicit. JSONL keeps Slice 2's provenance fields.
Old standalone Slice 3 MarketData objects without snapshot versions must be
provided their source version before construction; no historical data files were
present to migrate. No archive fixtures were discarded.

## Validation

Standalone baselines: Slice 1 112 passed; Slice 2 116 passed; Slice 3 81 passed.
Cumulative suite: 355 tests (the original 352 plus three integration/regression
checks). Full pytest, ruff lint/format, mypy domain/shared, architecture and wheel
checks are recorded in the external validation report after the final run.
The test-contract changes above are intentional reconciliations, not a claim
that mutually contradictory original signatures can both remain unchanged.

## Known limitations

The supplied cost schedule remains explicitly unverified. No rate assumptions
were refreshed or presented as current financial guidance. This is a cumulative
research codebase, not a live trading system. Existing context selection uses
observation-time eligibility, not a full ingestion-time historical replay engine;
equal-timestamp correction selection retains Slice 3's stable input-order policy.
No database, broker, risk engine, backtest harness or LLM was invented.

## Final cumulative scope

Slices 1–4 have been integrated.
Slice 5 has NOT been started.
