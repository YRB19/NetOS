
---

## Slice 3 — Feature/Context Formation + Tier-1 Baseline

**Date/time (session):** 2026-09-26 (per system date)

**Starting repository state:** `/home/claude/trading-system` did not
exist. No prior Slice 0/1/2 artifacts were present in this sandbox.

**Continuity findings:** confirmed a total absence of the previously
reported implementation (not merely a partial gap, as flagged after
Slice 2). Reconstructed the full plane-isolation directory structure,
the complete Stage 3 §2 domain model (21 objects), a minimal NSE-CSV
adapter, validation, and normalization (Slice 0-2 equivalents), before
building Slice 3 proper. This is documented plainly rather than assumed
away; see `docs/slice-status.md` for the full continuity table.

**Implementation summary:**
1. Scaffolded the repository per Stage 3 §1's directory layout, with
   `__init__.py` in every package.
2. Built `shared/time/clock.py` and `shared/versioning/versioning.py` as
   the cross-cutting utilities every plane depends on.
3. Implemented the full domain model (`domain/models/`): enums,
   Instrument, MarketData, FeatureSnapshot (+ MarketDataRef),
   CandidateTrade, versioned artifacts (StrategyVersion, ModelVersion,
   ConfigurationVersion, RiskRuleVersion), CostEstimate/ActualCost,
   RiskDecision, PortfolioState/Position, OrderRequest/Order/Fill,
   DecisionRecord, research objects (Experiment/EvaluationRun/
   PromotionCandidate), AutonomyLevel. Each with constructor-level
   validation (immutability + required-field enforcement in the type
   itself, not only at a future runtime boundary, per Stage 3 §21's
   Slice-1 guidance).
4. Reconstructed a minimal, functional NSE-bhavcopy CSV adapter,
   validator, and normalizer (`data/adapters`, `data/validation`,
   `data/normalization`) sufficient to produce canonical `MarketData`.
5. Built `PermittedUniverse` (`data/features/universe.py`) — explicit,
   content-addressed-versioned, with a `diff()` primitive for
   added/removed detection.
6. Built the Tier-1 context feature set definition (`data/features/feature_sets.py`)
   and the feature/context builder (`data/features/context_builder.py`),
   handling SF-1 (missing) and SF-2 (stale → treated as missing)
   deterministically, with full provenance.
7. Implemented the Tier-1 equal-weight buy-and-hold baseline
   (`intelligence/baseline/tier1_equal_weight.py`) per the exact
   behavior table in `docs/baseline-tier1.md`.
8. Built the import-graph lint (`tools/check_import_graph.py`) enforcing
   plane isolation, including a negative/provocative test proving it
   actually catches a synthetic violation.
9. Wrote 81 tests across unit, integration, contract (architecture), and
   fault-injection categories.

**Tests:** 81/81 passing. `python3 -m unittest discover -s tests -p "test_*.py"`.

**Architecture check:** `python3 tools/check_import_graph.py` → 0
violations, 0 cycles, 59 modules scanned.

**Failures encountered and fixed during this session:**
- Initial `FeatureSnapshot` validation incorrectly forbade
  `is_permitted=True, reference_price=None`, which is exactly the valid
  SF-1 "missing data" representation the spec requires — relaxed the
  validation and documented the correct semantics.
- Test 14/15 (no-broker / no-network dependency) initially used raw
  substring search and false-failed on the word "broker" appearing in a
  docstring; switched to `ast`-based import inspection for precision.
- Minor cleanup: unused `is_utc` import in the strategy module; a
  leftover no-op expression in a test file.

**Decisions:**
- `size_hint` is a normalized `[0,1]` allocation-weight hint, never a
  quantity — documented explicitly in `docs/baseline-tier1.md` per the
  Slice 3 prompt's instruction not to silently reinterpret the contract.
- Removed instruments require an explicit widened `instrument_ids` call
  into `build_feature_snapshots` to obtain an attributable exit snapshot
  (RR-7); the strategy raises rather than silently skipping if this
  isn't supplied.
- HOLD is represented as a first-class `CandidateTrade` with
  `action=HOLD`, never as an absent candidate or an exception, per TR-4
  and the Slice 3 prompt §14.

**Known limitations:** see `docs/slice-status.md`.

**Next step:** Slice 4 (Cost Model) or Slice 5 (Research harness core),
per `docs/slice-status.md`'s recommendation. Do not begin Slice 4/5
automatically — this is a stop point per the Slice 3 prompt §24.
