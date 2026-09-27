# NetOS

Cumulative Slices 1–4: domain contracts, historical data ingestion, feature context,
Tier-1 equal-weight buy-and-hold proposals, and a deterministic cost calculator.

## Setup and validation

Python 3.11 or newer; no runtime third-party dependencies.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check .
ruff format --check .
mypy domain shared
python -m shared.arch_lint.cli .
```

`python run_tests.py` also runs the full pytest suite. The CI workflow runs these checks.

## Structure and flow

- `domain/models/`: validated domain objects, serialization and order transitions.
- `data/adapters/`, `validation/`, `normalization/`: CSV ingestion, validation,
  split adjustment, deterministic versioning and JSONL persistence.
- `data/features/`: permitted universe and immutable, attributable feature snapshots.
- `intelligence/baseline/`: Tier-1 equal-weight BUY/HOLD/SELL advisory candidates.
- `shared/costs/`: Decimal cost inputs, versioned schedules and pure calculations.
- `shared/time/`, `versioning/`, `arch_lint/`: common utilities and architecture checks.
- `tests/`: cumulative regression coverage and a cross-slice integration test.
- `docs/`: design records, component contracts, source history and merge audit.

The primary historical path is `load_bhavcopy_csv` → `normalize_bhavcopy_batch`
→ JSONL persistence (optional) → `build_feature_snapshots`
→ `Tier1EqualWeightBuyHold.generate_candidate_trades`. All consumers use the same
canonical domain objects. The Slice 3 in-memory CSV API remains available for its
input format. `CostModel.estimate` accepts an explicit hypothetical quantity and
price; advisory strategy weights never become executable quantities automatically.

See [reconciliation](docs/slice-1-4-reconciliation.md),
[data ingestion](docs/data-ingestion.md), [feature context](docs/feature-context.md),
[Tier-1 baseline](docs/baseline-tier1.md), and [cost model](docs/cost-model.md).
The original Stage 0–3 specifications remain in `docs/`.

## Scope

Slice 5 has NOT been started. There is no live execution, broker connection,
risk engine, research harness, momentum strategy, LLM or self-improvement loop.
The included cost schedule is explicitly unverified; its original provenance
and status are retained in `docs/cost-model.md`.
