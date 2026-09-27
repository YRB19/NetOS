# Dependency Decisions

## Slice 2 (this session)

| Dependency | Decision | Why |
|---|---|---|
| `pytest` | **Not used — unavailable.** `pip install pytest` fails in this sandbox (no network access: "No matching distribution found for pytest"). | Stage 3 §22 anticipated this ("If additional test tooling such as pytest/ruff/mypy remains unavailable because the environment lacks network access, report that honestly"). |
| Python stdlib `unittest` | **Used** for all tests (`tests/**/test_*.py`), discovered and run via `run_tests.py`. | Zero additional dependencies required; ships with the Python 3.12.3 interpreter already present in this sandbox. Fully sufficient for this slice's test needs (assertions, fixtures via `setUp`, `assertRaises`, etc.). |
| `ruff` / `mypy` | **Not used — unavailable**, same network restriction as pytest. | No static-analysis/type-checking pass was run this session; this is a real gap, not a silent one. Should be run in an environment with network access before this code is considered fully vetted. |
| Python stdlib `csv`, `hashlib`, `json`, `dataclasses`, `datetime`, `ast`, `pathlib` | **Used** throughout (adapters, versioning, domain models, the import-graph checker). | All stdlib, zero install risk, matches Stage 2 §18's Python-ecosystem rationale. |
| A dedicated CSV-parsing/data-frame library (e.g. pandas) | **Not adopted.** | Not required at this slice's scale (a handful of fixture rows); stdlib `csv.DictReader` is sufficient and keeps the adapter's dependency footprint at zero. Revisit if/when Slice 3+ needs bulk numerical operations across large historical windows, where pandas' vectorized operations would earn their weight — that is a real, anticipated future need, not ruled out permanently. |
| A schema-validation library (e.g. pydantic) | **Not adopted**, per Stage 2 §18's original framing ("a low-stakes, easily reversible choice"). | Hand-rolled `__post_init__` validation on frozen dataclasses (`domain/models/`) is sufficient for the three domain objects this slice needs, and avoids a dependency to install in a network-restricted sandbox. |

## Carried forward from Stage 2 §22 (technology decisions, restated where relevant to Slice 2)

- Python 3.x — confirmed present (3.12.3) — no invalidating latency finding surfaced this
  slice.
- A relational database (Postgres-class) for domain-model records — **deferred**; Slice 2 uses
  the JSONL stopgap in `data/normalization/persistence.py` instead, exactly as Stage 3 §21
  Slice 2 anticipated ("If persistence is needed for this slice, keep it simple and
  deterministic").
- A time-series-friendly store for MarketData — **deferred**, unchanged from Stage 2's
  assessment; not needed at this slice's data volume.
