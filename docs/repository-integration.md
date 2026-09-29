# Repository integration (Slice 4.5A)

## Why this was necessary
Slices 0–4 were built in non-persistent sandboxes, so no single repository held them all.
The uploaded `NetOS.zip` is the result of an earlier integration (git history of ~30 commits,
`docs/slice-1-4-reconciliation.md`). Slice 4.5A **independently verified** that tree instead of
trusting its reports, fixed what verification found, and added integration tests.

## Source artifacts inspected
- `NetOS.zip` (single upload): full working tree, `.git`, `docs/`, `docs/history/slice1..4/`,
  `docs/slice-1-4-source-manifest.json` (per-file SHA-256 of the original inputs),
  `docs/slice-1-4-file-audit.md`.
- **Not available to this session:** the four original per-slice archives and the external
  recovery backup named in the earlier reconciliation. Their contents could not be diffed
  against the integrated tree; only the recorded manifest hashes and preserved historical
  reports exist. The `.venv/` in the zip is macOS/Python 3.14 and unusable here.

## Slice-by-slice
| Slice | Status | Provenance | Notes |
|---|---|---|---|
| 0 | Restored (verified) | prior integration | one checker (`shared/arch_lint`), both script paths delegate; 0 violations |
| 1 | Restored (verified) | prior integration | full Stage 3 §2 surface; state machine in `domain/models/order.py` |
| 2 | Restored (verified) | prior integration | primary path `pipeline.py`; JSONL persistence |
| 3 | Restored (verified) | prior integration | contexts, Tier-1; alternate in-memory path retained |
| 4 | Restored (verified) | prior integration | `shared/costs`; schedule `india-equity-v1-unverified`, `verified=False` |

## Findings and reconciliation (this slice)
1. **Duplicate class `NormalizationResult`** (`normalizer.py` vs `pipeline.py`). Renamed the
   Slice 3 alternate-path one to `AlternateNormalizationResult` (only used in its own module).
   No behaviour change.
2. **Two `CostEstimate` classes — retained, needs operator decision.** `shared.costs.CostEstimate`
   is the pure Decimal calculator result; `domain.models.cost.CostEstimate` is the Stage 3 §2
   audit envelope (slippage, id, version). Different contracts, deliberately not aliased
   (decision from the earlier reconciliation). This is an explicit allow-listed exception in
   the new duplicate-class test; a rename would touch 43+ preserved tests.
3. **Two ingestion paths retained.** Slice 2 pipeline (canonical) and Slice 3 in-memory CSV path
   (`nse_csv_adapter`, `normalizer`, `validators`) both feed canonical `MarketData`. Two
   implementations of overlapping behaviour remain — a continuity risk, not consolidated
   because both have preserved tests.
4. **Determinism nuance.** The adapter stamps `ingestion_time` once per read (provenance by
   design), and snapshot fingerprints include it. Two separate reads of the same file
   therefore differ in ingestion metadata and snapshot version; a fixed raw read is fully
   deterministic through MarketData → FeatureSnapshot → CandidateTrade → CostEstimate.
   Not changed (would alter Slice 2 behaviour); flagged for Slice 5 replay design.
5. `Confidence/Uncertainty` is not a standalone class: it is `confidence` + `UncertaintyBand`
   on `CandidateTrade` (Stage 3 §3.2 contract), which satisfies the spec.

## Canonical locations
Domain `domain/models/`; ingestion `data/adapters/nse_bhavcopy_csv.py`,
`data/normalization/pipeline.py`; features `data/features/`; Tier-1
`intelligence/baseline/tier1_equal_weight.py`; costs `shared/costs/`; checker
`shared/arch_lint/`. Risk, sizing, broker, research, governance, LLM packages are empty scaffolds.

## Remaining continuity risks
Original archives unavailable; cost rates unverified; parallel ingestion paths; ruff/mypy not
re-run (no network; the bundled mypy is macOS-compiled); `run_tests.py`/pytest needed for 3
pytest-fixture tests (unittest discovers 366 of 369).
