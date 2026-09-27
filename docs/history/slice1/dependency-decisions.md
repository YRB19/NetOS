# Dependency Decisions — Slice 0 + Slice 1

Per the implementation prompt's "TECHNOLOGY DISCIPLINE" section: nothing
below was adopted for a capability not required by the current slice.
Several categories are explicitly deferred, not chosen.

## Runtime dependencies

**None.** `domain/models/` and `shared/` use only the Python standard
library: `dataclasses`, `enum`, `datetime`, `typing`, `uuid`, `hashlib`,
`ast`, `pathlib`, `types.MappingProxyType`. This is deliberate — typed,
validated, immutable data structures do not need a schema/validation
library (e.g. Pydantic, attrs) at this scale, and adding one now would be
exactly the "speculative abstraction" / "unnecessary dependency" the
prompt warns against. `pyproject.toml`'s `dependencies = []` reflects this.

If a future slice's domain-model needs grow past what dataclasses +
`__post_init__` validation can comfortably express (e.g. cross-field
validation shared across dozens of models, or a need for JSON Schema
generation), that would be a concrete, evidence-based reason to revisit
this — not a reason to add one preemptively now.

## Dev dependencies (`[project.optional-dependencies].dev`)

| Dependency | Why |
|---|---|
| `pytest` | Standard, minimal-friction test runner; also runs `unittest.TestCase`-based tests natively (which is what this slice's test suite is written as — see note below), so adopting it costs nothing today and pays off once fixtures/parametrization are needed later. |
| `ruff` | Single-binary lint + format tool; replaces what would otherwise be separate flake8/black/isort dependencies with one. Chosen for minimal footprint, not for any feature unique to this slice. |
| `mypy` | Type checking for the typed domain models. Configured as advisory (`continue-on-error: true`) in CI for this slice — not yet a hard gate, since Slice 1 hasn't been run through a real mypy pass in an environment with network access to install it (see "Verification environment note" below). |

## Explicitly deferred (not selected, per the prompt's instruction)

Broker SDK, production market-data provider, LLM provider/SDK, LangGraph
or any agent-orchestration framework, TradingAgents, Paperclip, a
production database, Kubernetes, cloud infrastructure, a message queue, a
vector database. None of these are needed by Slice 0/1's scope
(repository scaffolding + domain models), and Stage 3 §18/§22 already
defers most of these to later slices or to Stage-3-identified open
questions (e.g. broker selection is blocked on REG-6 closure).

## Verification environment note

The sandbox this implementation was built in has **no network access**, so
`pytest`, `ruff`, and `mypy` could not actually be `pip install`-ed or run
here, despite being declared as dev dependencies. To avoid claiming a test
run that didn't happen, the test suite (`tests/unit/`, `tests/adversarial/`)
was written using `unittest.TestCase` (pure standard library) so it could
be **actually executed** in this environment via
`python -m unittest discover -s tests -p "test_*.py"` — see
`implementation-log.md` for the exact, real output (112 tests, all
passing). `unittest.TestCase` classes are natively collected and run by
`pytest` with no changes required, so `pytest -v` will run the identical
suite once dependencies are installed in an environment with network
access (e.g. CI, or a developer's machine) — this is asserted, not
verified in this session, and is called out explicitly rather than implied.

`ruff` and `mypy` were **not** run in this session for the same reason.
The code was manually checked for the most common ruff findings (unused
imports — a lightweight AST-based scan found and fixed one real instance
in `domain/models/portfolio.py`) but a real `ruff check` / `mypy` pass has
not happened yet. This should be treated as an open item for the first
session with network access, not as "done."
