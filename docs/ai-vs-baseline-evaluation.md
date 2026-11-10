# AI vs baseline evaluation (Slice 12)

**Status: COMPLETE as an evaluation framework; the AI question itself is UNANSWERED (Outcome B, evidence capped).**
Slice 12 is an evaluation stage. It promotes nothing, enables no live path, changes no risk threshold and no autonomy
level. Everything measured here is **synthetic data with offline-fixture signals**: it verifies the evaluation
machinery, and says nothing about markets or about any AI model.

## 1. What was built

| Piece | Location | Role |
|---|---|---|
| Frozen spec + registry | `research/ai_eval/spec.py` | Hypothesis, null, thresholds, windows, seeds; write-once, hash-frozen before any run |
| Point-in-time / provenance audit | `research/ai_eval/pit_audit.py` | Per-signal gate; exclusions are logged, never repaired |
| Attribution + AI metrics | `research/ai_eval/attribution.py` | Incremental trades, coverage, direction distribution, information-content diagnostic |
| Statistics | `research/ai_eval/stats.py` | Seeded paired block bootstrap, Bonferroni-adjusted level; identical paths reported as such |
| Outcome classifier | `research/ai_eval/decision.py` | Outcome A–D by fixed rules in a fixed order |
| Artifact + report | `research/ai_eval/report.py` | JSON artifact, 13-section Markdown report, credential scan (fail-closed) |
| Record/replay providers | `model_providers/replay.py` | Capture raw responses; replay them with no network and no invention |
| Orchestrator | `tools/ai_vs_baseline.py` | Runs all arms through the real simulated pipeline (outside the planes) |
| Synthetic scenario | `tools/ai_vs_baseline_synthetic.py` | `python3 -m tools.ai_vs_baseline_synthetic <dir>` |

`research/ai_eval/` is a pure analysis layer: no execution, risk, governance, broker, provider or network imports
(enforced by a test). Orchestration lives in `tools/` because it must touch both the pipeline and the analysis layer.

## 2. Experimental hypothesis and frozen protocol

- **Hypothesis:** the bounded AI confidence adjustment gives a net-of-cost return difference vs Tier-2 whose adjusted CI lies above the minimum economic effect.
- **Null (credible):** the AI component does not provide statistically or economically meaningful incremental value over the deterministic baseline.
- **Primary metric (fixed in code):** `net_return_difference_ai_minus_tier2`. Secondary: max drawdown, total costs, turnover/capital, per-cycle Sharpe, incremental trades.
- **Windows:** development < configuration-selection < confirmatory, strictly ordered and non-overlapping (validated). No configuration selection was performed; defaults were frozen before the run.
- **Thresholds** (min effect, drawdown regression, cost increase, coverage, min signals, min cycles) are researcher-supplied with **no defaults**. The values in the synthetic spec are labelled EXAMPLE.
- **Gate:** `run_evaluation` refuses an unfrozen spec, a spec changed after freezing, a spec frozen after the start time, and any drift between the spec and the live configuration (Tier-2 config, adjustment config, prompt template/hash, output schema, cost schedule, confirmatory window).
- Each run exposes the confirmatory window in the holdout registry; a second exposure is flagged and the run is non-confirmatory.

## 3. Strategies and ablation arms

Tier-1 (equal-weight buy-and-hold), Tier-2 (12–1 momentum, existing config authoritative), and Tier-2 + overlay in:
`TIER2_AI_DISABLED`, `TIER2_AI_NEUTRAL`, `TIER2_AI_ENABLED`, `TIER2_AI_UNAVAILABLE`, plus one `TIER2_AI_ENABLED@max_delta=m` arm per tested magnitude (0.05, 0.1, 0.2). All share data, universe, window, capital, the shared verified cost schedule and NEXT_BAR_OPEN execution. Every arm is a ledger trial (STARTED → TERMINAL); a failed arm is recorded and the evaluation continues.

## 4. Point-in-time restrictions (per signal)

Blocking, coded exclusions: snapshot id missing/mismatched (expected id comes from the baseline candidate, never from the signal), unknown document, document unavailable at decision time, published after decision, inconsistent timestamps, unusable status, model cutoff undeclared or overlapping the decision, provider-returned model id unresolved (non-fixture), outside the confirmatory window, schema/prompt mismatch, duplicate and contradictory-duplicate signals. Eligible signals only are placed in each arm's signal store, so an excluded signal cannot influence a decision. A journal-side detector additionally counts any `AI_SIGNAL_EVALUATED` with `applied=true` whose key is not eligible; **any such event forces Outcome D**. Run-level finding: model-identifier drift.

## 5. Provider provenance

Signals are classified `OFFLINE_FIXTURE` (stub), `LIVE_CAPTURED` (real provider, completed at/before decision time), `RETROSPECTIVE_REPLAY` (real provider run after the decision on old documents, **not** point-in-time evidence), or `NO_PROVIDER_OUTPUT`. Raw responses are captured by `RecordingProvider` (no credentials are ever captured) and replayed by `ReplayProvider`, which never calls a provider and raises `ProviderUnavailable` for an unrecorded request. Replay reproduces the recorded response; it is not a new model call. No historical AI output exists for any real period, so none is claimed.

## 6. Statistical methods and what was not done

Implemented: seeded paired circular block bootstrap of per-cycle return differences (AI arm − Tier-2); Bonferroni-adjusted confidence level over the tested magnitudes (3 comparisons → 98.33% per comparison at a 95% family level); a signal-level information-content diagnostic (direction-aligned next-cycle return with an iid bootstrap CI and hit rate); PBO via the existing Slice 9 CSCV implementation over the magnitude variants. **No p-values are reported.**
Not performed, with reasons recorded in the artifact: walk-forward (no model is fitted and no configuration is selected), regime segmentation of the AI comparison (identical paths carry no regime information), annualised return/volatility/Calmar (irregular cycle spacing, short sample: UNSUPPORTED), sector concentration (no sector data). PBO returned `INSUFFICIENT_SAMPLE` because the variant paths are identical.

## 7. Decision rules (frozen, applied in order)

R1 integrity breach → D. R2 evidence class below `REAL_DATA_LIVE_CAPTURED_PROVIDER_SIGNALS`, or not effectively confirmatory → **cap at B**. R3 power/coverage below the frozen minimums → B. R4 AI path identical to Tier-2 with zero incremental trades → C. R5 statistics unavailable → B. R6 harm (CI upper below −min effect, drawdown or cost regression beyond limits) → D. R7 adjusted CI lower bound above min effect → A. R8 CI upper below min effect → C. R9 otherwise B. Outcome A only supports further **paper** evaluation.

## 8. Findings of the synthetic run (`docs/slice12-synthetic-run-report.md`)

- **Outcome B**, evidence class `SYNTHETIC_DATA_OFFLINE_FIXTURE_SIGNALS`, effective confirmatory **False**.
- 210 offline-fixture signals, all eligible, 0 exclusions, 0 integrity breaches, coverage 50/50 of BUY/SELL candidates; 32 confidence adjustments applied.
- **All AI arms are identical to Tier-2** (net return 0.18950794, costs 1184.76, 6 trades; Tier-1 0.11478188). Cause, now measured rather than assumed: `confidence` is not an input to sizing or risk in this repository, so the overlay cannot change a trade by construction. This is a property of the Slice 11 contract, not a result about AI.
- Information-content diagnostic on synthetic uninformative labels: mean direction-aligned return 3.1e-05, CI [−0.0023, 0.0024], hit rate 0.5625, n = 32: consistent with no information, as designed.
- Synthetic prices rise monotonically, so drawdown/downside metrics are degenerate (0) and per-cycle Sharpe is not meaningful.

## 9. Limitations and promotion restrictions

Synthetic data and fixtures only; no real provider call; no real disclosures; no verified historical data; simulated execution with no market-impact model; arms share one run id by Slice 11 design (distinguished by arm label, overlay version id and journal events). The full `ResearchEvaluationService` confirmatory path (protocol registry, holdout policy REJECT) is not engaged because no confirmatory-grade dataset exists; the spec freeze, trial ledger and holdout exposure are used instead. **Nothing here permits promotion, live execution, unattended trading, or an autonomy change.**

## 10. What would be needed to leave Outcome B

1. A governed decision (ADR) on whether confidence may ever reach sizing; today the AI component has no mechanism to add value.
2. Real historical market data with a verified point-in-time universe.
3. Live-captured provider signals recorded at decision time with a documented model cutoff before the window.
4. Enough cycles/signals to meet the frozen power thresholds, and a frozen confirmatory window never exposed before.
