# Implementation log

## 2026-09-27 — Cumulative Slices 1–4 reconciliation

Reconstructed one root-level project from the four user-supplied archives.
The archive contents are authoritative; existing local-only project contents
are preserved in the external recovery archive. Git history is retained.

See `slice-1-4-reconciliation.md` and `slice-1-4-file-audit.md` for the complete
reconciliation record. Original implementation logs are preserved verbatim in
`history/slice1/` through `history/slice4/`.

Slices 1–4 have been integrated. Slice 5 has NOT been started.

## Slice 4.5A — Repository verification and integration (session date 2026-09-28)
**Starting state:** uploaded NetOS.zip already contained an integrated tree (~30 commits) from
a prior reconciliation; original per-slice archives not supplied.
**Work:** independent verification (355 pytest tests passed; 352 via unittest; arch checker
0 violations x3 entry points); Stage 3 §2 surface checked (all present; Confidence is a
CandidateTrade field); scan for out-of-scope code (none; scaffolds empty).
**Reconciliation:** duplicate `NormalizationResult` renamed in Slice 3 alternate path;
`CostEstimate` split kept and allow-listed; two ingestion paths kept.
**Tests added:** `tests/integration/test_slice_4_5a_integration.py` (14): data->feature,
feature->Tier-1 (initial/unchanged/added/removed), provenance, cost independence (AST import
scan), unverified schedule guard, full chain determinism, duplicate-class guard.
**Failure/fix:** first determinism test failed — per-read `ingestion_time` provenance;
test corrected to fixed-raw-read semantics, behaviour documented, code unchanged.
**Final:** 369 passed (pytest), 366 (unittest), 0 violations.
**Limitations:** see repository-integration.md. **Next:** Slice 5 not started.

## Slice 4.5B — India equity cost schedule primary-source verification (session date 2026-09-29)
**Starting state:** 4.5A tree, 369/366 tests passing, 0 arch violations, schedule
`india-equity-v1-unverified` (`verified=False`).
**Work:** searched and fetched official primary sources for all six existing cost
components (NSE investor-education pages for STT/SEBI-fee/GST/stamp-duty; NSE circular
NSE/FA/73061 for exchange transaction charge; SEBI circular SEBI/HO/GSD/TAD/CIR/P/2022/0097
as GST corroboration). Compared each verified rate against the existing V1 constants.
**Finding:** five of six statutory/regulatory rates in V1 were already numerically correct
(STT, SEBI fee, GST rate, both stamp-duty legs) — now independently confirmed rather than
assumed. One component, the exchange transaction charge, was genuinely stale: V1's
₹297/crore predated NSE/FA/73061's revision to ₹307/crore, effective 2026-03-01 (before
today). Brokerage was deliberately left unverified (not a statutory rate; no single broker's
official rate card checked), consistent with the brief's explicit instruction.
**Code:** added `INDIA_EQUITY_SCHEDULE_V2_VERIFIED` (`india-equity-v2-2026-03-verified`,
`verified=True`) to `shared/costs/schedule.py`, registered additively in
`default_registry()`. `INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED` left byte-for-byte unchanged.
No dataclass field added; per-component status recorded in the module docstring, the
schedule's `notes` dict, and `docs/cost-model.md`'s new Rate Verification Status table,
since a single schedule-level `verified` bool cannot itself distinguish "verified" from
"deliberately still an assumption" at component granularity.
**Tests added (12):** hand-calculated Decimal fixtures for delivery buy/sell and intraday
buy/sell against V2; a dedicated SEBI-fee unit-conversion test (₹10/crore → exact ₹10.00 at
₹1 crore turnover) and an equivalent exchange-charge test (₹307/crore); V1
preserved-and-still-selectable tests, including a fixed regression value proving V1's
exchange charge (74.25 on the standard fixture) did not drift when V2 was added.
**Verification:** 381 passed (pytest), 378 (unittest, historical +3 gap unchanged), 0
import-graph violations (both entry points).
**Docs:** `cost-model.md` (new Rate Verification Status table, rewritten
Provenance/Limitations), `cost-rate-verification.md` (new — full audit trail with sources,
URLs, effective dates), `slice-status.md`, this log.
**Limitations carried forward:** BSE's own exchange-transaction-charge rate not verified
(NSE-specific rate used; documented as a model gap, not fixed); GST base composition is
standard industry practice, not itemised by the primary source itself; brokerage remains
unverified in both schedule versions by design.
**Next:** Slice 5 not started (out of scope for this slice).

## Slice 5 — Research Harness Core
**Start state:** repository as uploaded after Slice 4.5B (378 unittest tests passing, 0
import-graph violations; 3 fixture-based tests need pytest, unavailable here).
**Implemented:** `research/harness/` (config/identity, replay, runner, execution translation,
portfolio, metrics, comparison, result, failures, jsonio), `research/contamination/guards.py`,
`research/experiments/store.py`. Reused `Experiment`, `EvaluationRun`, `SplitSpec`,
`ContaminationCheckResult`, `DecisionRecord`, `Fill`, `CandidateTrade`, `FeatureSnapshot`,
`PermittedUniverse`, `CostModel`; no domain contract modified.
**Key decisions:** (1) fills at the next bar's OPEN, consumed lazily when the loop reaches
that bar, so no lookahead is possible by construction; (2) deterministic string identities
(`exp_`/`run_` + hash), wall-clock excluded; (3) fail-closed defaults (FAIL_RUN on rejected
orders; no forward-fill of held-position marks unless `carry_forward_marks`); (4) cost
schedule required, never defaulted; future-effective schedule needs explicit acknowledgement;
(5) `DecisionRecord` emitted for fills only — its enum cannot express HOLD-with-candidate or
simulated rejections (documented, not changed); (6) `EvaluationRun.passed_pre_registered_criteria
=False` means NOT ASSESSED (also `criteria_assessment` in result.json).
**Tests:** +93 → 471 (unittest): 41 unit, 18 lookahead/isolation adversarial, 25
fault-injection, 9 synthetic end-to-end. 3 pytest-fixture tests run manually: pass.
**Defects found while testing:** none in prior slices; two harness/test bugs fixed during
development (non-deterministic `Experiment.created_at` leaking into artifacts; a test helper
treating an empty universe list as "use default").
**Limitations:** see `research-harness.md` (ingestion_time not an availability gate, unliquidated
mark-to-market, no PBO/CSCV/regimes, per-cycle O(N) snapshot-version hashing).
**Next:** not started — Slice 6 (Tier-2 momentum / Risk Engine) per the Stage 3 sequence.

## Slice 6 — Tier-2 momentum + Risk Engine + deterministic sizing + simulated broker
**Start state (measured):** uploaded repo through Slice 5; 471 unittest tests OK; import checker 0 violations.
**Built:** `data/features/{calendar,momentum,builders}.py`; `intelligence/baseline/tier2_momentum.py`;
`risk_execution/risk_engine/{config,context,engine}.py`; `risk_execution/sizing/sizer.py`;
`risk_execution/broker/{interface.py,adapters/simulated.py}`; `simulation/{config,runner,reconcile,result,artifacts}.py`;
arch-lint rules for the new boundaries; three additive `FailureCategory` members.
**Design decisions:** (1) `simulation/` leaf package keeps research isolated from execution (ADR-9);
(2) `RiskDecision.approved_qty` on APPROVE is a quantity *ceiling*, sizing alone produces quantities/OrderRequests;
(3) rebalance = first observation of a calendar month, computed from visible data only, carried in
FeatureSnapshot features; (4) strategy version id embeds a hash of its full config; (5) risk config has no
default thresholds; (6) drawdown halt latches in the runner and never self-clears; (7) `DecisionRecord` also
emitted for risk vetoes (`REJECTED_AT_RISK`), broker rejections and reconciliation failures; (8) pipeline artifacts go
in a `pipeline/` subdirectory so the Slice 5 store is untouched.
**Defects found/fixed during development:** test fixture produced negative low prices; my first end-to-end test
file overwrote the pre-existing Slice 5 `tests/integration/test_pipeline_e2e.py` (2 tests) — caught by comparing
per-module counts against a pristine unzip; the Slice 5 file was restored and mine is
`test_execution_pipeline_e2e.py`; `RiskConfig` initially capped gross exposure at 1.0 (relaxed to positive).
Mid-session the sandbox was reset and the working tree was lost; it was rebuilt from the uploaded zip and
re-verified (593 tests, 0 violations).
**Tests:** 593 passed (471 + 122). Import checker: 0 violations.
**Limitations:** see each doc; synthetic data only; NEXT_BAR_OPEN no-slippage fills; no regulatory approval implied.
**Notion:** Slice 6 entry written and verified by re-fetching the page.
