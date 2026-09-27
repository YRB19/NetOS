# AI Trading Agent — Research & Engineering Project

**Status: Slice 0 + Slice 1 implemented. Not runnable as a trading system —
there is no data ingestion, no strategy, no broker, no risk engine, and no
execution capability yet.**

This repository is the implementation of the system specified across:

- `docs/00-Project-Understanding-Report.md` (Stage 0)
- `docs/01-Self-Improvement-Research-Report.md` / `docs/02-Self-Improvement-vs-Static-Strategy-Report.md` (Stage 0)
- `docs/03-Stage1-Requirements-Baseline-v0_2.md` (Stage 1 — approved)
- `docs/04-Stage2-System-Architecture-v0_1.md` (Stage 2 — build-ready)
- `docs/05-Stage3-Detailed-Technical-Design-v0_1.md` (Stage 3 — ready for implementation)

(The Stage 0–3 documents are the project's design record; copies are kept
under `docs/` for reference. This repository's `docs/` also contains the
implementation-specific documentation described below.)

## What exists right now

- The five-plane repository structure mandated by Stage 3 §1
  (`governance/`, `data/`, `domain/`, `intelligence/`, `risk_execution/`,
  `observability/`, `research/`, `shared/`), each an empty, isolated
  Python package.
- **ADR-6**: an automated, tested import-graph isolation checker
  (`shared/arch_lint/`) enforcing the plane-boundary rules from Stage 2/3
  — e.g. `research` can never import `risk_execution`.
- **Every Stage 3 §2 domain model** (`domain/models/`) as typed, validated,
  immutable-where-specified data structures, with deterministic
  serialization.
- 112 unit/adversarial tests, all passing (see `docs/implementation-log.md`
  for the exact run).

## What does NOT exist yet (deliberately)

Historical data ingestion, feature engineering, the momentum baseline
strategy, the Cost Model, the Risk Engine, the order state machine's
broker-facing side, the Research/backtesting harness, any LLM component,
and self-improvement of any kind. See `docs/slice-status.md` for the exact
boundary and `docs/05-Stage3-Detailed-Technical-Design-v0_1.md` §21 for the
full planned slice sequence.

## Running things locally

```bash
# Install (editable, with dev extras: pytest, ruff, mypy)
pip install -e ".[dev]"

# Run tests
pytest -v
# or, without pytest installed:
python -m unittest discover -s tests -p "test_*.py"

# Run the ADR-6 import-isolation check (this is also run in CI)
python -m shared.arch_lint.cli .

# Lint / format / type-check
ruff check .
ruff format --check .
mypy domain shared
```

No broker, market-data provider, or LLM credentials are required for
anything in this repository yet — see `docs/dependency-decisions.md`.
