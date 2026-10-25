# Cumulative slice status

## Slice 5 — Research harness core (complete; see `research-harness.md`, `research-protocol.md`)

Deterministic offline replay of canonical `MarketData` → `FeatureSnapshot` → strategy →
`CandidateTrade` → NEXT_BAR_OPEN simulated fill → shared Cost Model → research portfolio →
metrics, with deterministic experiment/run identity, strict split + basic contamination
guards (fail-closed), failures persisted as first-class artifacts, file-based artifacts,
and apples-to-apples baseline comparison. **Not** implemented (out of scope): PBO/CSCV,
regime segmentation, Sharpe-family metrics, Tier-2, LLM, risk engine, brokers, paper trading.
A passing run is infrastructure verification only — not evidence of profitability.
Tests: 378 → 471 (unittest), +93 (41 unit, 18 lookahead/isolation adversarial, 25
fault-injection, 9 e2e integration).

Distinction used below: **historically reported** = a past
session's claim; **verified now** = executed in the Slice 4.5A session on this tree.

| Slice | Historically reported | Verified now (4.5A) | Origin |
| --- | --- | --- | --- |
| 0 | complete | arch check: 0 violations | restored |
| 1 | 112 tests | domain surface complete (Stage 3 §2) | restored |
| 2 | 116 tests | pipeline + persistence tests pass | restored |
| 3 | 81 tests | context + Tier-1 tests pass | restored |
| 4 | 43 tests | cost tests pass; schedule still unverified | restored |
| 4.5A | n/a | 369 passed (pytest); 366 (unittest, 3 need pytest fixtures); 14 new integration/guard tests; 0 violations | verification + minimal fix |
| 4.5B | n/a | 381 passed (pytest); 378 (unittest); +12 new tests; 0 violations | primary-source rate verification |
| 5 | n/a | 471 passed (unittest, 93 new) + 3 pytest-fixture tests run manually (pytest unavailable); 0 violations | research harness core |
| 6 | n/a | 593 passed (unittest; 471 baseline + 122 new); 0 violations | Tier-2 momentum + Risk Engine + sizing + simulated broker |

Cost schedule `india-equity-v1-unverified` remains `verified=False`, preserved unchanged
for reproducibility.

## Slice 4.5B — India equity cost schedule verification

**New schedule:** `india-equity-v2-2026-03-verified` (`verified=True` for its statutory/
regulatory/exchange components — brokerage remains an unverified assumption within it; see
`docs/cost-model.md`'s Rate Verification Status table).

**Verified against primary sources (2026-09-29):** STT (NSE, updated 17/04/2026), SEBI
turnover fee (same), GST rate (same), stamp duty (NSE, updated 03/10/2023), exchange
transaction charge (NSE circular NSE/FA/73061, effective 2026-03-01 — this one component's
rate actually changed from V1's ₹297/crore to ₹307/crore, a genuine regulatory update V1
predated).

**Still unverified:** brokerage (both schedule versions — deliberate, not a statutory rate).
**Documented gap, not fixed:** GST base composition is standard practice, not itemised by
the primary source; exchange identity (NSE vs BSE) is not modeled — NSE-specific rate used.

**Tests:** +12 (hand-calculated fixtures for both trade legs/types, SEBI and exchange-charge
unit-conversion tests, V1 preserved-and-reproducible tests). Full suite: 381 passed (pytest),
378 (unittest), 0 import-graph violations.

See `repository-integration.md`, `cost-model.md`, `cost-rate-verification.md`.
Historical reports: `history/slice1..4/`.

## Slice 6 — Tier-2 momentum, Risk Engine, sizing, simulated broker

**Status: implemented; all acceptance criteria met (Notion write verified by re-fetch).**
Offline research/simulation only. No LLM, no real broker, no credentials, no live path, no Slice 7+ work.

**Delivered:** Tier-2 12-1 momentum (`tier2-momentum.md`); deterministic Risk Engine RR-1..RR-9, fail closed
(`risk-engine.md`); deterministic sizing (`sizing.md`); `SimulatedBrokerAdapter` on the existing Order state
machine (`simulated-broker.md`); `simulation/` orchestrator running strategy -> risk -> sizing -> broker ->
portfolio with independent-ledger reconciliation; Tier-1 still runs through the same pipeline; Slice 5
harness untouched apart from three additive `FailureCategory` members.

**Tests:** 593 unittest tests pass (baseline 471 measured on the uploaded repo before any change; +122:
Tier-2 23, risk 26, sizing 20, broker 18, end-to-end 25, isolation/architecture 10). Import checker: 0 violations.

**Honest caveats:** results are synthetic infrastructure checks, not alpha evidence; a passing Risk Engine is
not regulatory approval; risk thresholds in tests are examples, not operator-approved limits; RR-4 exit-of-removed
instrument and `RiskDecision.approved_qty`-as-ceiling are documented interpretations needing operator sign-off.

## Slice 7 — Order state machine & reconciliation hardening

**Status: COMPLETE against the final-closure gate (2026-10-23), with one stated caveat: `NetOS_Post_Slice_7_Roadmap.md` was not in the
engineering workspace, so roadmap line-by-line acceptance was NOT inspected or certified; the closure-prompt gate was used instead. ADR-11 is
pending operator ratification.** Previous status (2026-10-21, kept for history): PARTIALLY COMPLETE (acceptance closure pass). The original Slice 7 status line ("implemented; acceptance
criteria met") is withdrawn: it was written without the roadmap, and the closure review found four real gaps, now closed in code and
tests (below). Roadmap-level acceptance cannot be certified because `NetOS_Post_Slice_7_Roadmap.md` was not supplied to either pass.
Offline/simulated only; no LLM, no live broker, no credentials, no Slice 8 work.
**Closed in the closure pass:** (1) cancellation contract — ADR-11 adds `ACKNOWLEDGED -> CANCELLED` (broker-confirmed only), authority
Stage 1 FR-3 + Stage 3 §10; (2) per-fill charge/component/schedule-version and three-way average-cost reconciliation with a documented
policy; (3) event provenance (ids, correlation, source, event time vs recorded time, halt/quarantine references) with snapshot v2 and
v1 compatibility; (4) restart/recovery: atomic mandatory write-ahead checkpoint, validated restore, broker-lookup recovery, tests at
every required boundary.
**Original delivery:** `OrderLifecycleManager`, idempotent identity-based event handling, quarantine, operator-only halt clearing,
execution reconciliation, simulated-broker fault injection, runner integration, ADR-10 import rules.
**Tests:** 717 unittest tests pass (672 baseline verified from the delivered archive; +45). Import checker and `shared.arch_lint.cli`: 0 violations.
pytest, ruff and mypy are not installed in this environment, so they were not run.
**Final closure (2026-10-23, ADR-13):** the portfolio-application crash window is closed: `ResearchPortfolio.apply_fill` is idempotent by
`fill_id` (payload fingerprint; conflicting reuse fails closed), commits financials + applied-fill ledger in one atomic checksummed file,
and `simulation/settlement.apply_pending_fills` recovers both interleavings; 21 new tests incl. rebuilt manager + restored portfolio.
**Tests:** 738 unittest tests pass (717 verified baseline + 21). Import checker and `shared.arch_lint.cli`: 0 violations; `compileall` clean.
pytest/ruff/mypy unavailable here, not run. **Remaining limits:** two checkpoint files (safe interleavings, not one joint atomic commit);
`PipelineHarness` uses an in-memory portfolio and has no integrated crash-resume; roadmap not inspected; ADR-11 awaiting operator ratification.
**Earlier limits (history):** roadmap not available for line-by-line acceptance; the portfolio-application crash window (portfolio
update vs `mark_portfolio_applied`) needed an idempotent-by-fill-id portfolio (now built, above); the original
`OrderRequest` store needed by restore belongs to sizing/Slice 8; no exactly-once claim for any real broker; charge rates not
independently verified in simulation; ADR-11 awaits operator ratification; risk thresholds remain unapproved examples.

## Slice 8 — Decision Journal & Observability (2026-10-25)
**Status: COMPLETE against the Slice 8 prompt (backend contract only); roadmap `NetOS_Post_Slice_7_Roadmap.md` was NOT in the workspace, so
roadmap line-by-line acceptance is not certified. ADR-11 is still pending operator ratification (unchanged).** Implemented: ADR-14 durable
hash-chained journal, required pipeline integration with pre-submission write, structured RR-check evidence, explicit HOLD/NO_TRADE/
SKIPPED/INVALID decisions, read-only query/reconstruction, redaction, controlled error taxonomy, verify command. Docs: docs/decision-journal-observability.md.
**Tests:** 787 unittest tests pass (738 verified baseline + 49 new). Import checker and `shared.arch_lint.cli`: 0 violations; compileall clean; pytest/ruff/mypy unavailable.
**Limits:** see docs/decision-journal-observability.md §7. Slice 9 (statistical hardening) and Slice 10 (console) not started. Evidence class: synthetic infrastructure only.
