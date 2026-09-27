# Implementation Log

## Session: Slice 4 — Cost Model

**Starting repository state:** `/home/claude/trading-system` did not exist
on disk at session start — confirmed empty, consistent with this project's
previously-documented finding that the sandbox does not persist code
between sessions. No Slice 0–3 artifacts (domain models, data pipeline,
Tier-1 baseline) were present to inspect or build against.

**Decision made about scope, given this:** rather than silently assuming
Slice 0–3 code existed, or spending this session reconstructing all of
Slices 0–3 (a materially different and larger task than the Slice 4 prompt
itself specifies), this session built:

1. The minimal scaffold Slice 4 actually depends on: top-level directory
   structure consistent with the Stage 3 §1 repository layout, and a real,
   working import-graph/dependency-direction checker
   (`scripts/check_import_graph.py`), since Slice 4's own acceptance
   criteria require "architecture checker reports 0 violations" and that
   check needs to actually exist and actually run, not be assumed.
2. Slice 4 (Cost Model) in full, as specified.

This is recorded explicitly (rather than silently) so a future session
does not mistake "Slice 4 tests pass" for "the full prior implementation
still exists" — it does not, and reconstructing it is a separate,
documented open item (see `slice-status.md`).

**Implementation:**

- `shared/costs/models.py` — `TransactionSide`, `TradeType`, `CostInputs`
  (validated, immutable, Decimal-coercing), `CostEstimate` (immutable,
  all six components always present, `component_total()` and
  `cost_pct_of_turnover()` helper methods).
- `shared/costs/schedule.py` — `IndiaEquityCostSchedule` (versioned rate
  configuration, deliberately separate from calculation logic),
  `ScheduleRegistry`, `default_registry()`, and the single shipped
  schedule `INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED` — explicitly named and
  documented as unverified against a primary regulatory source this
  session (see decision below).
- `shared/costs/calculator.py` — `CostModel.estimate()`, a pure function
  implementing brokerage, STT, exchange transaction charges, SEBI charges,
  GST, and stamp duty per the side/trade-type rules documented in
  `docs/cost-model.md`, with an explicit `ROUND_HALF_UP`-to-paisa rounding
  policy applied per component before summation.
- `scripts/check_import_graph.py` — AST-based static import checker
  enforcing plane-isolation rules (extensible to future planes without
  modification, since rules for not-yet-built directories are declared
  now and are simply inert until those directories exist).
- `tests/unit/test_costs.py` — 43 tests across validation, calculation,
  reconstruction, rounding, versioning, independence, determinism, and
  round-trip categories.

**Key decisions:**

1. **Decimal, not float, for all monetary values.** Floats accepted at the
   `CostInputs` boundary for caller convenience are converted via
   `Decimal(str(value))`, never `Decimal(float)` directly, to avoid
   importing binary-floating-point representation error into a price.
2. **Rounding: per-component `ROUND_HALF_UP` to 2 decimal places, total is
   the exact sum of already-rounded components (never independently
   re-rounded).** This makes `total_cost == component_total()` a structural
   guarantee, not a coincidence, and is directly tested.
3. **Schedule is data, not code.** `IndiaEquityCostSchedule` is a frozen
   dataclass of rates; `CostModel`'s logic never hardcodes a rate directly
   — every rate reference goes through the schedule object passed in via
   the registry. A new rate table is a new schedule version, never an
   edit to an existing one.
4. **The v1 schedule is marked `verified=False` with an explicit
   `-unverified` version-id suffix.** This project's own epistemology
   (evidence tiering, primary-source verification, "do not fabricate
   regulatory verification") applies here just as it applied to the
   Stage 0 research literature review — a plausible, commonly-cited rate
   structure is not the same claim as a primary-source-confirmed one, and
   the two must not be allowed to look identical in the code or the docs.
   See `docs/cost-model.md`'s Provenance section for the full statement.
5. **`CostInputs` is not `OrderRequest`.** Kept as its own minimal domain
   contract so Research/backtest code (which has no order or broker
   context) can call the Cost Model identically to how execution
   eventually will.

**Test results:** 43/43 passing (`python3 -m unittest discover -s tests -p
"test_*.py" -v`). No failures, no skips.

**Architecture check:** `python3 scripts/check_import_graph.py` → 0
violations.

**Bugs/fixes during implementation:** two test-authoring issues caught and
fixed before finalizing (not implementation bugs): (a) a test attempted to
put `CostEstimate` instances into a `set()`, which fails at runtime because
the frozen dataclass's default-generated `__hash__` calls `hash()` on the
`schedule_notes` dict field, which is unhashable — removed the unused set
construction rather than adding an unsafe custom `__hash__`; (b) an
overly-elaborate half-cent rounding test was simplified to a single,
clearly-reasoned boundary case (`1 * 0.005 = 0.005 -> 0.01` under
`ROUND_HALF_UP`) after an earlier draft's inline arithmetic comments were
found to be internally inconsistent while writing them out.

**Cost-schedule provenance:** see `docs/cost-model.md` — summarized as
"commonly-cited industry structure, not independently primary-source
verified this session."

**Limitations:** see `docs/slice-status.md`'s Known Limitations section in
full; the two most important are (1) rate-table verification and (2) the
fact that Slices 0–3 do not currently exist on disk this session, so full
cross-slice regression testing was not possible.

**Next step:** per `slice-status.md`'s recommendation — either reconstruct
Slices 0–3 in a dedicated session to restore full regression coverage, or
proceed to Slice 5 with the understanding that a real end-to-end research
run will still need Slices 2–3 reconstructed first. Rate-table verification
(limitation #1) should be treated as a priority open item regardless of
which slice comes next.
