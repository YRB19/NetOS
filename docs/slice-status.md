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

**Status: implemented; acceptance criteria met (see `order-state-machine-reconciliation.md`).** Offline/simulated only;
no LLM, no live broker, no credentials, no Slice 8 work.
**Delivered:** `OrderLifecycleManager` (approval re-validation, write-ahead submission, explicit submission uncertainty,
identity-based idempotent events, quarantine, operator-only halt clearing, checksummed snapshot/restore); execution
reconciliation (orders, fills, positions, cash, 3-way) extending the Slice 6 comparison; simulated-broker fault injection and
lookup by client key; pipeline runner integration; ADR-10 import rules.
**Tests:** 672 unittest tests pass (baseline 593 verified on the uploaded repo before editing; +79). Import checker: 0 violations.
**Honest caveats:** in-memory persistence only; no exactly-once claim for any real broker; charge rates not independently
verified in simulation; `ACKNOWLEDGED -> CANCELLED` contract edge is an open operator decision; risk thresholds remain examples.
