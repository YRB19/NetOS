# AI vs Baseline Evaluation — slice12-synthetic-ai-vs-tier2 v1

## 1. Executive summary

**Outcome B: Inconclusive (AI component remains experimental).**

Evidence class: `SYNTHETIC_DATA_OFFLINE_FIXTURE_SIGNALS`. Effective confirmatory: **False**.

- Net return: AI-enabled Tier-2 0.189508, Tier-2 0.189508, Tier-1 0.114782 (all net of the same verified cost schedule).
- 32 confidence adjustment(s) were applied; trades differing from Tier-2: 0 added, 0 removed.
- Confidence adjustments reached no sizing/risk input in this repository, so the AI arm is mechanically unable to change simulated outcomes; the equity paths are identical by construction.
- Evidence class measured: SYNTHETIC_DATA_OFFLINE_FIXTURE_SIGNALS. This is NOT confirmatory-grade evidence.

## 2. Experimental design

- Hypothesis: SYNTHETIC infrastructure check: the bounded AI confidence adjustment yields a net-of-cost return difference vs Tier-2 whose adjusted confidence interval lies above the minimum economic effect.
- Null: The AI component does not provide statistically or economically meaningful incremental value over Tier-2.
- Alternative: The AI-augmented Tier-2 has a higher net return than Tier-2 by more than the minimum economic effect.
- Primary metric: `net_return_difference_ai_minus_tier2`; secondary: max_drawdown, total_costs, turnover_to_capital, cycle_sharpe, incremental_trades
- Frozen spec hash: `39fa2f266629e55ab621bf55c9db1803359bec3ae9e93b12a7451e3d3af870c0`; decision rules `ai-eval-decision-rules-v1`
- Windows: development ['2025-03-03T10:00:00+00:00', '2025-12-31T10:00:00+00:00'], selection ['2026-01-01T10:00:00+00:00', '2026-03-30T10:00:00+00:00'], confirmatory ['2026-04-01T10:00:00+00:00', '2026-08-29T10:00:00+00:00']
- Cost schedule `india-equity-v2-2026-03-verified`; execution NEXT_BAR_OPEN; rebalance monthly (Tier-2 default)
- AI: provider `STUB`, requested model `stub-model-v1`, prompt `disclosure_classification_prompt_v2`, schema `disclosure_interpretation_v1`; seed 20260901
- Acceptance: min effect 0.002, max drawdown regression 0.01, max cost increase 0.10, min coverage 0.8, min signals 30, min cycles 26

## 3. Data quality and coverage

- bars: 780
- instruments: 10
- first_bar: 2025-03-03T10:00:00+00:00
- last_bar: 2026-08-24T10:00:00+00:00
- sources: ['SYNTHETIC']
- origin: SYNTHETIC
- survivorship_and_revision_data: UNAVAILABLE for the synthetic dataset

## 4. Point-in-time validation

```json
{
  "by_provenance": {
    "OFFLINE_FIXTURE": 210
  },
  "eligible": 210,
  "excluded": 0,
  "exclusions_by_reason": {},
  "signals_audited": 210
}
```
Run-level findings: none. Applied-but-ineligible signals (integrity breaches): **0**.

## 5. Strategy comparison

| Arm | Net return | Net P&L | Costs | Turnover/capital | Trades | Max DD | Cycle Sharpe (not annualised) |
|---|---|---|---|---|---|---|---|
| TIER1 | 0.114782 | 114781.88 | 1175.44 | 0.989904 | 10 | 0.000000 | 13.939101 |
| TIER2 | 0.189508 | 189507.94 | 1184.76 | 0.997763 | 6 | 0.000000 | 7.553510 |
| TIER2_AI_DISABLED | 0.189508 | 189507.94 | 1184.76 | 0.997763 | 6 | 0.000000 | 7.553510 |
| TIER2_AI_NEUTRAL | 0.189508 | 189507.94 | 1184.76 | 0.997763 | 6 | 0.000000 | 7.553510 |
| TIER2_AI_ENABLED | 0.189508 | 189507.94 | 1184.76 | 0.997763 | 6 | 0.000000 | 7.553510 |
| TIER2_AI_UNAVAILABLE | 0.189508 | 189507.94 | 1184.76 | 0.997763 | 6 | 0.000000 | 7.553510 |
| TIER2_AI_ENABLED@max_delta=0.05 | 0.189508 | 189507.94 | 1184.76 | 0.997763 | 6 | 0.000000 | 7.553510 |
| TIER2_AI_ENABLED@max_delta=0.1 | 0.189508 | 189507.94 | 1184.76 | 0.997763 | 6 | 0.000000 | 7.553510 |
| TIER2_AI_ENABLED@max_delta=0.2 | 0.189508 | 189507.94 | 1184.76 | 0.997763 | 6 | 0.000000 | 7.553510 |

## 6. Performance after costs

All arms share one data snapshot, universe, window, capital, cost schedule and execution convention. Gross P&L, costs and net P&L per arm:

- TIER1: gross 115957.32, costs 1175.44, net 114781.88, cost drag 0.001175
- TIER2: gross 190692.70, costs 1184.76, net 189507.94, cost drag 0.001185
- TIER2_AI_DISABLED: gross 190692.70, costs 1184.76, net 189507.94, cost drag 0.001185
- TIER2_AI_NEUTRAL: gross 190692.70, costs 1184.76, net 189507.94, cost drag 0.001185
- TIER2_AI_ENABLED: gross 190692.70, costs 1184.76, net 189507.94, cost drag 0.001185
- TIER2_AI_UNAVAILABLE: gross 190692.70, costs 1184.76, net 189507.94, cost drag 0.001185
- TIER2_AI_ENABLED@max_delta=0.05: gross 190692.70, costs 1184.76, net 189507.94, cost drag 0.001185
- TIER2_AI_ENABLED@max_delta=0.1: gross 190692.70, costs 1184.76, net 189507.94, cost drag 0.001185
- TIER2_AI_ENABLED@max_delta=0.2: gross 190692.70, costs 1184.76, net 189507.94, cost drag 0.001185

## 7. Risk comparison

- TIER1: max DD 0.000000, DD duration 0 cycles, downside dev 0.000000, worst cycle 0.003799, avg exposure 0.944344, max position weight 0.108273, risk vetoes 0, sector concentration UNAVAILABLE (no sector classification in repository data)
- TIER2: max DD 0.000000, DD duration 0 cycles, downside dev 0.000000, worst cycle 0.003814, avg exposure 0.949037, max position weight 0.338417, risk vetoes 0, sector concentration UNAVAILABLE (no sector classification in repository data)
- TIER2_AI_DISABLED: max DD 0.000000, DD duration 0 cycles, downside dev 0.000000, worst cycle 0.003814, avg exposure 0.949037, max position weight 0.338417, risk vetoes 0, sector concentration UNAVAILABLE (no sector classification in repository data)
- TIER2_AI_NEUTRAL: max DD 0.000000, DD duration 0 cycles, downside dev 0.000000, worst cycle 0.003814, avg exposure 0.949037, max position weight 0.338417, risk vetoes 0, sector concentration UNAVAILABLE (no sector classification in repository data)
- TIER2_AI_ENABLED: max DD 0.000000, DD duration 0 cycles, downside dev 0.000000, worst cycle 0.003814, avg exposure 0.949037, max position weight 0.338417, risk vetoes 0, sector concentration UNAVAILABLE (no sector classification in repository data)
- TIER2_AI_UNAVAILABLE: max DD 0.000000, DD duration 0 cycles, downside dev 0.000000, worst cycle 0.003814, avg exposure 0.949037, max position weight 0.338417, risk vetoes 0, sector concentration UNAVAILABLE (no sector classification in repository data)
- TIER2_AI_ENABLED@max_delta=0.05: max DD 0.000000, DD duration 0 cycles, downside dev 0.000000, worst cycle 0.003814, avg exposure 0.949037, max position weight 0.338417, risk vetoes 0, sector concentration UNAVAILABLE (no sector classification in repository data)
- TIER2_AI_ENABLED@max_delta=0.1: max DD 0.000000, DD duration 0 cycles, downside dev 0.000000, worst cycle 0.003814, avg exposure 0.949037, max position weight 0.338417, risk vetoes 0, sector concentration UNAVAILABLE (no sector classification in repository data)
- TIER2_AI_ENABLED@max_delta=0.2: max DD 0.000000, DD duration 0 cycles, downside dev 0.000000, worst cycle 0.003814, avg exposure 0.949037, max position weight 0.338417, risk vetoes 0, sector concentration UNAVAILABLE (no sector classification in repository data)

## 8. AI signal quality and contribution

```json
{
  "adjustment_direction_distribution": {
    "DECREASE": 67,
    "INCREASE": 70,
    "NO_CHANGE": 73
  },
  "adjustment_outcome_reasons": {
    "APPLIED": 32,
    "CLAMPED_NO_CHANGE": 2,
    "HOLD_NOT_ADJUSTED": 160,
    "NEUTRAL_SENTIMENT": 16
  },
  "adjustments_applied": 32,
  "confidence_interpretation": "model confidence is NOT a calibrated probability (calibration not demonstrated)",
  "disclosure_store_status_counts": {
    "VALID": 780
  },
  "disclosures_referenced_by_signals": 210,
  "invalid_schema_rate": {
    "denominator": 210,
    "numerator": 0,
    "value": "0.0"
  },
  "max_abs_adjustment": "0.09000000000000002",
  "mean_abs_adjustment": "0.09",
  "missing_provenance_rate": {
    "denominator": 210,
    "numerator": 0,
    "value": "0.0"
  },
  "provider_failure_rate": {
    "denominator": 210,
    "numerator": 0,
    "value": "0.0"
  },
  "provider_status_counts": {
    "OK": 210
  },
  "signal_coverage": {
    "denominator": 50,
    "numerator": 50,
    "value": "1.0"
  },
  "signal_coverage_definition": "valid, eligible signals on BUY/SELL candidates / BUY/SELL candidates",
  "signal_direction_stability": {
    "denominator": 200,
    "numerator": 71,
    "value": "0.355"
  },
  "signals_eligible_after_pit_audit": 210,
  "signals_rejected_by_pit_audit": 0,
  "signals_total": 210,
  "valid_ai_signals": 210
}
```
Incremental trades vs Tier-2 (per AI arm):

```json
{
  "TIER2_AI_DISABLED": {
    "ai_trade_count": 6,
    "baseline_trade_count": 6,
    "identical": true,
    "trades_only_in_ai_arm": 0,
    "trades_only_in_baseline_arm": 0
  },
  "TIER2_AI_ENABLED": {
    "ai_trade_count": 6,
    "baseline_trade_count": 6,
    "identical": true,
    "trades_only_in_ai_arm": 0,
    "trades_only_in_baseline_arm": 0
  },
  "TIER2_AI_ENABLED@max_delta=0.05": {
    "ai_trade_count": 6,
    "baseline_trade_count": 6,
    "identical": true,
    "trades_only_in_ai_arm": 0,
    "trades_only_in_baseline_arm": 0
  },
  "TIER2_AI_ENABLED@max_delta=0.1": {
    "ai_trade_count": 6,
    "baseline_trade_count": 6,
    "identical": true,
    "trades_only_in_ai_arm": 0,
    "trades_only_in_baseline_arm": 0
  },
  "TIER2_AI_ENABLED@max_delta=0.2": {
    "ai_trade_count": 6,
    "baseline_trade_count": 6,
    "identical": true,
    "trades_only_in_ai_arm": 0,
    "trades_only_in_baseline_arm": 0
  },
  "TIER2_AI_NEUTRAL": {
    "ai_trade_count": 6,
    "baseline_trade_count": 6,
    "identical": true,
    "trades_only_in_ai_arm": 0,
    "trades_only_in_baseline_arm": 0
  },
  "TIER2_AI_UNAVAILABLE": {
    "ai_trade_count": 6,
    "baseline_trade_count": 6,
    "identical": true,
    "trades_only_in_ai_arm": 0,
    "trades_only_in_baseline_arm": 0
  }
}
```
Information-content diagnostic (signal direction vs next-cycle return):

```json
{
  "direction_aligned_return": {
    "block_length": 1,
    "confidence_level": "0.9833333333333333333333333333",
    "lower": "-0.0023124234998546864",
    "mean": "3.129089896308085e-05",
    "method": "circular moving-block bootstrap, percentile interval",
    "n": 32,
    "reason": "",
    "resamples": 2000,
    "seed": 20260901,
    "status": "OK",
    "upper": "0.0024062873074685645"
  },
  "hit_rate_direction_aligned": "0.5625",
  "interpretation": "positive aligned return = the signal's stated direction preceded same-direction next-cycle returns; a diagnostic of information, not of tradable profit",
  "limitations": [
    "cross-sectional observations share dates and are not independent (iid bootstrap is optimistic)",
    "no adjustment for the baseline strategy's own selection effect"
  ],
  "mean_forward_return_influenced": "0.005093663784108186",
  "mean_forward_return_non_influenced": "0.006222287102766548",
  "n_dropped_no_forward_bar": 0,
  "n_influenced": 32,
  "n_non_influenced": 18
}
```

## 9. Statistical confidence and limitations

```json
{
  "comparisons": {
    "TIER2_AI_ENABLED@max_delta=0.05": {
      "block_length": 3,
      "confidence_level": "0.9833333333333333333333333333",
      "lower": "0.0",
      "mean": "0.0",
      "method": "circular moving-block bootstrap, percentile interval",
      "n": 20,
      "reason": "every paired difference is exactly zero: the two paths are identical",
      "resamples": 2000,
      "seed": 20260901,
      "status": "ZERO_VARIANCE_IDENTICAL_PATHS",
      "upper": "0.0"
    },
    "TIER2_AI_ENABLED@max_delta=0.1": {
      "block_length": 3,
      "confidence_level": "0.9833333333333333333333333333",
      "lower": "0.0",
      "mean": "0.0",
      "method": "circular moving-block bootstrap, percentile interval",
      "n": 20,
      "reason": "every paired difference is exactly zero: the two paths are identical",
      "resamples": 2000,
      "seed": 20260901,
      "status": "ZERO_VARIANCE_IDENTICAL_PATHS",
      "upper": "0.0"
    },
    "TIER2_AI_ENABLED@max_delta=0.2": {
      "block_length": 3,
      "confidence_level": "0.9833333333333333333333333333",
      "lower": "0.0",
      "mean": "0.0",
      "method": "circular moving-block bootstrap, percentile interval",
      "n": 20,
      "reason": "every paired difference is exactly zero: the two paths are identical",
      "resamples": 2000,
      "seed": 20260901,
      "status": "ZERO_VARIANCE_IDENTICAL_PATHS",
      "upper": "0.0"
    }
  },
  "family_confidence_level": "0.95",
  "method": "paired circular block bootstrap of per-cycle return differences (AI arm - Tier-2), Bonferroni-adjusted level; no p-values are reported",
  "n_comparisons": 3,
  "pbo": {
    "duplicate_trial_ids": [
      "TIER2_AI_ENABLED@max_delta=0.1",
      "TIER2_AI_ENABLED@max_delta=0.2"
    ],
    "is_ties": 0,
    "mean_logit": null,
    "metric": "SHARPE",
    "n_combinations": 0,
    "n_partitions": 10,
    "n_periods": 20,
    "n_trials_supplied": 3,
    "n_trials_used": 1,
    "pbo": null,
    "prob_oos_loss_of_selected": null,
    "reason": "fewer than 2 distinct trials after removing identical candidates",
    "status": "INSUFFICIENT_SAMPLE"
  },
  "per_comparison_confidence_level": "0.9833333333333333333333333333",
  "regimes": {
    "reason": "AI and Tier-2 paths are compared across the whole confirmatory window; segmenting identical or near-identical paths by regime adds no information",
    "status": "NOT_PERFORMED_ON_AI_COMPARISON"
  },
  "walk_forward": {
    "reason": "no model fitting or configuration selection occurs in this evaluation (defaults frozen before the run); Slice 9 split/purge utilities are not engaged",
    "status": "NOT_PERFORMED"
  }
}
```
- Synthetic prices rise monotonically, so drawdown, downside deviation and worst-cycle metrics are degenerate and cycle Sharpe is not meaningful.
- Synthetic/offline-fixture evidence cannot support a claim about markets or about any AI model.
- AI-enabled and Tier-2 runs share the run id by Slice 11 design (run-facing strategy id stays the baseline id); arms are distinguished here by arm label, overlay version id and journal AI events.
- Sharpe is per-cycle and not annualised; annualised return/volatility/Calmar are UNSUPPORTED (irregular cycle spacing, short sample).
- Sector concentration is unavailable (no sector classification in repository data).
- Simulated execution: NEXT_BAR_OPEN fills with a deterministic simulated broker; no market-impact or queue model.
- Information-content diagnostic uses cross-sectional observations that are not independent; its interval is optimistic.
- Walk-forward and regime segmentation were not performed because no model fitting or selection occurs and the compared paths are identical or near-identical.
- No real provider call has been made in this evaluation; fixture signals are not model outputs.

## 10. Robustness and ablation results

| Ablation arm | Net return | Δ vs Tier-2 | Identical path to Tier-2 |
|---|---|---|---|
| TIER2 | 0.189508 | 0.000000 | True |
| TIER2_AI_DISABLED | 0.189508 | 0.000000 | True |
| TIER2_AI_NEUTRAL | 0.189508 | 0.000000 | True |
| TIER2_AI_ENABLED | 0.189508 | 0.000000 | True |
| TIER2_AI_UNAVAILABLE | 0.189508 | 0.000000 | True |
| TIER2_AI_ENABLED@max_delta=0.05 | 0.189508 | 0.000000 | True |
| TIER2_AI_ENABLED@max_delta=0.1 | 0.189508 | 0.000000 | True |
| TIER2_AI_ENABLED@max_delta=0.2 | 0.189508 | 0.000000 | True |

Authority checks: {"TIER2_AI_DISABLED": {"actions_and_size_hints_identical_to_baseline": true, "all_fills_within_permitted_universe": true, "every_order_carries_a_risk_decision": true, "no_order_without_candidate": true, "risk_verdicts_identical_to_baseline": true}, "TIER2_AI_ENABLED": {"actions_and_size_hints_identical_to_baseline": true, "all_fills_within_permitted_universe": true, "every_order_carries_a_risk_decision": true, "no_order_without_candidate": true, "risk_verdicts_identical_to_baseline": true}, "TIER2_AI_ENABLED@max_delta=0.05": {"actions_and_size_hints_identical_to_baseline": true, "all_fills_within_permitted_universe": true, "every_order_carries_a_risk_decision": true, "no_order_without_candidate": true, "risk_verdicts_identical_to_baseline": true}, "TIER2_AI_ENABLED@max_delta=0.1": {"actions_and_size_hints_identical_to_baseline": true, "all_fills_within_permitted_universe": true, "every_order_carries_a_risk_decision": true, "no_order_without_candidate": true, "risk_verdicts_identical_to_baseline": true}, "TIER2_AI_ENABLED@max_delta=0.2": {"actions_and_size_hints_identical_to_baseline": true, "all_fills_within_permitted_universe": true, "every_order_carries_a_risk_decision": true, "no_order_without_candidate": true, "risk_verdicts_identical_to_baseline": true}, "TIER2_AI_NEUTRAL": {"actions_and_size_hints_identical_to_baseline": true, "all_fills_within_permitted_universe": true, "every_order_carries_a_risk_decision": true, "no_order_without_candidate": true, "risk_verdicts_identical_to_baseline": true}, "TIER2_AI_UNAVAILABLE": {"actions_and_size_hints_identical_to_baseline": true, "all_fills_within_permitted_universe": true, "every_order_carries_a_risk_decision": true, "no_order_without_candidate": true, "risk_verdicts_identical_to_baseline": true}}

## 11. Failed experiments and exclusions

Trial-ledger attempts recorded this evaluation: 9 (terminal outcomes: {'COMPLETED': 9}).
Signal exclusions (0):

## 12. Conclusion

**Outcome B** — Inconclusive (AI component remains experimental).

- frozen spec slice12-synthetic-ai-vs-tier2 v1 hash 39fa2f266629e55a
- R1 integrity: no applied-but-ineligible signals
- R2 evidence cap: class 'SYNTHETIC_DATA_OFFLINE_FIXTURE_SIGNALS', effective_confirmatory=False; confirmatory-grade evidence (real data, live-captured provider signals, cutoff-clean) is required to leave Outcome B

## 13. Recommendation for the next stage

Keep the AI component experimental and disabled in any decision path. Obtain confirmatory-grade evidence (real market data, live-captured provider signals recorded at decision time, cutoff-clean window) and, before that, decide through a governed ADR whether confidence should ever reach sizing; today it cannot.

---
Artifact hash `0260f1d2892a930582e18fa8eae0b906032a0722284b3958875a3338195a4863`. Synthetic/offline-fixture results are infrastructure verification, not evidence about markets or about any AI model.
