# Slice Status

## Slice 4 — Cost Model — COMPLETE

**Scope built:** `shared/costs/` (models, schedule, calculator, public API),
`scripts/check_import_graph.py`, `tests/unit/test_costs.py`.

**Important note on repository state at session start:** consistent with
this project's documented finding that the sandbox does not persist code
between sessions, the repository was found **empty** at the start of this
session (no `trading-system/` directory existed on disk). Slice 4's scope
does not include reconstructing Slices 0–3's full domain model, data
pipeline, and Tier-1 baseline (that reconstruction is a substantial task in
its own right, previously performed in a dedicated Slice-3 session per the
project's implementation log). This session built:

1. The minimal subset of Slice 0's scaffold actually required by Slice 4 —
   directory structure and a real, working import-graph checker
   (`scripts/check_import_graph.py`), not the full Slice 0–3
   reconstruction.
2. Slice 4 (Cost Model) in full, as its own self-contained, independently
   testable, broker/strategy/research-independent package.

**Consequence — regression testing:** there was no pre-existing Slice 0–3
test suite on disk this session to regress against. "All Slice 0–3 tests
still pass" (Slice 4's acceptance criterion) is therefore not evaluable
this session in the strict sense of re-running prior tests; the correct
open item is **re-run Slice 4's implementation prompt's acceptance
criterion against a session where Slices 0–3 have first been reconstructed
in full**, so the full regression suite can be exercised together. This is
recorded as a known limitation, not silently glossed over.

### Implementation summary

- `CostInputs` / `CostEstimate` (`shared/costs/models.py`) — immutable,
  validated, Decimal-based domain contracts.
- `IndiaEquityCostSchedule` / `ScheduleRegistry` (`shared/costs/schedule.py`)
  — versioned rate configuration, separated from calculation logic.
  Default schedule: `india-equity-v1-unverified` — **rates not
  independently verified against a primary source this session; see
  `cost-model.md`'s Provenance section.**
- `CostModel` (`shared/costs/calculator.py`) — pure, deterministic
  `CostInputs -> CostEstimate` calculation covering brokerage, STT,
  exchange transaction charges, SEBI charges, GST, and stamp duty, with an
  explicit `ROUND_HALF_UP`-to-paisa rounding policy applied per component.

### Tests

- 43 tests in `tests/unit/test_costs.py`, all passing.
- Categories covered: input validation (13), calculation/component
  correctness (10), total reconstruction (4), rounding (4), versioning
  (4), independence (3), determinism (1), round-trip (2), plus fixtures.
- Full command: `python3 -m unittest discover -s tests -p "test_*.py" -v`
  from the repository root.

### Architecture check

- `python3 scripts/check_import_graph.py` → **0 violations**.
- Rules currently enforced: `shared/*` may not import `intelligence`,
  `research`, or `risk_execution.broker`; `domain/*` may not import
  anything plane-specific. Rules for `risk_execution.broker` importability
  are declared but inert until that package exists (Slice 6+), so they take
  effect automatically without editing the checker later.

### Known limitations

1. **Rate-table verification (primary, see `cost-model.md`)** — the India
   equity cost schedule is a commonly-cited industry structure, not a
   primary-source-verified rate table. Must be resolved before TR-2/PR-6/
   PR-9 can responsibly rely on it.
2. **Slices 0–3 not reconstructed this session** — see above. The Cost
   Model is fully self-contained and testable in isolation, but the
   project's full prior test suite (domain models, data ingestion, Tier-1
   baseline — previously ~81+ tests per the implementation log) does not
   currently exist on disk to regress against.
3. Brokerage modeled generically, not against a specific broker's current
   published rate card (unchanged limitation from Stage 3 §8, restated
   here for this slice's context).
4. No slippage/market-impact modeling (out of scope for this slice; belongs
   to DR-5/PR-7 in a future slice).

### Recommended next slice

Two reasonable options, not mutually exclusive:

- **(a)** Reconstruct Slices 0–3 (domain models, data ingestion, Tier-1
  baseline) in a dedicated session, so a full regression suite exists
  again and Slice 4's Cost Model can be exercised end-to-end alongside
  them (this is what Stage 3 §21's sequence assumes as normal continuity).
- **(b)** Proceed directly to Slice 5 (Research harness core: walk-forward
  splitting + ER-1 baseline comparison), since the Cost Model it depends on
  now exists and is independently proven, and reconstruct Slices 0–3 as a
  prerequisite of whichever slice first needs them (Slice 5 needs Slice 3's
  Tier-1 baseline and Slice 2's data pipeline to actually run an
  evaluation, so in practice (a) is likely unavoidable before (b) can
  produce a real end-to-end result — but the Cost Model itself does not
  block on this).

Either way: the rate-table verification (limitation #1) should be closed
before any Cost-Model-derived number is treated as more than a working
placeholder.
