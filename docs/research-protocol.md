# Research protocol — minimum for a valid research run (Slice 5)

A run is valid only if every item below is explicit in the `ResearchConfig` /inputs and
recorded in the artifact. The harness refuses (FAILED artifact) rather than guessing.

| # | Element | How it is specified | Recorded in |
| --- | --- | --- | --- |
| 1 | Data snapshot | canonical `MarketData` list; `data_snapshot_version` is computed from it | `experiment.json` |
| 2 | Strategy version | `strategy.strategy_version_id` (required, non-empty) | `experiment.json`, every trade/decision |
| 3 | Feature version | `feature_set_id` (default Tier-1 context set) | `experiment.json` |
| 4 | Universe | explicit schedule of `PermittedUniverse` (versioned, `effective_from`) | `experiment.json` |
| 5 | Cost schedule | `cost_schedule_version`, REQUIRED, never defaulted | everywhere incl. each `CostEstimate` |
| 6 | Date range | `SplitSpec` (train / [empty] validation / test) + `evaluation_period` | `experiment.json` |
| 7 | Initial capital | `initial_capital`, REQUIRED, positive, INR, ≤ 2 dp, Decimal/int/str (floats rejected) | `experiment.json` |
| 8 | Execution assumptions | `execution_assumption` (`NEXT_BAR_OPEN`), `allocation_cash_buffer`, integer shares, `order_rejection_policy`, `carry_forward_marks`, `max_staleness_days` | `experiment.json` config |
| 9 | In/out-of-sample split | windows strictly separated (shared instant = overlap); OOS requires `strategy_configured_through` < test start if declared | `result.json` contamination_report |
| 10 | Contamination requirements | all guards pass: split separation, configuration cutoff, cost schedule not from the future (or explicitly acknowledged), no observation > decision time or > window end, snapshots stamped `t`, universe effective ≤ `t` | `result.json`, `evaluation_run.json` |
| 11 | Pre-registration | non-empty `hypothesis` and `pre_registered_criteria` (stored; **not assessed** by the harness) | `experiment.json` |

## Rules

1. Define criteria (including what counts as a negative result) **before** looking at results.
2. Keep failed and negative runs; they are first-class artifacts and are never overwritten.
3. Compare only via `compare_runs` / `run_with_baseline` (identical fingerprint, net of costs).
4. Choosing a window, universe or parameters after seeing results voids an out-of-sample
   claim. The harness cannot detect that; declare `strategy_configured_through` honestly.
5. A completed run, a good metric, or a baseline comparison is **not** evidence of profitability,
   validated alpha, or readiness for paper/live use. Multiple-testing correction (ER-4),
   regime-segmented reporting (ER-6) and model-cutoff contamination checks are not yet
   implemented, so no claim of skill may rest on this harness alone.
6. Re-run reproducibility check: same inputs ⇒ identical deterministic artifact digest
   (`digest_of_run_dir`).

## Slice 9 addendum
Free-text pre-registration is superseded for confirmatory runs by `ExperimentProtocol` (docs/statistical-validation.md §1): frozen, hashed, registered before
evaluation, structured criteria only. Exploratory runs are labelled; a reused holdout is never confirmatory.
