# Notion-ready paste block — Slice 5 (NOT written to Notion: write returned "No approval received")

## Slice 5 — Research Harness Core (COMPLETE)

**Verified state:** starting repo = Slice 4.5B (378 unittest tests, 0 import-graph violations). Final = 471 unittest tests passing (+93: 41 unit, 18 lookahead/isolation adversarial, 25 fault-injection, 9 synthetic e2e) plus the 3 pytest-fixture tests run manually (pytest unavailable in sandbox); import-graph checker 0 violations.

**Built:** deterministic offline replay of canonical MarketData → FeatureSnapshot → strategy → CandidateTrade → NEXT_BAR_OPEN simulated fill → shared Cost Model (schedule version explicit, never defaulted; V1 and V2 both selectable) → research portfolio (costs deducted from cash, integer shares, cash/overselling guards) → basic net-of-cost metrics. Deterministic experiment/run identity (no wall-clock). Strict split + fail-closed contamination guards. Failed runs persisted as first-class artifacts. File-based, byte-reproducible artifacts. Apples-to-apples baseline comparison via comparison fingerprint.

**Recorded contract notes:** EvaluationRun.passed_pre_registered_criteria=False means NOT ASSESSED; DecisionRecord emitted for fills only; two-way split encoded via empty validation window. No domain contract changed.

**Not done (out of scope):** PBO/CSCV, regime segmentation, Sharpe-family metrics, Tier-2, LLM, risk engine, brokers, paper trading. A passing run is infrastructure verification, not evidence of profitability.
