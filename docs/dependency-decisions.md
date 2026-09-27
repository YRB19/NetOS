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
