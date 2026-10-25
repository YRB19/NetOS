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

**ADR-10 (architecture decision, Slice 7): order lifecycle & reconciliation packages, and the `simulation/` audit.**
Problem: order-event handling and multi-ledger reconciliation need a home that cannot manufacture approvals, orders or fills,
and the `simulation/` bridge (ADR-9) had to be re-checked against "research never imports execution". Findings: nothing
imports `simulation`; `research` imports neither `risk_execution` nor `simulation`; ADR-9 stands unchanged. Decision: new
`risk_execution/order_lifecycle` and `risk_execution/reconciliation`, extending (not duplicating) the domain `Order` state machine
and the Slice 6 reconciler; forbidden-import rules added in `shared/arch_lint/rules.py` (lifecycle/reconciliation -> risk engine, sizing,
research, simulation, intelligence, governance, data adapters; risk engine/sizing/broker -> lifecycle/reconciliation; lifecycle ->
reconciliation). No rule was weakened. Open (needs operator approval): `ACKNOWLEDGED -> CANCELLED` contract edge.

**ADR-11 (architecture decision, Slice 7 closure): add `ACKNOWLEDGED -> CANCELLED` to the Order contract.**
Problem: confirmed cancellation of a resting, entirely unfilled order had no legal transition (the Stage 3 §9 diagram only draws a cancel
edge after a partial fill), while Stage 1 FR-3 (Must) and the Stage 3 §10 broker interface require cancellation. Options: (a) keep the
contract and escalate every such cancel to RECONCILIATION_REQUIRED (safe but makes the normal cancel path a halt); (b) add the single
edge for broker-confirmed cancels (chosen); (c) also allow SUBMITTED/APPROVED -> CANCELLED (rejected: no acknowledgement evidence).
Consequences: domain table + simulated broker + lifecycle `_on_cancel` updated; the Slice 6 test that asserted the old behaviour was
superseded (rationale in its docstring); late fills after a confirmed cancel remain quarantined + halted. Invalidated if the operator
rules the diagram authoritative as-is (revert the one edge; every other mechanism is unchanged).

**ADR-12 (architecture decision, Slice 7 closure): explicit atomic file checkpoint for the order lifecycle.**
Problem: snapshot/restore alone did not demonstrate restart safety. Decision: `risk_execution/order_lifecycle/checkpoint.py` — one JSON file,
temp-file + fsync + `os.replace`, mandatory write-ahead checkpoint before any broker call, restore validates version/checksum/request
identity/history, recovery reconciles against retained broker state by client key and never re-sends. No database, queue or third-party
dependency. Limits and unsupported crash windows are listed in docs/order-state-machine-reconciliation.md §12.

**ADR-13 (architecture decision, Slice 7 final closure): idempotent portfolio settlement with its own atomic checkpoint.**
Problem: the crash window between booking a fill in `ResearchPortfolio` and `mark_portfolio_applied` could double-book a fill, and the
portfolio could not be restored. Decision: `ResearchPortfolio.apply_fill` keyed by `fill_id` with a payload fingerprint and an applied-fill
ledger, committed together with the financial state in one checksummed JSON file (`research/harness/portfolio_checkpoint.py`, same
temp-file/fsync/`os.replace` convention as ADR-12, duplicated rather than imported because `research/` must not import `risk_execution/`),
plus `simulation/settlement.apply_pending_fills`. Alternatives rejected: remembering processed fills only in the lifecycle manager (cannot know
whether the portfolio effect was booked); a database or queue (not justified at this scale). One additive `FailureCategory`
(`PORTFOLIO_CHECKPOINT_ERROR`). No new dependency. Limits: docs/order-state-machine-reconciliation.md §12a.

**ADR-14 (architecture decision, Slice 8): durable hash-chained decision journal; additive contract changes only.**
Problem: decisions were only exported at end of run (`decision_records.jsonl`), HOLD/no-trade/skipped outcomes had no canonical
record, and `RiskCheckResult` kept only prose. Options: (a) rival decision model (rejected: Stage 3 §4 names one); (b) add fields to
`DecisionRecord` (rejected: would change every existing artifact byte-for-byte and break reproducibility of old runs); (c) additive
`TerminalState` members + typed journal events carrying the extension data (chosen). Decision: stdlib JSONL journal in
`observability/decision_log/`, per-run stream, sequence + SHA-256 chain, fsync'd append, fail-closed reopen, required (not optional)
in `PipelineHarness`; `RiskCheckResult.evidence`/`evaluable` captured at evaluation time; `FailureCategory.JOURNAL_FAILURE`;
`OrderLifecycleManager.halt_external`. No new dependency, database or service. Consequences: every run needs a journal factory (existing
tests use a test-only in-memory subclass); runs write `journal_ref.json`. Invalidated if multi-process writers are needed (would require a
locking/transactional store) or if the operator rules a new field on `DecisionRecord` preferable (a migration reader is then required).
