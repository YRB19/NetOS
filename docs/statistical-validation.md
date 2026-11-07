# Statistical validation & research validity (Slice 9, ADR-15..19)

Goal: NetOS can tell a valid research result from a contaminated, overfit, incomparable,
insufficiently sampled or unsupported one, keeps negative results, and reports uncertainty.
**Nothing here proves, or labels, a strategy profitable.** All evidence produced so far is
SYNTHETIC infrastructure evidence.

## 1. Protocol (`research/protocol/`)
`ExperimentProtocol` (schema `experiment-protocol-v1`) freezes: hypothesis, question, universe policy/versions, dataset id/version,
date range, split, strategy/benchmark versions, parameter space + trial budget, cost schedule, execution assumptions + unverified
elements, primary/secondary metrics + definitions version, structured `AcceptanceCriterion`s, negative-result definition, holdout id
+ reuse policy, `strategy_configured_through`, information horizon, embargo, regime set, links, and `supersedes_protocol_hash`.
Hash = `hash_json_stable(payload)`; the registration time is stored beside, not inside, the hash. `ProtocolRegistry.register`:
write-once per (id, version); same version + different content ⇒ `ProtocolConflict`; a change needs version n+1 that cites the prior
hash; `verify_registered_before(protocol, evaluation_started_at)` rejects unregistered, altered or retroactively registered protocols.
Confirmatory protocols must carry structured criteria, a declared horizon and a configuration cutoff. **No threshold is defaulted.**
Free-text rationale is never assessed; `assess_criteria` assesses only structured criteria, returns `INCONCLUSIVE` for unavailable
metrics, `ADVERSE` if an adverse criterion is met.

## 2. Trial ledger and holdout (`research/trials/`)
`TrialLedger`: append-only JSONL, fsync'd, sequence + prev-hash chain; `verify()` detects edits/removals of non-tail entries (tail
truncation is detectable only against an externally recorded `head_hash()`, which every report embeds). Outcomes: COMPLETED,
COMPLETED_WORSE_THAN_BASELINE, FAILED, INVALID_CONFIGURATION, REJECTED, INTERRUPTED, UNSUPPORTED, EXCLUDED_VALIDITY_FAILURE; non-completed
outcomes require a reason. It supplements (never replaces) `research/experiments/store.py`.
`holdout_id_for` hashes dataset id/hash, universe versions and test window — **not the protocol**, so a new protocol cannot make an
exposed holdout untouched. `HoldoutRegistry.expose`: any prior exposure (exploratory or confirmatory) ⇒ policy `REJECT` raises
(and is not recorded as a use) or `DOWNGRADE_TO_NON_CONFIRMATORY` records `REUSED_NON_CONFIRMATORY`. History is never erased.

## 3. Point-in-time (`research/contamination/point_in_time.py`)
Distinct times: event time (`MarketData.timestamp`), source availability (`VersionedObservation.available_at` + `AvailabilityBasis`),
ingestion (`MarketData.ingestion_time`, **never promoted** to availability), decision time. `MarketData` itself is unchanged (no
hash/artifact drift); availability is a sidecar provenance contract. Basis `UNKNOWN` carries no timestamp and is never backfilled.
`AvailabilityLedger.resolve(as_of)` returns, per (instrument, timestamp), the latest revision with `available_at <= as_of`; later
revisions and late-published bars cannot influence earlier decisions. Unknown availability ⇒ excluded and listed as
`UNVERIFIABLE` (policy EXCLUDE) or the run fails (FAIL); `clean_point_in_time_claim` is false. `ResearchHarness(availability=ledger)`
swaps in `PointInTimeReplay`, which gates `visible`, `bar_at`, `last_close_on_or_before` and cycle existence; the artifact's
contamination report gains `point_in_time` (without a ledger it states `UNVERIFIABLE`). The data version includes the ledger
fingerprint. The Slice 8 journal cannot be imported by `research/` (ADR-6); reports carry journal references as strings only.

## 4. Splits, walk-forward, purge/embargo (`research/splits/plan.py`)
Windows are inclusive. A train sample at t with information horizon H days and embargo E is allowed iff `t < test_start − (H+E) days`.
`purge_boundary` returns APPLIED / NOT_REQUIRED_JUSTIFIED (H=E=0 needs a written justification) / NOT_DECLARED (never assumed safe) plus
the excluded interval. `WalkForwardPlan` (EXPANDING/ROLLING) yields chronological, non-overlapping test windows (`step < test` rejected)
and a plan hash. `run_walk_forward` evaluates a **fixed** configuration per window (Tier-1/Tier-2 have no fit step; recorded as
`NOT_APPLICABLE_FIXED_CONFIGURATION`); per-window re-fitting is `UNSUPPORTED`. Expanding windows reuse earlier test windows as training
(flagged). No samples are dropped to improve a metric.

## 5. CSCV / PBO (`research/stats/pbo.py`)
Input: aligned T×N per-period returns of N trials. S even partitions (4 ≤ S ≤ 16, T divisible by S — otherwise UNSUPPORTED; no rows silently
dropped). For each of C(S,S/2) IS/OOS splits: n* = IS-best (MEAN_RETURN or SHARPE with sample sd; ties within 1e-12 ⇒ lowest index, counted);
ω = avg-rank_OOS(n*)/(N+1) (ascending, best=N); λ = ln(ω/(1−ω)); **PBO = share of combinations with λ ≤ 0**. Also reported: mean λ,
share with OOS loss, trial/period/combination counts, tie count. Identical candidates are collapsed and listed (the ledger keeps the true trial
count). UNSUPPORTED / INSUFFICIENT_SAMPLE (fewer than 2 trials, ragged/missing returns, bad S, zero-variance Sharpe, <2 obs per half) return
`pbo = None` with a reason. Floats with documented tolerance 1e-12 (statistics only; money stays Decimal). Hand-calculated tests: anti-persistent
set ⇒ PBO 1.0, mean λ = −5·ln2/6; persistent set ⇒ PBO 0, λ = ln 2. PBO is evidence about a testing setup, not a promotion rule.

## 6. Regimes (`research/stats/regimes.py`)
Required inputs (no defaults): lookback, thresholds, min_samples. TREND (RISING/FALLING/RANGE_BOUND on trailing cumulative return) and
VOLATILITY (HIGH/LOW on trailing sample sd) over a *constructed* equal-weight close index (not an official index). Labels at t use data ≤ t;
returns are attributed to the label at the period start. Too little history ⇒ UNCLASSIFIED; fewer than `min_samples` ⇒ INSUFFICIENT_SAMPLE
(no return shown). LIQUIDITY ⇒ `UNSUPPORTED` (no verified depth/spread data). Regime boundaries must be fixed before confirmatory analysis.

## 7. Metrics, costs, liquidation (`research/validity/metrics.py`, `assumptions.py`)
Every metric: `{value, status, unit, denominator, definition, reason}`; uncomputable ⇒ `None` + status, never 0. Added: final equity, net/gross
P&L, actual entry vs exit costs (reconciled to portfolio costs), cost drag (= actual costs / initial capital), turnover/capital, realized/unrealized,
max drawdown (fraction and INR, over the persisted equity curve; running-peak denominator), per-decision-cycle volatility (sample sd, n−1),
annualised volatility **only** with an explicit periods-per-year + justification, average/max exposure, counts, unique trial count,
baseline-relative return (same comparison fingerprint, else `NON_COMPARABLE`). **Terminal liquidation** is a separate, hypothetical estimate
(SELL at last mark, explicit selected schedule, optional ASSUMED slippage bps) and is never merged with booked costs; unavailable without marks.
Old metrics and cost schedules V1/V2 are untouched. Booked fills remain NEXT_BAR_OPEN with **no** modelled slippage, spread, impact,
liquidity limits or partial fills (disclosed as UNMODELLED); brokerage and some statutory scope remain unverified.

## 8. Dataset quality (`research/validity/quality.py`)
Warnings: MISSING_BARS, STALE_OBSERVATIONS, CORPORATE_ACTION_ADJUSTMENT_MISMATCH, IDENTITY_MAPPING_GAP, POSSIBLE_SURVIVORSHIP_BIAS (instrument dropped
between universe versions without a recorded delisting), SURVIVORSHIP_NOT_ESTABLISHED, SYNTHETIC_DATA, UNVERIFIED_HISTORY_SOURCE,
POINT_IN_TIME_NOT_VERIFIED, CORPORATE_ACTION_SOURCE_MISSING. Evidence class: SYNTHETIC_INFRASTRUCTURE / HISTORICAL_UNVERIFIED /
HISTORICAL_VERIFIED_FOR_STATED_CHECKS. The repository has no verified, survivorship-free historical Indian-equity dataset.

## 9. Report, verdicts, reproducibility (`research/validity/evaluation.py`)
`build_report` → verdict INVALID / UNSUPPORTED / EXPLORATORY_ONLY / INCONCLUSIVE / INFRASTRUCTURE_ONLY (synthetic) /
CONFIRMATORY_CHECKS_PASSED (historical-verified only); `profitability_claim` is always `NONE`. Embeds protocol id/version/hash/registration time,
holdout status, trial count + ledger head hash, contamination (incl. point-in-time), quality, criteria assessment, metrics, PBO, regimes,
walk-forward, purge report, run-artifact digest, data/cost/strategy/universe identities, journal reference strings, `report_hash`.
`write_report` never overwrites a different report. `reproduce_run` verifies the stored run directory (MISSING_ARTIFACT / CORRUPT_ARTIFACT),
requires caller-supplied inputs (MISSING_INPUT; nothing is fetched), checks the data snapshot version (INPUT_MISMATCH), re-runs and compares digests.

## 10. Remaining limitations
No verified historical dataset; datasets/universes are not persisted by the research store (callers keep them); Slice 8 settlement snapshots without
marks and `data_available_at` unknown records are not backfilled; the journal does not yet record research validity events (isolation rule);
re-fitting walk-forward, significance testing/Deflated Sharpe, and liquidity regimes are not implemented; slippage/spread/impact unmodelled;
brokerage unverified. pytest/ruff/mypy unavailable (unittest used).

## 11. Enforced evaluation workflow (Slice 9 closure, ADR-20)
Entry point: `research/validity/service.py::ResearchEvaluationService.evaluate`. The registries, `build_report` and the harness remain usable
independently, but **only this service enforces the combined contract**, and only `build_verified_report` can emit a confirmatory verdict.
Confirmatory order of operations: (1) write-ahead `STARTED` trial record (its ledger time is the authoritative evaluation start);
(2) `verify_registered_before` — protocol loaded from the registry, stored hash equals the supplied object, registered before that start;
(3) correspondence of frozen protocol to supplied config/strategy/baselines/universe versions/data range/dataset hash/cost schedule/fill assumption/
strategy cutoff/hypothesis/split and OUT_OF_SAMPLE period, plus ledger chain verification; (4) holdout identity recomputed from dataset hash +
universe versions + test window and compared with the protocol; (5) holdout exposure recorded per the frozen policy (REJECT blocks *before* the harness runs);
(6) harness run through its normal interface; run artifacts (success or failure) written; (7) post-run correspondence (data version, strategy, baselines, universes);
(8) terminal trial event (COMPLETED, COMPLETED_WORSE_THAN_BASELINE, FAILED, INVALID_CONFIGURATION, EXCLUDED_VALIDITY_FAILURE, REJECTED; INTERRUPTED on BaseException);
(9) report assembled from `EvaluationEvidence.verify()`, which re-derives protocol registration time, holdout exposure record, ledger chain, trial counts/head hash and
the run-artifact digest from durable stores. A mismatch before the run ⇒ trial `REJECTED`, nothing evaluated. Exploratory protocols may run with unverified correspondence,
but are labelled non-confirmatory.
**Trial lifecycle & denominator:** a logical trial = one `attempt_id` (START + TERMINAL events) or one legacy single-event entry; reported `trial_count` counts logical trials for
the protocol family (all versions); `event_count` is separate. `unresolved()` lists attempts whose latest event is STARTED; `recover_interrupted()` appends INTERRUPTED
(never edits, no result fabricated). **Durability limits:** single-process append with fsync; no file locking (concurrent writers unsupported); a crash between the START write and the
holdout write leaves an unresolved attempt with no exposure (conservative direction is not guaranteed in the opposite order: exposure is written after START and before the run);
a crash after the run but before the terminal event leaves an unresolved attempt whose run artifacts exist; tail truncation is detectable only against an externally held head hash.
**Report v2 semantics:** `research_validity_verdict` (alias `verdict`) answers only whether the controls support the stated evaluation claim: INVALID, UNSUPPORTED, EXPLORATORY_ONLY,
INFRASTRUCTURE_ONLY, CONFIRMATORY_CHECKS_PASSED. `criterion_outcome` (CRITERIA_MET / CRITERIA_NOT_MET / ADVERSE / INCONCLUSIVE) reports the structured criteria separately and is
`criterion_outcome_admissible_as_evidence` only when validity passed. `evidence_class` and `profitability_claim` (always NONE) are separate. `CONFIRMATORY_CHECKS_PASSED` does **not** mean
useful returns or that criteria were met. The legacy `build_report` records caller-supplied values as `LEGACY_UNVERIFIED` and can never grant confirmatory status.
Reports are stored per attempt: `validity/<run_id>/report-<attempt_id>.json`.


## Slice 11 note — model knowledge cutoff (ER-3)
`research/contamination/model_cutoff.py` classifies an evaluation as `EXPLORATORY_ONLY` when the test window starts on/before the model's declared knowledge cutoff, and `enforce_confirmatory` raises `CONTAMINATION`. An unknown cutoff is the sentinel `9999-12-31` and always fails closed. No cutoff date has been established for any real model. Any AI-enabled run is a research signal; no run in this repository shows that it improves risk-adjusted return (that is Slice 12's question).


## Slice 11 closure — model cutoff in the enforced path
`ResearchEvaluationService.evaluate` applies `assess_ai_model` to AI-enabled strategies only. Unknown/undeclared cutoff, unlinked or inconsistent model metadata, or a test window starting on/before the declared cutoff => `EXPLORATORY_ONLY` (reasons prefixed `AI_MODEL:`), persisted in the report as `ai_model_provenance`. Non-AI evaluations are unchanged. Declared cutoffs are operator-supplied and unverified. No AI-enabled run here is evidence that the signal improves returns.
