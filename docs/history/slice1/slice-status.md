# Slice Status

## Slice 0 — Repository scaffolding + enforced plane isolation

**Status: COMPLETE.**

- Repository structure created exactly per Stage 3 §1: `governance/`,
  `data/`, `domain/`, `intelligence/`, `risk_execution/`, `observability/`,
  `research/`, `shared/`, plus `tests/`, `scripts/`, `docs/`, `deploy/`,
  each with the subpackage structure Stage 3 specifies (e.g.
  `risk_execution/{cost_model,risk_engine,sizing,order_state_machine,broker}`).
- **ADR-6 (import-graph / dependency-direction enforcement)** implemented
  as a real, automated, dependency-free AST-based checker:
  - `shared/arch_lint/rules.py` — the rule set (data, not logic).
  - `shared/arch_lint/checker.py` — the scanner (`scan_directory`,
    `scan_file`, pure functions taking a root path and returning
    `Violation` objects).
  - `shared/arch_lint/cli.py` — `python -m shared.arch_lint.cli [ROOT]`,
    exit code 0/1, this is the command CI runs.
  - Enforced rules: `research` ⇏ `risk_execution` (incl. `.broker`),
    `research` ⇏ `governance`, `research` ⇏ `observability.decision_log`;
    `intelligence` ⇏ `risk_execution` (incl. `.broker`), `intelligence` ⇏
    `governance`, `intelligence` ⇏ `data.adapters`; `risk_execution` ⇏
    `intelligence`.
  - Verified against the real repository: **0 violations** (see
    `implementation-log.md` for the exact command and output).
  - Verified to actually detect violations: `tests/adversarial/test_import_isolation.py`
    builds temporary, throwaway fixture trees (never the real repo) with a
    deliberately illegal `research -> risk_execution.broker` import and an
    `intelligence -> data.adapters` import, and asserts the checker flags
    both. A third test confirms a legal import is *not* flagged (no
    false positives). A fourth test scans the real repository itself and
    asserts zero violations — this is the test that would fail the build
    if a real violation were ever introduced.
- CI (`.github/workflows/ci.yml`): installs the project, runs `ruff check`,
  `ruff format --check`, `mypy` (advisory, non-blocking at this slice),
  `pytest`, and — the load-bearing step — `python -m shared.arch_lint.cli .`.

## Slice 1 — Core domain models

**Status: COMPLETE.**

All Stage 3 §2 domain objects are implemented under `domain/models/`:
`Instrument`, `MarketData`, `FeatureSnapshot`, `CandidateTrade` (+ its
embedded confidence/uncertainty fields), `CostEstimate`, `ActualCost`,
`RiskDecision` (+ `RiskCheckResult`), `PortfolioState`, `Position`,
`OrderRequest`, `Order` (+ the full state machine), `Fill`, `DecisionRecord`
(+ `DecisionRecordBuilder`, `DataSourceRef`), `StrategyVersion`,
`ModelVersion`, `ConfigurationVersion`, `RiskRuleVersion`, `Experiment` (+
`SplitSpec`, `ContaminationCheckResult`), `EvaluationRun`,
`PromotionCandidate`, `AutonomyLevel`.

- **No business logic, no I/O, no broker/LLM/database calls** anywhere in
  `domain/models/` — every model is a pure, validated data structure, per
  the implementation prompt's explicit instruction.
- **CandidateTrade contract enforced**: mandatory non-empty `rationale`
  (RR-7), mandatory `confidence` in `[0,1]` (SF-10), no field that could be
  read as an authoritative order quantity — `size_hint` is the only
  quantity-adjacent field, and a defensive runtime assertion
  (`CandidateTrade.__post_init__`) fails loudly if a forbidden field name
  is ever added to the dataclass in the future.
- **Immutability**: every object Stage 3 §2 marks immutable is a
  `@dataclass(frozen=True, slots=True)`; attempted mutation raises
  `dataclasses.FrozenInstanceError` (verified in
  `tests/unit/test_immutability.py`). Mutable collection fields (e.g.
  `ConfigurationVersion.values`) are additionally wrapped in
  `types.MappingProxyType` so a caller can't mutate a "frozen" object
  through a shared reference to one of its fields.
- **Order state machine**: `Order` is the one deliberately mutable domain
  object (Stage 3 §9 requires this — state advances via defined
  transitions only). `domain/models/order.py` implements the exact
  transition table from Stage 3 §9's diagram, plus the resolution
  transitions out of `RECONCILIATION_REQUIRED` described in the
  surrounding prose. Invalid transitions raise `InvalidOrderTransition`
  and leave the order's state and history unchanged — verified explicitly
  for `CANDIDATE -> FILLED`, `CANDIDATE -> ACKNOWLEDGED`, and
  `APPROVED -> FILLED` (all three are named in the implementation prompt),
  plus every other transition not in the allowed table (verified via an
  exhaustive "terminal state accepts nothing further" test).
- **AutonomyLevel**: domain representation only (`level`, `set_by`,
  `effective_from`, `effective_to`), append-only via `.closed()` (returns a
  new record, never mutates). No autonomy *behavior* and no promotion
  logic — that's explicitly out of scope for this slice per the
  implementation prompt.
- **Versioning**: every object Stage 3 §15/§19 requires to carry a version
  reference has one (`version_id`, `strategy_version_id`,
  `risk_rule_version_id`, `config_version_id`, etc.), correctly typed and
  non-empty. `StrategyVersion`, `ModelVersion`, and `RiskRuleVersion` are
  content-addressed (`shared/versioning/identifiers.py::content_hash`) —
  identical content always produces the same `version_id`, verified in
  `tests/unit/test_versioning.py`. `ConfigurationVersion` is
  identity-addressed (a fresh UUID per snapshot), since two config
  snapshots with identical values at different times are still distinct
  historical facts, not duplicates.
- **Serialization**: `domain/models/serialization.py` provides a generic,
  recursive `to_serializable` (→ JSON-safe primitives) and
  `from_serializable` (type-hint-driven reconstruction) covering every
  shape the domain models actually use (dataclasses, Enums, timezone-aware
  datetimes, tuples, dicts/`MappingProxyType`, `Optional[X]`/`X | None`).
  `Order` gets a dedicated `order_from_serializable` reconstructor, since
  its `__post_init__` deliberately forbids constructing anything but a
  fresh `CANDIDATE`-state order — reconstruction replays the recorded
  transition history instead, which also proves the stored history is
  itself a legal transition sequence. Round-trip equality
  (`object -> serialized form -> object`) is tested for every model shape
  that appears in practice.

## What was explicitly NOT built in this slice (by design)

Per the implementation prompt's "IMPORTANT: DO NOT GO FURTHER" section:
historical data ingestion, feature engineering, the momentum strategy, the
Cost Model, the Research harness, the Risk Engine, broker integration
(including the `SimulatedBrokerAdapter`), LLM integration, and any
self-improvement mechanism. `Order`'s broker-facing behavior (actually
talking to a broker) is likewise not built — only the domain
representation of its lifecycle.

## Recommended next step

**Slice 2 — Historical Data Ingestion**, per Stage 3 §21. Not started.
