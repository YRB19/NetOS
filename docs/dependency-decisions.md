# Cumulative dependency decisions

Runtime remains standard-library-only. No unrelated dependency upgrades or new
runtime libraries were introduced. The existing development extras are pytest,
ruff and mypy; setuptools remains the existing build backend. Newly introduced
`shared.costs` and `risk_execution.broker.adapters` are explicitly included in
packaging. Development tools were installed into an external staging virtualenv.

The pure Decimal calculator resides in `shared/costs` so research can use it
without importing execution. Domain contracts may import pure shared time and
identifier utilities; Slice 4's standalone ban on all domain→shared imports was
incompatible with every earlier slice and has been narrowed accordingly.

The architecture checker combines all remaining slice restrictions, plus cycle
checks. Both historical script entry points delegate to it. Historical dependency
reports are preserved under `history/slice*/dependency-decisions.md`.

## Slice 4.5A
No dependency added or changed. Runtime stays stdlib-only. pytest was needed only to run 3
fixture-based tests; it was borrowed from the uploaded venv's pure-Python packages via
PYTHONPATH for verification, not added to the project. Renamed
`normalizer.NormalizationResult` -> `AlternateNormalizationResult` (internal only).

## Slice 5
No dependency added or changed; runtime stays stdlib-only (`decimal`, `json`, `bisect`,
`dataclasses`). The research tree is statically checked to import no broker SDK and no
network library (`tests/adversarial/test_research_lookahead.py`). pytest remains unavailable
in this sandbox; new tests are `unittest.TestCase` so they run under both runners.

## Slice 6
No third-party dependency added; runtime stays stdlib-only (`decimal`, `dataclasses`, `bisect`, `calendar`).
Execution path statically checked to import no network library, broker SDK, secret store, `random`, or
wall-clock calls (`tests/adversarial/test_slice6_isolation.py`).

**ADR-9 (architecture decision): new leaf package `simulation/`.** Problem: Slice 6 requires the research
pipeline to run strategy -> risk -> sizing -> broker, but the Slice 5 rule `research -X-> risk_execution`
(Stage 2 §11/§16) must stay: the research environment may never reach execution code. Options: (a) let
`research` import `risk_execution` (rejected — removes the most safety-critical boundary); (b) put the
orchestrator in `risk_execution` (rejected — Plane 3 would depend on research); (c) a separate leaf package
that may import both (chosen). Rules added in `shared/arch_lint/rules.py`: nothing may import `simulation`; it may
not import concrete strategies, LLM, data adapters or governance; `risk_execution` may not import research,
simulation or adapters; risk/sizing/broker may not import each other. Reuses `ResearchHarness` internals
(`_RunState`, `_invoke`, `_validate_candidates`, `_marks`, `_assemble`) by subclassing. Invalidated if a
later slice moves orchestration under a governed deployment boundary.

Additive changes to existing code: `FailureCategory` += `BROKER_REJECTED`, `RECONCILIATION_REQUIRED`,
`SIZING_REFUSED`; `simulation` registered in the checker, graph and `pyproject.toml`.
