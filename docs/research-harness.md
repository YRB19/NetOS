# Research harness (Slice 5)

> **Status of this document:** describes infrastructure. A completed research run is **not**
> evidence that any strategy is profitable; a profitable backtest is **not** evidence of live
> profitability. All test fixtures are synthetic.

## Purpose

A deterministic, offline, isolated environment for replaying canonical historical `MarketData`
through a strategy, applying the shared Cost Model, keeping research-accounting portfolio
state, and persisting reconstructable results — including failures — so that strategies can
later be evaluated rigorously (ER-1…ER-8). Implemented: ER-1 (apples-to-apples comparison
mechanics only), ER-2 (declared strict split), ER-3 (basic temporal guards only), ER-5
(net-of-cost accounting), ER-8 (pre-registration *fields* required, **not assessed**).
Not implemented: ER-4 PBO/CSCV, ER-6 regime segmentation, ER-7.

## Architecture

```
research/
  harness/       config.py (identity, validation) · replay.py · runner.py · execution.py
                 portfolio.py · metrics.py · comparison.py · result.py · failures.py · jsonio.py
  contamination/ guards.py   (fail-closed temporal/split/universe/cost-schedule guards)
  experiments/   store.py    (file-based persistence; deterministic; never overwrites)
```

Reuses existing contracts — no competing schemas: `Experiment`, `EvaluationRun`,
`SplitSpec`, `ContaminationCheckResult`, `DecisionRecord`, `Fill`, `CandidateTrade`,
`FeatureSnapshot`, `PermittedUniverse`, shared `CostModel`/`ScheduleRegistry`.

## Research environment boundary

`research/` may import `domain`, `data.features/validation/normalization`, `intelligence`,
`shared`. It must not import `risk_execution`, `governance`, `data.adapters`,
`observability`, any broker SDK or any network library. Enforced by the ADR-6 import-graph
checker (0 violations) plus `tests/adversarial/test_research_lookahead.py`
(`ResearchHarnessSourceIsolationTests`: AST scan of `research/` for broker/network imports).
The harness holds no credentials, no broker handle and no governance handle, performs no
network I/O, and writes only to the artifact directory it is given.

## Replay sequence (per decision timestamp `t`)

Decision timestamps = distinct observation timestamps within the evaluation window
(non-trading days therefore produce no cycle).

0. Settle pending orders from earlier cycles at the **open of the bar at `t`** (NEXT_BAR_OPEN);
   cost-estimate; update portfolio.
1. Load observations available at `t` — `replay.visible(t)` returns timestamp ≤ `t` only.
2. Validate temporal availability (guards: no observation > `t`, none > window end, universe
   effective ≤ `t`).
3. Build `FeatureSnapshot`s as of `t` (universe in force at `t` plus instruments just removed).
4. Validate snapshots (stamped `t`; sources ≤ `t`), then invoke the strategy.
5. Validate returned `CandidateTrade`s (list, correct snapshot, timestamp, version,
   one per instrument, BUY only inside the universe in force).
6. Mark the portfolio to market at the close of `t`.
7. Translate candidates to pending simulated orders sized from equity at `t`.
8. Record decision traces, `DecisionRecord`s (for fills) and the equity-curve point.

Steps 1–5 never see a bar later than `t`. Fills never look ahead: an order is filled at the
first cycle where the instrument has a bar strictly after the decision time — the bar is
consumed only when the loop reaches it. Orders unfilled when the window ends are recorded
as `UNEXECUTED_END_OF_WINDOW` (no data beyond the window is ever consumed).

### Defined data behaviours

| Situation | Behaviour |
| --- | --- |
| Duplicate (instrument, timestamp), even across sources | run FAILS (`DUPLICATE_DATA`) |
| Non-`MarketData` / non-UTC record | run FAILS (`INVALID_DATA`) |
| Universe instrument with no data at all | run FAILS (`MISSING_DATA`) |
| Empty data / no observations in window | run FAILS (`MISSING_DATA`) |
| Instrument without a bar at `t` (not held) | snapshot is incomplete → strategy sees missing/stale data; no forward-fill. `max_staleness_days` (default 0) is explicit config |
| Held instrument without a bar at `t` | run FAILS (`MISSING_DATA`) unless `carry_forward_marks=True` (explicit; recorded per cycle in `carried_marks`) |
| Non-trading day | no cycle |
| No universe in force at first cycle | run FAILS (`MISSING_DATA`); never back-filled |

## Execution assumption (`NEXT_BAR_OPEN`, the only supported value)

Fill at the **open** of the instrument's next observation after the decision time. Whole
shares only, no partial fills, no slippage beyond the open-vs-prior-close gap, no market
impact, no volume cap, no price limits/halts. Delivery only (intraday square-off is not
modelled; configuration is rejected). **Not equivalent to live execution.**

## Quantity translation (research accounting, not a sizing engine)

`target = size_hint × equity_t × (1 − allocation_cash_buffer)`; BUY qty = `floor((target −
current value)/close_t)`; SELL qty = `held − floor(target/close_t)` (`size_hint == 0` ⇒ sell
all). Integer floor only; residual cash stays cash. Within a cycle SELLs are processed before
BUYs. A second order for an instrument that still has an unfilled order is rejected
(`REJECTED_PENDING_ORDER_EXISTS`).

## Portfolio accounting

`ResearchPortfolio` (Decimal): cash, integer positions, cost basis, realised/unrealised gross
P&L, cumulative costs and turnover. Costs are deducted from cash, so equity reflects them.
BUY needs turnover + costs ≤ cash; SELL ≤ held. Violations raise categorised failures;
`order_rejection_policy` (default `FAIL_RUN`) chooses between failing the run and recording
a rejection and continuing. No margin, leverage, risk limits or kill switch — that is the
future Risk Engine, deliberately not here.

## Cost integration

`ResearchConfig.cost_schedule_version` is **required** (no default, never "latest"). Both
`india-equity-v1-unverified` and `india-equity-v2-2026-03-verified` run; the version is in
every result, artifact, trade's `CostEstimate`, and in experiment identity. A schedule with an
`effective_date` after the window start is refused (`CONTAMINATION`) unless
`acknowledge_future_cost_schedule=True`. (Note: the registry's V1 has no effective date.)

## Benchmark comparison

`run_with_baseline()` runs candidate and baseline under the identical configuration;
`compare_runs()` refuses unless `comparison_fingerprint` matches (data snapshot, universe
schedule, window, capital, cost schedule, execution assumptions, buffer, staleness, feature
set). Both must have COMPLETED; both are net of costs. No significance test is computed
(`statistical_significance: NOT_ASSESSED`).

## Identity, reproducibility

`experiment_id = "exp_" + SHA-256(canonical{config, strategy_version, baseline ids, data
snapshot version, universe schedule})[:32]`; `run_id` = hash of `experiment_id` + harness
version. No wall-clock, hostname or path enters identity. `created_at` lives only in
`meta.json` (and is excluded from the deterministic digest); `Experiment.created_at` is also
kept out of the deterministic files. Re-running yields byte-identical deterministic files
(tested). Order ids and decision ids are hashes of run identity.

## Artifact persistence (`<root>/runs/<run_id>/`)

`experiment.json`, `result.json`, `decisions.jsonl`, `trades.jsonl`, `rejections.jsonl`,
`equity_curve.jsonl`, `decision_records.jsonl`, `evaluation_run.json` (when applicable),
`failure.json` (iff FAILED), `meta.json` (non-deterministic metadata only). A write that would
change existing deterministic content raises `ArtifactConflict`; failures are never overwritten.

## Failure handling

Anticipated failures raise `ResearchRunFailure(category, …)` and become a FAILED result with a
`ResearchFailureRecord` (category, message, decision timestamp, context) and `failure.json`;
metrics are `None`, so a failed run cannot be mistaken for a result. Unexpected exceptions
become `UNEXPECTED_ERROR` (strategy exceptions become `STRATEGY_ERROR`). Partial decision
traces up to the failure are preserved. Categories: INVALID_CONFIGURATION, INVALID_DATA,
MISSING_DATA, DUPLICATE_DATA, CONTAMINATION, STRATEGY_ERROR, INVALID_CANDIDATE,
INSUFFICIENT_CASH, INSUFFICIENT_POSITION, MISSING_EXECUTION_PRICE, ACCOUNTING_ERROR,
UNEXPECTED_ERROR.

## Contract notes / incompatibilities recorded (nothing changed in domain)

* `EvaluationRun` requires `passed_pre_registered_criteria: bool`. The harness cannot assess
  free-text criteria, so it stores `False` and sets `criteria_assessment = "NOT_ASSESSED"` in
  `result.json`. **`False` there means "not assessed", not "failed".**
  `pbo_cscv_correction_applied=False` and `regime_segmented_results={}` likewise mean not done.
* `SplitSpec` has a mandatory validation window; a two-way split is encoded with
  `validation_start == validation_end == train_end` (`two_way_split()`), treated as empty.
* `DecisionRecord` has no terminal state for HOLD-with-candidate or simulated rejections
  (`NO_CANDIDATE` forbids a candidate id). Canonical `DecisionRecord`s are therefore emitted
  for **fills only** (`FILLED`, autonomy level 0, risk-rule version
  `NOT_APPLICABLE_RESEARCH_HARNESS_NO_RISK_ENGINE`); every decision (incl. HOLD, rejection)
  is in `decisions.jsonl`. Proposed for a future design review, not changed here.
* `CandidateTrade.size_hint` for SELL is interpreted as target allocation (0.0 = exit),
  matching Tier-1.

## Known limitations

* `MarketData.ingestion_time` is pipeline provenance and is NOT used to gate availability;
  point-in-time availability is by observation `timestamp` only. Late-published or revised
  data is not modelled. Corporate-action adjustment is Plane 1's job; the harness does not
  check `adjusted` consistency.
* Fill at next open ignores gaps beyond the buffer, liquidity, halts, circuit limits.
  A modest `allocation_cash_buffer` (default 1%) can still be exceeded by a gap-up ⇒ default
  `FAIL_RUN`.
* Metrics are mark-to-market and unliquidated: exit costs are not deducted
  (`exit_costs_included: false`). Costs use the schedule's single NSE-specific rate set;
  brokerage is the unverified assumption documented in `cost-model.md`.
* Per-cycle `compute_market_data_snapshot_version(visible)` is O(N) per cycle: fine for
  fixtures, will need an incremental approach for large histories.
* No regime segmentation, PBO/CSCV, Sharpe-family metrics, significance, or walk-forward
  re-fitting. Contamination guards are basic; they do not detect model-knowledge-cutoff
  leakage (needed when an LLM component exists).
* `strategy_configured_through=None` is accepted (e.g. zero-parameter Tier-1) and recorded as
  `strategy_configuration_declared: false` — it is a declaration, not a verification.
* Only the Tier-1 baseline and test-only strategies have been run, on synthetic data.
