# Implementation Log

Waterfall discipline: entries are appended, never rewritten. See Stage 1
DOC-6.

---

## Entry 1

```
Date:              2026-09-05 (session date; system clock — see note below)
Stage:             Stage 3 -> Implementation
Slice:             Slice 0 (Repository scaffolding + plane isolation)
                   Slice 1 (Core domain models)
```

### What was implemented

**Slice 0:**
- Full repository directory structure per Stage 3 §1, all eight planes
  plus `tests/`, `scripts/`, `docs/`, `deploy/`, each populated with the
  Stage-3-specified subpackages and `__init__.py` markers.
- ADR-6 import-graph isolation enforcement: a dependency-free, AST-based
  static checker (`shared/arch_lint/`) with a documented rule set, a pure
  scanning function, and a CLI entry point suitable for both local and CI
  use.
- `.github/workflows/ci.yml`: install, ruff lint + format check, mypy
  (advisory), pytest, and the ADR-6 CLI check as the final gate.
- `pyproject.toml`: project metadata, flat-layout package declarations for
  every plane subpackage, pytest/ruff/mypy tool configuration.

**Slice 1:**
- Every Stage 3 §2 domain object, implemented as typed, validated Python
  dataclasses under `domain/models/`, split into one module per logical
  group (instrument, market_data, feature_snapshot, candidate_trade, cost,
  risk_decision, portfolio, order_request, order [state machine],
  decision_record, versions, research_artifacts, promotion, autonomy,
  enums), plus a shared `_validators.py` for common field-validation logic
  and a `serialization.py` providing generic, deterministic
  to/from-serializable conversion.
- `shared/time/clock.py`: single source of truth for UTC storage / IST
  display, per Stage 3 §5.
- `shared/versioning/identifiers.py`: `new_id()` (UUID4) and
  `content_hash()` (deterministic SHA-256 over ordered parts), used by
  every versioned artifact.
- Full test suite (see below).

### Files / modules created

68 Python files. Full list:

```
conftest.py
pyproject.toml
.github/workflows/ci.yml
governance/{,config,autonomy,killswitch}/__init__.py
data/{,adapters,validation,normalization,features,schemas}/__init__.py
domain/__init__.py
domain/models/__init__.py
domain/models/_validators.py
domain/models/enums.py
domain/models/instrument.py
domain/models/market_data.py
domain/models/feature_snapshot.py
domain/models/candidate_trade.py
domain/models/cost.py
domain/models/risk_decision.py
domain/models/portfolio.py
domain/models/order_request.py
domain/models/order.py
domain/models/decision_record.py
domain/models/versions.py
domain/models/research_artifacts.py
domain/models/promotion.py
domain/models/autonomy.py
domain/models/serialization.py
intelligence/{,baseline,llm_component,interface}/__init__.py
risk_execution/{,cost_model,risk_engine,sizing,order_state_machine,broker}/__init__.py
observability/{,decision_log,reconciliation,reporting}/__init__.py
research/{,harness,contamination,stats,experiments,promotion}/__init__.py
shared/__init__.py
shared/time/__init__.py
shared/time/clock.py
shared/versioning/__init__.py
shared/versioning/identifiers.py
shared/config_loader/__init__.py
shared/arch_lint/__init__.py
shared/arch_lint/rules.py
shared/arch_lint/checker.py
shared/arch_lint/cli.py
tests/{,unit,integration,contract,simulation,fault_injection,adversarial}/__init__.py
tests/unit/_helpers.py
tests/unit/test_valid_construction.py
tests/unit/test_required_field_validation.py
tests/unit/test_candidate_trade_safety.py
tests/unit/test_immutability.py
tests/unit/test_order_state_machine.py
tests/unit/test_versioning.py
tests/unit/test_serialization.py
tests/adversarial/test_import_isolation.py
docs/00-Project-Understanding-Report.md   (copied from project source)
docs/01-Self-Improvement-Research-Report.md   (copied)
docs/02-Self-Improvement-vs-Static-Strategy-Report.md   (copied)
docs/03-Stage1-Requirements-Baseline-v0_2.md   (copied)
docs/04-Stage2-System-Architecture-v0_1.md   (copied)
docs/05-Stage3-Detailed-Technical-Design-v0_1.md   (copied)
docs/slice-status.md
docs/dependency-decisions.md
docs/implementation-log.md   (this file)
README.md
```

### Tests added

112 tests across 8 files:

| File | Count | Purpose |
|---|---|---|
| `tests/unit/test_valid_construction.py` | 20 | Every domain object can be validly constructed |
| `tests/unit/test_required_field_validation.py` | 26 | Invalid/missing required fields fail, across representative models |
| `tests/unit/test_candidate_trade_safety.py` | 20 | Exhaustive CandidateTrade contract tests (explicitly required by the prompt) |
| `tests/unit/test_immutability.py` | 13 | Frozen dataclasses actually reject mutation; MappingProxyType fields too |
| `tests/unit/test_order_state_machine.py` | 17 | Every valid transition + every explicitly-named invalid transition + exhaustive terminal-state check |
| `tests/unit/test_versioning.py` | 8 | Version-reference presence, typing, and content-determinism |
| `tests/unit/test_serialization.py` | 8 | object -> serialized -> object round-trip, including JSON-safety |
| `tests/adversarial/test_import_isolation.py` | 4 | Mandatory ADR-6 test: illegal imports detected in throwaway fixtures; real repo has zero violations |

### Tests / results (actual, run in this session)

Environment note: this sandbox has no network access, so `pytest`, `ruff`,
and `mypy` (declared as dev dependencies) could not be installed or run
here. The test suite was written using `unittest.TestCase` specifically so
it could be *actually executed* now rather than only asserted to work —
see `docs/dependency-decisions.md` for the full explanation. `pytest`
collects and runs `unittest.TestCase` suites natively with zero changes,
so `pytest -v` is expected to run the identical 112 tests once installed
in an environment with network access (CI, or a developer machine) — this
expectation is stated explicitly rather than left implicit, and should be
confirmed the first time `pytest` actually runs.

Command run:
```
python3 -m unittest discover -s tests -p "test_*.py" -v
```

Result:
```
Ran 112 tests in 0.018s

OK
```
(Full per-test verbose output is reproducible by re-running the command
above; all 112 report `... ok`, zero failures, zero errors, zero skips.)

Additionally:
```
$ python3 -m shared.arch_lint.cli .
ADR-6 import-isolation check: PASSED (0 violations) — scanned .

$ python3 -m py_compile <every .py file in the repo>
ALL FILES COMPILE OK
```

`ruff` and `mypy` were **not** run (no network access to install them in
this session) — flagged as an open item, not silently skipped.

### Architectural decisions made during implementation

- **`Order` reconstruction from serialized form is a dedicated function
  (`order_from_serializable`), not the generic `from_serializable`.**
  `Order.__post_init__` deliberately forbids constructing anything other
  than a fresh `CANDIDATE`-state order (this is what guarantees every
  transition is audit-trailed — see `order.py`'s docstring). Generic
  reconstruction would have needed to bypass that guarantee. Instead,
  reconstruction replays the recorded transition history, which
  additionally proves the stored history is itself a legal sequence.
- **`CandidateTrade` carries a defensive, normally-unreachable runtime
  assertion** checking its own `__dataclass_fields__` against a forbidden-
  name set (`quantity`, `order_quantity`, `shares`, `order_size`) on every
  construction. This is deliberately paranoid for the single most
  safety-critical interface in the system (Stage 3 §3.2) — if a future
  change ever adds such a field, every CandidateTrade construction (i.e.
  effectively every test in the suite) fails immediately and loudly,
  rather than the violation being discoverable only via code review.
- **Governance-write-interface isolation is currently "no import of
  `governance` at all"** from `research`/`intelligence`, rather than a
  finer-grained "no *write* access" rule — because the `governance`
  package doesn't yet have a read/write split (that's Governance-plane
  build work, not scheduled yet). This is documented in
  `shared/arch_lint/rules.py`'s module docstring as a rule that should be
  *narrowed*, never widened, once that split exists.
- **`ConfigurationVersion` is identity-addressed (UUID); `StrategyVersion`
  /`ModelVersion`/`RiskRuleVersion` are content-addressed (SHA-256).** This
  wasn't fully explicit in Stage 3 §19 for every type, so a decision was
  needed: two configuration snapshots with identical values taken at
  different times are still distinct historical facts (an operator
  re-confirming the same values is a real event), whereas two strategy
  artifacts with identical code/config genuinely are the same artifact and
  should collapse to the same identity (this is what makes ER-4's
  multiple-testing correction across a lineage well-defined). Recorded here
  since it's a real interpretive decision, not dictated verbatim by Stage 3.

### Problems discovered

- Two bugs found and fixed during self-testing before declaring the
  milestone done (neither reached the committed test suite in its buggy
  form): (1) an arithmetic error in a hand-computed expected value in
  `test_cost_estimate_and_actual_cost` (29.2 vs. the correct 29.7 — a test
  bug, not a production bug); (2) an unused `field` import in
  `domain/models/portfolio.py`, caught by a lightweight AST-based
  unused-import scan run in place of `ruff` (unavailable, see above).
- No genuine Stage 3 contradiction was found. No architecture-level
  question was escalated.

### Decisions deferred

- Whether `mypy` should be a hard CI gate rather than advisory — deferred
  until it has actually been run once against this codebase (it has not,
  per the no-network-access note above).
- The exact library (if any) to replace the hand-rolled unused-import scan
  once `ruff` is actually runnable — expected to be `ruff` itself, per
  `pyproject.toml`, pending confirmation.

### Next slice

**Slice 2 — Historical Data Ingestion**, per Stage 3 §21. Not started —
per the implementation prompt's explicit instruction to stop here.

---

*Notion write status: not attempted this session. Per the established
project discipline (Stage 0-3 documents' own logged history), Notion write
access has previously failed with a "No approval received" error of
unconfirmed resolution status, and no MCP/Notion tool is available in this
implementation session to test it. This log entry is saved as Markdown
under `docs/` per the fallback rule — no Notion write is claimed.*

*Date note: this environment's system clock and the project's own stated
"current date" context differ slightly across the session's source
documents (which reference 2026-08-29 through 2026-08-31); this entry uses
the implementation session's actual date without attempting to reconcile
that discrepancy, consistent with "preserve the history, don't rewrite it
to look cleaner."*
