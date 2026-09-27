# STAGE 3 — DETAILED TECHNICAL DESIGN v0.1
**AI Trading Agent Research & Engineering Project**
Status: Draft for discussion · Stage 3 (Detailed Technical Design) · Depends on: Stage 1 Requirements Baseline v0.2 (APPROVED), Stage 2 System Architecture v0.1 (Build-ready)

**Stage 2 COMPLETE → Stage 3 STARTED (this document).**

This document does not reopen Stage 0 research, does not re-litigate Stage 1 requirements, and does not revisit Stage 2's architectural decisions except where a genuine technical contradiction is found (none was, in the course of writing this). Every technical decision below traces to a Stage 1 requirement ID, a Stage 2 architectural element, or is explicitly marked as a new Stage 3 ADR where a decision had to be made that Stage 2 left open. Where something is a narrow, specific technical fact requiring external verification, that is done in isolation, not as a re-opened literature review, and is marked as such.

---

## 0. How to read this document

Stage 2 defined five planes (Governance, Data, Intelligence, Risk & Execution, Observability & Evaluation) plus an isolated Research/Backtesting environment, and made five architecture decisions (ADR-1 through ADR-5, plus implicit ADR-3/4/5) that this document treats as fixed inputs. This document's job is narrower and more concrete: turn each plane into modules, interfaces, schemas, and a build sequence precise enough that implementation can start without further design conversations. Every section below is written so a competent engineer unfamiliar with the prior stages, but handed this document, could begin building.

---

## 1. Repository / project structure

**Design principle:** the repository layout mirrors the plane boundaries exactly, so that "Plane 2 is swappable without Plane 3 rework" (FR-6) and "Research has no write path to live" (§11/§14 of Stage 2) are true at the filesystem/dependency-graph level, not just conceptually. A module in `risk/` must never import from `intelligence/`; a module in `research/` must never import from `execution/` or hold broker credentials. This is enforced by directory structure plus a dependency-direction lint rule (see §15), not by convention alone.

```
trading-system/
├── governance/              # Plane 0 — operator-owned config, autonomy level, kill switch state
│   ├── config/               # operator-writable, system-read-only values (RR-1..3 thresholds, universe, autonomy level)
│   ├── autonomy/              # autonomy-level state machine, promotion/approval records (AR-1..5)
│   └── killswitch/            # independent kill-switch trigger + state, checked by Plane 3 (AR-3, RR-8)
│
├── data/                    # Plane 1 — ingestion, validation, normalization, feature formation
│   ├── adapters/              # one subfolder per external data source, behind a common interface (TR-6)
│   ├── validation/            # SF-1 (missing), SF-2 (staleness) checks
│   ├── normalization/         # corporate actions, schema unification, timezone handling
│   ├── features/              # feature/context snapshot construction (input to Plane 2)
│   └── schemas/               # canonical MarketData / FeatureSnapshot / Instrument definitions (shared, versioned)
│
├── domain/                  # Shared domain model (§2) — pure data structures, no logic, no I/O
│   └── models/                # Instrument, CandidateTrade, Position, Order, DecisionRecord, etc.
│
├── intelligence/             # Plane 2 — the "replaceable brain." No broker credentials, no DB write access
│   ├── baseline/               # deterministic Plane 2 v1 (§12) — the ER-1 comparator, always present
│   ├── llm_component/          # first AI component (§13), versioned, isolated behind the same interface as baseline
│   └── interface/              # the CandidateTrade contract (§3) — the ONLY thing any Plane 2 implementation may emit
│
├── risk_execution/           # Plane 3 — deterministic, non-LLM, hard veto authority (RR-1..9)
│   ├── cost_model/             # shared with research/ via the same package, not a duplicate (§6)
│   ├── risk_engine/            # RR-1..9 enforcement (§7)
│   ├── sizing/                 # deterministic sizing rule (§8)
│   ├── order_state_machine/    # order lifecycle (§9)
│   └── broker/                 # broker-neutral interface + adapters (§10); ONLY module holding broker credentials
│
├── observability/            # Plane 4 (live side) — decision logs, audit trail, reconciliation, alerts
│   ├── decision_log/           # structured DecisionRecord persistence (§4, §18)
│   ├── reconciliation/         # broker-truth vs. system-belief reconciliation (FR-4)
│   └── reporting/               # P&L, cost reconciliation, health/alerting
│
├── research/                 # Isolated Research & Backtesting environment (Stage 2 §11). NO import from risk_execution/broker
│   ├── harness/                 # walk-forward splitting, baseline comparison, regime segmentation (ER-1, ER-2, ER-6)
│   ├── contamination/           # ER-3 checks (temporal/knowledge-cutoff leakage)
│   ├── stats/                   # ER-4 multiple-testing correction (PBO/CSCV-style)
│   ├── experiments/              # every attempted experiment, including failed ones (§11, ER-4, ER-8)
│   └── promotion/                # candidate-artifact packaging for the promotion gate (§14)
│
├── shared/                   # Cross-cutting, dependency-safe utilities only (no plane-specific logic)
│   ├── versioning/              # artifact/version-identifier machinery (§19), used by every plane
│   ├── time/                     # timezone/clock utilities (single source of truth, avoids SF-2 bugs)
│   └── config_loader/            # reads Plane 0 config; read-only outside governance/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/                 # inter-plane interface contract tests (§3, §15)
│   ├── simulation/                # end-to-end simulated-market tests
│   ├── fault_injection/           # SF-1..10 (§15)
│   └── adversarial/                # RR-1..9 adversarial/edge-case tests (§15)
│
├── scripts/                  # operational scripts (backfill, one-off data checks, promotion CLI) — never imported by app code
├── docs/                      # this document series (00–05+), ADRs (§24), traceability matrix (§23)
└── deploy/                    # environment definitions (§20) — dev/research/paper/staging/live, each its own manifest
```

**Why this shape:** every top-level directory is one plane or one Stage-2-mandated boundary (domain model is shared *data shapes*, not shared *logic*, so it doesn't create a backdoor coupling between planes). `research/` and `risk_execution/` never appear in each other's dependency graphs — enforced by a CI import-graph check (a `research/` module importing `risk_execution.broker` fails the build) — which is the literal, buildable version of Stage 2 §11's "no network path is provisioned" applied to source code as well as runtime topology.

---

## 2. Domain model

All domain objects are **plain, versioned data structures** (no embedded business logic — logic lives in the plane modules that operate on them). Every object below states purpose, key fields, mutability, identifiers, and version references. Timestamps are UTC-stored, IST-displayed (see §5).

| Object | Purpose | Key fields (non-exhaustive) | Mutable? | Identifiers | Version refs |
|---|---|---|---|---|---|
| **Instrument** | Represents one tradable equity | symbol, exchange, ISIN, lot size, segment (equity/F&O — equity only in v1 per TR-1), universe-membership flag | Membership flag only, via Plane 0 | ISIN (canonical), symbol+exchange (working) | universe config version |
| **MarketData** | One normalized market observation | instrument_id, timestamp, OHLCV, source, ingestion_time | Immutable once written (corrections are new records, see §5) | (instrument_id, timestamp, source) | data snapshot version |
| **FeatureSnapshot** | The exact input Plane 2 saw at decision time | instrument_id, decision_timestamp, feature values, feature-set version, source MarketData refs | Immutable | UUID | feature-set version, data snapshot version |
| **CandidateTrade** | Plane 2's proposal (§3) | instrument_id, action (buy/sell/hold), suggested_qty_or_size_hint, confidence, uncertainty, rationale, strategy_version, timestamp | Immutable | UUID | strategy/model version |
| **Confidence/Uncertainty** | Mandatory sub-object of CandidateTrade (SF-10) | confidence ∈ [0,1] or categorical band, uncertainty source (model-reported vs. derived), fallback hint | Immutable (part of CandidateTrade) | — | — |
| **CostEstimate** | Pre-trade cost projection (TR-2) | instrument_id, brokerage, STT, exchange_charges, SEBI_fees, GST, stamp_duty, estimated_slippage, cost_model_version | Immutable | UUID | Cost Model version |
| **ActualCost** | Post-trade realized cost (PR-6) | order_id, all cost components as actually charged, realized_slippage | Immutable | UUID, FK to Order | Cost Model version (for reconciliation) |
| **RiskDecision** | Plane 3's verdict on a CandidateTrade (RR-1..9) | candidate_trade_id, checks_evaluated (list of RR-x, pass/fail), final_verdict (approve/reject/resize), approved_qty, reasons | Immutable | UUID, FK to CandidateTrade | risk-rule version |
| **PortfolioState** | Point-in-time positions + cash, reconciled to broker | as_of_timestamp, positions[], cash_balance, unrealized_pnl, realized_pnl, source (system-belief vs. broker-confirmed) | New record per reconciliation cycle (append-only) | (as_of_timestamp, source) | broker adapter version |
| **Position** | One held instrument's state | instrument_id, quantity, avg_cost, side (long only in v1 — no shorting assumed unless later specified) | Derived/recomputed, not directly edited | (instrument_id, as_of_timestamp) | — |
| **OrderRequest** | What Plane 3 asks the broker to do | instrument_id, side, quantity, order_type, risk_decision_id (FK), idempotency_key | Immutable once submitted | UUID (idempotency_key) | Plane 3 version |
| **Order** | Broker-tracked lifecycle of a request (§9) | order_request_id, broker_order_id, state, state_history[], last_broker_response | State field mutable via defined transitions only | broker_order_id (external), UUID (internal) | — |
| **Fill** | One broker-confirmed execution event | order_id, quantity, price, timestamp, fill_type (full/partial) | Immutable, append-only per order | UUID, FK to Order | — |
| **DecisionRecord** | The canonical, reconstructable record of one full decision cycle (§4) | Aggregates FeatureSnapshot, CandidateTrade, CostEstimate, RiskDecision, OrderRequest/Order/Fill refs, autonomy level, all version IDs | Immutable once finalized | UUID | Aggregates all of the above |
| **StrategyVersion** | One versioned Plane 2 artifact (deterministic or LLM-based) | version_id, plane2_type (baseline/llm), code/config hash, parent_version (lineage), promotion_status | Immutable once created; promotion_status transitions via §14 | version_id (content-addressed where feasible) | — |
| **ModelVersion** | A pinned model/weight/prompt snapshot, if Plane 2 uses one | version_id, backbone identifier, prompt/weight hash, training/eval data cutoff (for ER-3) | Immutable | version_id | Parent StrategyVersion |
| **ConfigurationVersion** | A snapshot of all Plane 0 operator-set values active at a point in time | version_id, values{}, effective_from, set_by (operator, always) | Immutable once effective; new config = new version, never in-place edit | version_id | — |
| **RiskRuleVersion** | A snapshot of Plane 3's risk-rule logic/thresholds | version_id, rule_set_hash, effective_from | Immutable; tracked separately from general Plane 3 versioning per RR-9 | version_id | — |
| **Experiment** | One Research-environment run, successful or not (§11) | experiment_id, hypothesis, candidate_strategy_version, baseline(s) compared, evaluation window, split declaration, result summary, promoted (bool) | Immutable once completed | experiment_id | StrategyVersion(s) under test |
| **EvaluationRun** | A single harness execution producing comparative results (§11) | run_id, experiment_id (FK), data_version, split spec, contamination-check result, PBO/CSCV correction applied, regime-segmented results, pass/fail vs. pre-registered criteria (ER-8) | Immutable | run_id | data version, all StrategyVersions compared |
| **PromotionCandidate** | An Experiment's output packaged for human review (§14) | candidate_id, experiment_id (FK), evaluation_run_id (FK), reviewer, decision (approve/reject), decision_timestamp | Immutable once decided | candidate_id | — |
| **AutonomyLevel** | Current + historical autonomy-level state (AR-1, AR-5) | level (0–3), set_by (operator), effective_from, effective_to | Append-only (transitions, never edited in place) | (level, effective_from) | — |

**Deliberately not modeled yet (per "don't over-engineer fields not yet required"):** short positions, F&O instruments, multi-currency, multi-broker simultaneous execution, and any self-modifying-code artifact (Type 6 self-improvement is out of scope per Stage 2 ADR-2, so no domain object exists for it). If any of these become required, they are additive, not a redesign of the objects above.

---

## 3. Plane interfaces

### 3.1 Plane 1 → Plane 2

Plane 2 receives exactly one thing per decision cycle: a **FeatureSnapshot** (§2), plus read-only access to the current permitted-universe list (from Plane 0, passed through Plane 1 — Plane 2 never queries Plane 0 directly, keeping Plane 2 fully stateless with respect to governance). Plane 2 has **no ability to request additional data mid-cycle from outside the snapshot** — if a strategy needs a data category not yet in the snapshot contract, that is a data-requirement change (DR-3/DR-7 style) handled at Plane 1, not an ad hoc query Plane 2 issues itself. This keeps Plane 2 swappable (FR-6) and keeps every input to a decision fully reconstructable (FR-5) from the FeatureSnapshot's own version reference.

### 3.2 Plane 2 → Plane 3 — the Candidate Trade contract

This is the single most load-bearing interface in the system (per Stage 2 §4/§8), because it is the only channel through which Plane 2's output can ever affect the real world, and it must contain everything Plane 3 needs while conferring zero execution authority.

**CandidateTrade (canonical, immutable, schema-validated at the boundary):**

```
CandidateTrade {
  candidate_id: UUID
  instrument_id: string            # must be in the permitted universe; Plane 3 re-checks independently (RR-4)
  timestamp: datetime (UTC)
  action: enum { BUY, SELL, HOLD }  # HOLD is first-class, never inferred from absence (TR-4)
  size_hint: float | null           # a *suggestion* (e.g., "high conviction"), NOT a share/rupee quantity —
                                     # Plane 3 alone converts this to an actual quantity (TR-3)
  confidence: float [0,1]           # mandatory, never optional (SF-10)
  uncertainty_band: enum {LOW, MEDIUM, HIGH} | null
  rationale: string                 # human-readable, mandatory, non-empty (RR-7) — a candidate with empty/null
                                     # rationale is rejected by Plane 3's schema validator before any risk logic runs
  input_snapshot_id: UUID (FK → FeatureSnapshot)   # RR-7 attributability
  strategy_version_id: UUID (FK → StrategyVersion)
  model_version_id: UUID | null (FK → ModelVersion)  # null for the deterministic baseline
}
```

**What this contract explicitly does NOT contain, by design:** an actual order quantity, a broker instruction of any kind, any credential, or any field that could be interpreted as "execute this." `size_hint` is deliberately named to avoid the appearance of a binding quantity — Plane 3's sizing module (§8) is the only place a real quantity is ever computed. This is the concrete implementation of Stage 2's "narrow, well-typed interface... not an order" and directly satisfies TR-3 (Plane 3 alone owns sizing) and RR-7 (nothing crosses without a rationale).

**Validation at the boundary:** Plane 3 runs a schema validator on every incoming CandidateTrade *before* any risk logic executes. A malformed object (missing rationale, confidence out of range, unknown instrument_id, action not in the enum) is rejected outright, logged as a rejected-at-ingestion event, and treated as "no candidate this cycle" (SF-3). Plane 2 is never trusted to have validated its own output.

### 3.3 Plane 3 → Broker

See §10 for the full broker-abstraction interface. At the boundary level: Plane 3 emits an **OrderRequest** (§2) only after a CandidateTrade has cleared risk validation and sizing; the broker adapter translates OrderRequest into broker-specific API calls and returns only broker-confirmed state (never assumes success from "request sent," per SF-5).

### 3.4 Plane 3 → Plane 1 (reconciliation)

After every broker interaction (order ack, fill, rejection, or unresolved/ambiguous response), Plane 3 emits a reconciliation event back to Plane 1, which updates PortfolioState (§2) as a new append-only record. Plane 1 never overwrites a prior PortfolioState record — FR-4's "at all times" requirement is satisfied by always being able to read the latest reconciled record plus its full history, not by mutating a single row.

### 3.5 Plane 1/4 → Research

The Research environment reads **only**: (a) historical MarketData/FeatureSnapshot records via Plane 1's normalization pipeline (the identical pipeline live trading uses, per Stage 2 §11), and (b) historical DecisionRecord/EvaluationRun data from Plane 4/Research's own store, for meta-evaluation. Research has a read-only, versioned data connection; it has no connection object, credential, or network route to Plane 3's broker adapter or Plane 0's governance store at all — this is enforced at the deployment-topology level (§20), not just at the API level, per Stage 2 §11/§16.

---

## 4. Canonical decision schema

The **DecisionRecord** (§2) is the single structured artifact that answers every question in Stage 2 §12 without re-derivation. It is not a log line; it is a first-class, versioned object assembled incrementally as a decision cycle proceeds through the planes (§8's lifecycle), and only marked "finalized" once the cycle completes (through outcome/cost reconciliation, or through an explicit terminal state like "rejected at risk" or "no candidate this cycle").

```
DecisionRecord {
  decision_id: UUID
  instrument_id: string
  cycle_timestamp: datetime (UTC)
  autonomy_level: int (0-3)                          # AR-5
  input_snapshot_id: UUID (FK → FeatureSnapshot)      # "what did it know"
  data_sources: [{source, version, timestamp}]        # "what data did it use"
  candidate_trade_id: UUID | null (FK)                # "what did it decide" — null if Plane 2 produced nothing
  rationale: string | null                            # denormalized copy of CandidateTrade.rationale — "why"
  strategy_version_id: UUID | null
  model_version_id: UUID | null
  cost_estimate_id: UUID | null (FK → CostEstimate)
  risk_decision_id: UUID | null (FK → RiskDecision)   # "what risk limits were applied" + pass/fail state
  order_request_id: UUID | null (FK)
  order_id: UUID | null (FK)                          # "what order was generated"
  fills: [Fill]                                        # "what actually happened" — broker-confirmed only
  actual_cost_id: UUID | null (FK → ActualCost)        # "what did it cost," reconciled against cost_estimate
  realized_pnl_delta: float | null                     # tied back through PortfolioState
  terminal_state: enum { NO_CANDIDATE, REJECTED_AT_RISK, SUBMITTED, FILLED, PARTIALLY_FILLED,
                          CANCELLED, REJECTED_BY_BROKER, RECONCILIATION_REQUIRED }
  risk_rule_version_id: UUID                           # always present, even on a HOLD/no-candidate cycle
  config_version_id: UUID                              # governance snapshot active at cycle time
  finalized_at: datetime (UTC) | null
}
```

**Rule:** no free-form log statement is ever treated as a substitute for a field in this record. Application logs (§18) may exist for operational debugging, but the DecisionRecord is the only artifact FR-5/RR-7/§M reconstruction is ever performed against. Every decision cycle — including HOLD and "no candidate produced" cycles — produces exactly one DecisionRecord, per TR-4's "hold is a first-class decision, not a silent no-op."

---

## 5. Data pipeline

```
External source
      ↓
Adapter (source-specific, behind common interface — TR-6)
      ↓
Raw data (stored as received, before any transformation — audit/replay value)
      ↓
Validation (schema check, plausibility bounds e.g. price > 0, volume ≥ 0)
      ↓
Freshness check (SF-2): timestamp age vs. configurable per-instrument threshold;
      stale data is routed to the SF-1 (missing) path, never silently used as current
      ↓
Normalization: unify field names/units across sources into the canonical MarketData schema;
      all timestamps converted to and stored as UTC; display/decision-window logic uses IST via
      a single shared time utility (shared/time/), never ad hoc per-module conversion
      ↓
Corporate-action handling: splits/bonuses/dividends applied at this stage against DR-2 data,
      producing adjusted series; the *unadjusted* raw record is retained separately (never overwritten)
      so historical replay can reconstruct exactly what was knowable at each point in time
      ↓
Canonical MarketData schema (§2) — this is what everything downstream consumes
      ↓
Feature/context formation → FeatureSnapshot (§2), versioned by feature-set version
      ↓
Plane 2
```

**Data contracts:** every adapter must produce the canonical MarketData shape before anything downstream sees it; no Plane 2 implementation is permitted its own parallel ingestion path (Stage 2 §7's "data flow principle," enforced here by the import-graph rule in §1 — `intelligence/` cannot import `data/adapters/` directly, only `data/features/`'s output type).

**Missing-data behavior (SF-1):** if a required feature cannot be computed because an upstream field is missing, the FeatureSnapshot is marked incomplete for that instrument and Plane 2 is never invoked for it that cycle; a DecisionRecord with terminal_state derived accordingly is still produced (so the gap itself is auditable, not silently absent from the record).

**Stale-data behavior (SF-2):** identical downstream handling to missing data — staleness is not a softer condition than absence.

**Correction/revision handling:** if a data provider revises a historical value (e.g., a corrected close price), this is stored as a *new* raw record with its own ingestion_time, never as an in-place edit to the original — this preserves the ability to say "what did the system know at decision time," which is a different, and for audit purposes more important, question than "what do we now know was true."

**Historical data versioning / reproducibility:** the normalization pipeline's output for any given raw-data snapshot must be deterministic and re-runnable — the same raw inputs plus the same normalization code version must always produce the same MarketData records. The **data snapshot version** referenced throughout §2/§4 identifies exactly this (raw data set + normalization code version), which is what makes ER-2's "genuinely held-out" claim and §19's reproducibility requirement checkable rather than assumed.

---

## 6. Cost Model

**Design:** a single, shared package (`risk_execution/cost_model/`, imported identically by `research/harness/` — never duplicated) computing both **CostEstimate** (pre-trade) and **ActualCost** (post-trade reconciliation), per §2.

**Components covered (India-specific, per Stage 1 DR-4):**
- Brokerage (broker-specific fee schedule — parameterized, not hardcoded, since broker selection is deferred per Stage 2 §18)
- Securities Transaction Tax (STT) — differs for delivery vs. intraday (ties to TR-5's distinction)
- Exchange transaction charges
- SEBI turnover fees
- GST (on brokerage + exchange charges)
- Stamp duty (state-dependent in principle; India's stamp duty on securities is centrally collected at a uniform rate since the 2020 amendment, but the Cost Model treats the rate as a versioned parameter, not a hardcoded constant, so a future change doesn't require a code change — just a new parameter version)
- Estimated slippage (pre-trade: a modeled estimate, using DR-5 order-book/microstructure data where available, falling back to a conservative default when it isn't — see Open Question in §21 carried from Stage 2)
- Realized slippage and market impact (post-trade: decision-time reference price vs. actual fill price, per PR-7)

**Separation of concerns:**
```
CostModel {
  estimate(candidate_trade, instrument, market_snapshot, cost_model_version) → CostEstimate
  reconcile(order, fills, cost_model_version) → ActualCost
}
```
Both methods are pure functions of their inputs plus a pinned `cost_model_version` — no hidden global state, no implicit "current rates," so that a Research-environment backtest run against a 2024 cost_model_version and a live decision run against a 2026 cost_model_version cannot silently cross-contaminate (this is the concrete mechanism behind Stage 2 §7's "cost model drift" risk mitigation).

**Versioning:** `cost_model_version` bundles the exact fee-schedule/tax-rate parameter set in effect; a new version is issued whenever any underlying rate changes (tracked via DR-6's regulatory-update monitoring, which raises an operator alert — a rate change is never silently absorbed into the Cost Model without an explicit new version and operator awareness, consistent with AR-2's "no silent self-promotion" spirit extended to cost assumptions).

---

## 7. Risk Engine

**Design:** `risk_execution/risk_engine/` is a deterministic, side-effect-ordered pipeline. It has **hard veto authority** — Plane 2 has no code path that bypasses it, because Plane 2's only output (CandidateTrade) physically cannot reach the broker adapter except by passing through this module first (enforced by the module dependency graph in §1: `broker/` only accepts input from `sizing/`, which only accepts input that has already cleared `risk_engine/`).

**Requirement mapping:**

| Requirement | Engine responsibility | Mechanism |
|---|---|---|
| RR-1 (max exposure) | Reject/resize any candidate that would push aggregate exposure past the operator-configured percentage-of-capital limit | Computed against current PortfolioState + the candidate's prospective size, before sizing is finalized |
| RR-2 (leverage/margin) | Reject/resize against operator-configured max leverage/margin utilization | Requires broker-reported margin data (via reconciliation, §3.4); if unavailable, fails closed (treats as "cannot verify" → reject, not "assume within limits") |
| RR-3 (drawdown halt) | Compute realized/unrealized drawdown against PortfolioState history; if breached, engine enters a HALT state that rejects all new position-opening candidates (holds/closes still permitted) until operator-reviewed reset | HALT state is itself a Plane 0-visible, operator-clearable flag — the engine cannot silently self-clear it |
| RR-4 (universe) | Independently re-check instrument_id against the current permitted-universe list (never trusts Plane 2's own filtering) | Direct lookup against Plane 0's universe config, read fresh each cycle |
| RR-5 (order-rate ceiling) | Track a rolling order-submission rate per second/window; reject submissions that would exceed the exchange-mandated threshold (10 OPS, per Stage 1 REG-4, pending final NSE/ISF circular confirmation — see §21) | A rate limiter local to the broker adapter boundary, not just an advisory counter |
| RR-6 (account scope) | Verify every order is for the single configured operator account (and immediate-family sub-accounts if ever configured — not built in v1) | Static configuration check; no dynamic "which account" logic exists to be gamed |
| RR-7 (attribution) | Reject any CandidateTrade lacking a non-empty rationale or a resolvable input_snapshot_id, before any other check runs | Schema validation at ingestion (§3.2) |
| RR-8 (kill switch) | Before *every single* action (not just at cycle start), check Plane 0's kill-switch state; if set, no further processing occurs for that cycle regardless of what stage it's in | Checked at the top of every method in the risk_engine call chain, not just once per cycle — this is deliberate defense-in-depth against a mid-cycle race |
| RR-9 (self-improvement boundary) | The risk_engine module has no write dependency from `research/` or `intelligence/` anywhere in its import graph or its runtime configuration source | Structural (§1's import-graph rule), not a runtime check — this is intentional, since a runtime check could itself be a target for erosion, while an absent code path cannot be |

**Order validation sequence (per cycle):**
```
1. Kill-switch check (RR-8) — halts immediately if set
2. Schema validation of CandidateTrade (RR-7)
3. Universe re-check (RR-4)
4. HALT-state check (RR-3, if previously triggered)
5. Cost estimation (§6) — needed before exposure math, since cost affects effective capital use
6. Exposure check (RR-1)
7. Leverage/margin check (RR-2)
8. Order-rate check (RR-5)
9. Account-scope check (RR-6)
10. → Sizing (§8)
11. → Sanity checks (SF-8)
12. → Order generation
```

**Rejection behavior:** any failed check produces a RiskDecision with final_verdict = reject and a specific reason per failed check (not a generic "rejected"); the DecisionRecord's terminal_state is set to REJECTED_AT_RISK. Rejection is never silent — it is exactly as loggable and reviewable as an approval.

**Fail-safe behavior:** any check that cannot be *evaluated* (missing margin data, unreachable Plane 0 config store) is treated as a **failed** check, never a passed one — "cannot verify" and "verified and safe" are never conflated (this is the Risk Engine's specific instantiation of the system-wide fail-closed principle, Stage 2 Principle 7).

**State required by the engine:** current PortfolioState (read from Plane 1), current RiskRuleVersion (read from Plane 0, never self-modified — RR-9), current ConfigurationVersion (thresholds), rolling order-rate counters (local, ephemeral, reconstructable from Order records if lost).

**Audit records:** every check evaluated, with its individual pass/fail state and the values compared, is stored in the RiskDecision object (§2) — this is what makes Plane 4/observability's "what risk limits were applied" question (Stage 2 §12) answerable without re-deriving anything.

---

## 8. Position sizing

Sizing is a **separate, explicit module** (`risk_execution/sizing/`) downstream of the risk-engine's approval checks, not fused into them — this separation matters because sizing logic (how much to buy, given an approved candidate and available capital/limits) is a different kind of rule than risk-limit enforcement (whether a trade is allowed at all), and conflating them was flagged in Stage 2 §20 as a risk ("Plane 2/Plane 3 interface becomes a de facto backdoor").

```
Candidate Trade (with confidence, size_hint)
      ↓
Eligibility (RR-4 universe re-check — done in risk_engine, sizing trusts this has already passed)
      ↓
Cost estimate (from §6, already computed in the risk_engine pipeline)
      ↓
Risk constraints (RR-1/RR-2's *remaining headroom*, not just pass/fail — sizing needs the actual
      available-exposure and available-leverage numbers, not merely "within limits" or "not")
      ↓
Sizing rule: converts (confidence, size_hint, available headroom, cost estimate) into an
      actual share quantity, via an explicit, versioned, inspectable function — NOT an LLM call,
      and not a function Plane 2 can influence beyond its declared confidence/size_hint inputs
      ↓
Sanity checks (SF-8): e.g., resulting quantity is not zero-or-negative when action≠HOLD,
      resulting notional value is not absurdly large/small relative to typical position sizes,
      resulting order would not itself trip RR-5's rate limit in combination with recent orders
      ↓
Approved (with final quantity) / Rejected (with reason)
```

**On numeric thresholds:** per Stage 1/Stage 2's explicit instruction not to invent operator decisions, the sizing rule's *shape* (e.g., "size scales with confidence within a min/max band defined by RR-1's headroom") is specified now; the actual min/max percentages, confidence-to-size mapping curve, and default fallback size are all **operator-configurable values read from Plane 0**, not constants in code. The sizing module is fully buildable and testable today using placeholder/example configuration values, with the real values supplied by the operator before paper trading begins (this satisfies §16's "system must be capable of accepting them as configuration" without inventing numbers here).

**Anti-gaming note (from Stage 2 §20's risk table):** because `size_hint` and `confidence` are the only levers Plane 2 has over sizing, and because the actual quantity computation lives entirely in Plane 3, any future concern about Plane 2 "learning" to send inflated confidence values to get larger sizes is addressed by (a) sizing's own sanity bounds being independent of Plane 2's self-reported confidence in the worst case (a hard ceiling regardless of confidence), and (b) periodic promotion-review auditing of the empirical relationship between Plane 2's reported confidence and realized outcome quality (a concrete, checkable version of "periodic review of whether confidence outputs are being gamed").

---

## 9. Order state machine

```
CANDIDATE           (a CandidateTrade exists, not yet risk-approved)
    ↓ (risk engine + sizing approve)
APPROVED            (an OrderRequest exists, not yet sent to broker)
    ↓ (submitted to broker adapter)
SUBMITTED           (sent; broker has not yet confirmed receipt)
    ↓ (broker acknowledges receipt)
ACKNOWLEDGED        (broker has the order; not yet filled)
    ↓                                              ↓
PARTIALLY_FILLED ←──────────────────────→ FILLED
    ↓ (remaining qty cancelled or expires)          
CANCELLED                                          
    
[from SUBMITTED or ACKNOWLEDGED, broker may instead return:]
REJECTED            (broker refuses the order — logged with broker's stated reason)

[from any post-SUBMITTED state, if the broker's response is ambiguous, times out, or contradicts
 the system's own state:]
RECONCILIATION_REQUIRED   (terminal until a human or an automated reconciliation job resolves it
                            against the broker's own order/position query endpoint)
```

**Valid transitions only** — the state machine implementation rejects (raises, does not silently coerce) any attempted transition not in the table above; e.g., CANDIDATE → FILLED directly is not a valid transition even if some race condition suggested it, since that would mean the audit trail (RR-7, FR-5) skipped the risk-approval step, which must never happen.

**Ambiguous broker response handling:** per Stage 2 §10's confirmation discipline, any broker response that is unparseable, contradicts the last known state, or simply doesn't arrive within a defined timeout moves the order to **RECONCILIATION_REQUIRED**, not to a best-guess state. The system never marks an order FILLED, CANCELLED, or REJECTED based on inference — only on an explicit, parsed broker confirmation matching that state. RECONCILIATION_REQUIRED orders trigger an operator alert (§18) and block further new orders for that instrument until resolved, as a conservative default (this is a design choice consistent with SF-9's "default to the more conservative action").

**"Request sent" ≠ "trade happened":** enforced structurally — SUBMITTED and ACKNOWLEDGED are both pre-fill states, and PortfolioState (§2) is only updated from FILLED/PARTIALLY_FILLED events carrying actual Fill records, never from SUBMITTED.

---

## 10. Broker abstraction

**Interface (broker-neutral, implemented per-broker in `risk_execution/broker/adapters/`):**

```
BrokerAdapter {
  authenticate(credentials) → Session
  get_account_state(session) → {cash_balance, margin_available, margin_used}
  get_positions(session) → [Position]           # broker's own view — authoritative, per FR-4
  place_order(session, OrderRequest) → {broker_order_id, initial_status}
  modify_order(session, broker_order_id, changes) → status
  cancel_order(session, broker_order_id) → status
  get_order_status(session, broker_order_id) → OrderStatus
  get_fills(session, broker_order_id) → [Fill]
}
```

**Normalization of broker-specific behavior:** each adapter is responsible for translating its broker's specific status codes, error formats, and field names into the canonical Order/Fill/OrderStatus shapes defined in §2 — no broker-specific vocabulary (e.g., a particular broker's proprietary status string) ever leaks past the adapter boundary into `risk_execution/order_state_machine/` or above.

**Where broker-specific regulatory constraints live:** static-IP whitelisting, OAuth/2FA (REG-3), and per-broker order-rate quirks are configured *within* each broker adapter's connection setup, not in the broker-neutral interface or anywhere in `risk_execution/risk_engine/` — the risk engine's RR-5 rate check is broker-agnostic (a system-wide rate ceiling), while any *additional*, broker-specific throttling (if a given broker imposes a stricter limit than the exchange-wide one) is an adapter-level concern layered on top, never a replacement for the system-wide check.

**Broker selection:** deliberately not made in this document, per Stage 2 §18's explicit deferral pending REG-6 (ToS review). The interface above is fully specifiable and buildable — including a first adapter implementation against a **paper-trading/sandbox mode** (§14 of Stage 2's environment table) — without naming a production broker. A `SimulatedBrokerAdapter` (implementing the identical interface, backed by the Research/paper-trading fill simulation) is the first concrete adapter built, satisfying Slice 6 (§21) without waiting on REG-6.

---

## 11. Research / Backtesting engine

**Structure (`research/`):**

- **`harness/`** — orchestrates a full Evaluation Run: loads a declared chronological split (ER-2), runs the candidate StrategyVersion and all declared baselines (ER-1) against identical historical data, applies the Cost Model (§6, same package as live), and produces regime-segmented results (ER-6). The harness **refuses to execute** an Evaluation Run that lacks a declared, checked split (Stage 2 §11) — this is a hard precondition, not a best-practice suggestion buried in documentation.
- **`contamination/`** — before any LLM-backbone StrategyVersion is evaluated, compares the evaluation window against that ModelVersion's declared knowledge-cutoff date (a required field on ModelVersion, §2); any overlap is flagged and the run is blocked pending explicit operator override with a logged justification (ER-3). This directly operationalizes the Alpha Illusion / Profit Mirage / KTD-Fin findings from Stage 0 (01 §7) as a mechanical gate, not a reviewer's judgment call alone.
- **`stats/`** — implements a PBO/CSCV-style correction (ER-4): every variant *attempted* within an experiment lineage (not just the reported winner) is logged via the Experiment/EvaluationRun records (§2), and the correction is computed across that full attempted set. This is the concrete mechanism by which the harness cannot be gamed by silently discarding failed variants before reporting — the harness's storage schema makes "hide the failures" structurally difficult, since an EvaluationRun cannot exist without being linked to its parent Experiment record, and Experiment records are never deleted.
- **`experiments/`** — the append-only store of every Experiment (§2), win or lose. A dashboard/report (§18) can be built over this store, but the store itself is the source of truth, not the report.
- **`promotion/`** — packages a completed, passing Experiment + EvaluationRun into a **PromotionCandidate** (§2) for human review (§14). This module has *write* access only to its own promotion-candidate store — it has no ability to place the candidate into paper trading or live use itself; that transition is an explicit, separate operator action (§14).

**What an Evaluation Run contains (concretely, per §2's EvaluationRun object):** run_id, the exact data_version used, the split specification (train/validation/test date ranges, declared before results are seen), contamination-check outcome, the full set of variants this run's correction was computed against, per-regime performance figures (cost-adjusted, per ER-5/ER-6), and an explicit pass/fail against the Experiment's pre-registered criteria (ER-8) — never a bare "here's the Sharpe ratio" without this surrounding context.

**Failed experiments are first-class:** an Experiment that fails to beat its baseline, or fails a contamination check, or fails its pre-registered disqualifying criteria, is stored with the same completeness as a successful one, and is included in any future ER-4 multiple-testing correction involving related strategy lineages. The harness's reporting layer has no code path that filters an Experiment out of the historical record based on its outcome.

---

## 12. Baseline strategy

**Candidates considered** (evaluated against: understandable, reproducible, defensible, simple, suitable for Indian equities, implementable without an LLM, strong enough to be a meaningful baseline):

| Candidate | For | Against |
|---|---|---|
| **Buy-and-hold on a broad index proxy (e.g., an equal-weight or cap-weighted basket of the permitted universe)** | Simplest possible; matches DeMiguel et al.'s naive-diversification standard (Stage 0 02 §3.1, §9) directly; zero parameters to overfit; StockBench (02 §4.2) used exactly this as its comparator, so it is also externally standard | Arguably *too* passive as the system's actual v1 Plane 2 — it never generates a sell signal, so it doesn't exercise Plane 3's full decision-cycle logic (TR-4's hold-as-decision, sizing, etc.) in a meaningful way beyond the initial purchase |
| **A single, documented momentum factor strategy (e.g., 12-month or 6-month price momentum, monthly rebalance) on NSE/BSE large-cap, liquid, F&O-eligible names** | Directly supported by Stage 0's finding that momentum effects have historically existed in Indian equities (02 §12); generates real buy/sell/hold decisions each rebalance, genuinely exercising the full Plane 2→3 pipeline; well-documented in classical literature, so it is defensible and reproducible without inventing a novel rule | Requires picking specific parameters (lookback window, rebalance frequency, ranking cutoff) that must themselves be chosen defensibly, not arbitrarily — addressed below |
| **A mean-reversion factor (e.g., short-term reversal)** | Also documented in classical literature | Less consistently supported in the specific Indian-equity sources Stage 0 surfaced than momentum; would require additional targeted verification not yet done |
| **A volatility-targeting/risk-parity static allocation** | Emphasizes risk-adjusted return, aligns with PR-8's regime-robustness framing | More about capital allocation across the universe than about generating instrument-level buy/sell signals; better suited as a *sizing overlay* than a Plane 2 decision generator |

**Decision: adopt a two-tier baseline, both required by ER-1, not a single strategy:**

1. **Tier 1 — Naive static baseline (ER-1's "(a)"):** equal-weight buy-and-hold across the permitted universe, rebalanced only on universe changes (TR-7). This is the DeMiguel-et-al.-standard floor every later candidate must clear.
2. **Tier 2 — Well-tuned deterministic strategy (ER-1's "(b)"), and Plane 2 v1 itself (per ADR-1):** a documented 12-month price-momentum factor (skip the most recent month, per the classical momentum-literature convention of avoiding short-term reversal contamination), ranking the permitted universe monthly, going long the top decile/quintile (exact cutoff is a configuration parameter, not hardcoded), equal-weighted within the selected set, with position changes only at monthly rebalance — a fully deterministic, fully inspectable rule with no LLM involvement whatsoever, satisfying "do NOT choose an LLM strategy as the baseline."

**Why momentum specifically, and why not treat parameter choice as arbitrary:** the 12-1 month momentum formulation is the single most standard specification in the classical asset-pricing literature (predating and independent of anything LLM-related), which means its parameters are externally documented and defensible rather than something this project tuned to look good — directly avoiding the "researcher degrees of freedom" problem ER-4/the Alpha Illusion paper warns about (01 §7). Any parameter *within* this family that Stage 3 or later work wants to sensitivity-test must go through the Research harness's PBO/CSCV correction (§11) like any other variant — the baseline strategy is not exempt from the overfitting discipline just because it's "the baseline."

**What this baseline is for:** per the prompt's own framing, it establishes the performance floor every future Plane 2 candidate (deterministic or LLM-based) must clear via ER-1 comparison before promotion (§14) — it is not a claim that momentum is expected to be profitable after costs; that is exactly what the Research harness (§11) exists to test, honestly, including the possibility that it isn't.

---

## 13. First AI / LLM component

**Explicit hypothesis (required by the prompt, and directly responsive to Stage 0's finding that no study isolates "better discovery" from "better adaptation" while holding effort constant, 02 §2):**

> "Adding LLM-based interpretation of recent company-specific news/disclosures as one additional input signal, layered on top of the Tier-2 momentum baseline's ranking, should improve risk-adjusted return (Sharpe, and specifically drawdown during earnings/news-driven volatility) relative to the momentum baseline alone, evaluated on the same permitted universe over the same walk-forward windows."

This hypothesis is deliberately narrow and falsifiable, consistent with Stage 0's finding that "capability on static financial knowledge tasks does not translate into effective trading behavior" (02 §4.2) and that multi-agent/complex designs show no evidence of outperforming simpler ones (02 §O) — it does not propose an agentic multi-step reasoner, a multi-agent debate structure, or any self-improvement mechanism. It proposes the smallest possible LLM contribution: **one additional signal, not a replacement decision-maker.**

**Specification:**

| Aspect | Design |
|---|---|
| Input | A FeatureSnapshot already containing the momentum-ranking output (from the Tier-2 baseline, treated as one input among several — per Stage 2 ADR-1 Option C's framing), plus a bounded set of recent (e.g., trailing N-day) company disclosures/news items for the instrument, sourced via DR-7 (adapter reserved but not populated in v1 per Stage 2 §7 — populating it is itself part of this component's build, not assumed already done) |
| Output | A single bounded adjustment signal (e.g., a sentiment/materiality score in a fixed range, or a categorical flag such as "no adjustment / reduce conviction / increase conviction"), NOT a raw buy/sell decision and NOT a raw quantity |
| What it may influence | Only the `confidence` field of the resulting CandidateTrade (§3.2) — it modulates how strongly the momentum signal is expressed, within the same sizing/risk pipeline as the deterministic baseline |
| What it cannot influence | Instrument universe membership, sizing arithmetic, any RR-x check, the action enum's HOLD/BUY/SELL selection logic itself (that remains the deterministic momentum rule) — this is a deliberate, narrow blast radius |
| Versioning | A ModelVersion (§2) record, including backbone identifier and declared knowledge-cutoff date (mandatory field, feeding ER-3's contamination check directly) |
| Evaluation | Run through the Research harness (§11) exactly like any other candidate: compared against the Tier-2 baseline *without* the LLM adjustment, on identical data, with the contamination check specifically exercised (since this is the system's first LLM-backbone component and therefore the first real test of ER-3's mechanism) |
| Replacement | Because its only output is a bounded confidence-modulation signal consumed through the same CandidateTrade contract as the baseline, it can be swapped for a different backbone, a different signal source, or removed entirely, by changing only `intelligence/llm_component/` — Plane 3 and the baseline strategy are untouched either way (FR-6) |

**What this component explicitly is not:** it is not an autonomous analyst agent, not a multi-agent system, not a component with tool-use/browsing/execution capability, and not a component with any credential or broker access (§17). It is the narrowest possible test of "does an LLM signal add value over the deterministic floor," which is exactly the comparison Stage 0 found essentially absent from the published literature (02 §9's evidence-gap list) and which this project's own evaluation discipline is built to answer honestly, including a "no" answer.

---

## 14. Self-improvement — promotion boundary

Self-improvement (Stage 2 ADR-2 types 2–5) is designed, in this stage, purely as a **process**, not as a running mechanism yet — no automated self-improvement loop is built in the first implementation slices (§21); this section specifies the boundary any future self-improvement experiment must operate within, so that when one is eventually built (entirely inside `research/`), it has a pre-existing, non-negotiable gate to pass through rather than an ad hoc one invented at that time.

```
Research experiment (research/experiments/)
       ↓
Candidate artifact (a new StrategyVersion or ModelVersion, produced by the experiment)
       ↓
Evaluation (research/harness/ — ER-1 through ER-8 in full, including contamination and PBO/CSCV correction)
       ↓
Baseline comparison (against current live baseline AND current live Plane 2, per ER-1(c))
       ↓
Human review (an operator examines the PromotionCandidate record — §2 — including the full
       Experiment/EvaluationRun history, not a summary alone)
       ↓
Versioned promotion (operator explicitly sets PromotionCandidate.decision = approve;
       this is the ONLY code path that can move a StrategyVersion's promotion_status forward —
       no automated job, scheduled task, or research-environment process can set this field)
       ↓
Paper trading (the promoted StrategyVersion now runs, unmodified, inside intelligence/,
       exactly like any human-authored Plane 2 change would)
       ↓
Further validation (§15's paper-trading test suite; PR-1 through PR-9 measured live)
       ↓
Possible live promotion (a SEPARATE explicit operator decision — AR-2's "no self-promotion"
       applies here exactly as it applies to autonomy-level transitions)
```

**No automatic promotion, structurally enforced:** `PromotionCandidate.decision` is a field writable only by an authenticated operator action (governance-layer write permission — §16/§17), never by any process running inside `research/`. This mirrors RR-9's enforcement mechanism in §7: the boundary is a missing write-path, not a checked-and-hopefully-respected rule.

**What no self-improvement mechanism can ever modify, by construction (not by policy):** risk rules (RiskRuleVersion, §2, owned by Plane 0/`risk_execution/risk_engine/`, no write dependency from `research/`), the kill switch (`governance/killswitch/`, same isolation), operator constraints (ConfigurationVersion, Plane 0-owned), execution authority (the broker adapter's credentials live only in `risk_execution/broker/`, which `research/` cannot import), and autonomy level (AutonomyLevel, Plane 0-owned, transitions only via AR-2's explicit-operator-decision mechanism). Each of these is a restated Stage 2 guarantee, now pinned to a specific module/directory so it is a checkable build-time fact (via the §1 import-graph lint), not merely an intention stated in prose.

---

## 15. Testing design

| Test layer | Purpose | Example coverage |
|---|---|---|
| **Unit** | Individual function/module correctness | Cost Model component calculations; sizing-rule arithmetic; state-machine transition validity |
| **Integration** | Modules within one plane working together | Plane 1's ingestion→validation→normalization→feature pipeline end-to-end against a fixed historical dataset |
| **Contract** | Inter-plane interfaces match their declared schema (§3) | A CandidateTrade missing `rationale` is rejected by Plane 3's validator; a malformed FeatureSnapshot is rejected before reaching Plane 2 |
| **Simulation** | Full decision-cycle behavior against a simulated market, without a real broker | End-to-end cycle from ingested tick to DecisionRecord, using `SimulatedBrokerAdapter` (§10) |
| **Fault-injection** | SF-1 through SF-10, each individually | Withhold a data field (SF-1); delay a feed past freshness threshold (SF-2); return malformed Plane 2 output (SF-3); time out an external API (SF-4); simulate broker unreachability (SF-5); drop connectivity entirely (SF-6); inject a simulated circuit-breaker/halt signal (SF-7); inject a candidate designed to fail the sanity check (SF-8); force disagreeing internal signals once Plane 2 has multiple components (SF-9, deferred until such a component exists); force a low-confidence candidate through and verify the fallback fires (SF-10) |
| **Adversarial risk tests** | RR-1 through RR-9, each individually, with intentionally hostile inputs | Attempt to submit a candidate exceeding RR-1's exposure limit; attempt to exceed RR-5's order-rate ceiling via rapid submission; attempt to have a simulated self-improvement artifact write to RiskRuleVersion (must fail at the import/permission level, not just at runtime); attempt to disable the kill switch from within a simulated Plane 2/Research process (must fail, RR-8) |
| **Backtest validation** | The Research harness itself behaves correctly | A synthetic dataset with a known, injected look-ahead leak must be caught by ER-3's contamination check; a synthetic multi-variant search must produce the expected PBO/CSCV correction magnitude |
| **Paper-trading tests** | End-to-end behavior against live data with simulated execution | A full trading day's cycle produces a complete, reconstructable DecisionRecord chain; reconciliation correctly detects a deliberately-introduced position mismatch |
| **Deployment-gate tests** | The promotion boundary (§14) itself | Verify a PromotionCandidate cannot reach `approved` state without an authenticated operator action; verify a promoted StrategyVersion cannot be deployed to `live` without REG-1/4/5/6/7 gate flags all being explicitly closed (§20) |

**Mapping discipline:** every SF-x and RR-x requirement has at least one named test in the fault-injection or adversarial-risk rows above; §23's traceability matrix makes this mapping explicit and complete, per the prompt's instruction that no SF/RR requirement may lack a concrete future test.

---

## 16. Configuration

**Operator configuration** (Plane 0, `governance/config/` — human-set, system-read-only):
- Permitted instrument universe (TR-1)
- Autonomy level (AR-1, AR-2 — though *transitions* go through the AutonomyLevel append-only record, not a simple overwrite)
- Exposure limit (RR-1), leverage/margin limit (RR-2), drawdown limit (RR-3) — as parameter *values*; the rules themselves live in code/RiskRuleVersion
- Kill-switch state (AR-3) — though note: the kill switch is a *write-only-by-operator, read-by-everything* flag; it is intentionally not bundled into the general ConfigurationVersion object, since it must be independently and immediately actionable (§9 of Stage 2), not batched with other config changes
- Trading mode / environment target (which environment this deployment instance is, §20)
- Execution permissions (which order types are enabled, tying to Stage 1's still-open market/IOC-order question, REG-5)
- Active StrategyVersion and ModelVersion pointers (i.e., which promoted artifact is currently live/paper — this is the operator's promotion decision recorded as config, distinct from the artifact's own definition)

**System-generated state** (never operator-edited directly, always derived/computed): PortfolioState, Order/Fill records, DecisionRecords, RiskDecisions, reconciliation records.

**Versioned research artifacts** (Research-owned, immutable once created): StrategyVersion, ModelVersion, Experiment, EvaluationRun, PromotionCandidate.

**The non-silent-conversion rule (explicit mechanism, not just a statement):** the *only* code path that moves a versioned research artifact's identifier into operator configuration (i.e., makes a StrategyVersion "the active one") is the same authenticated-operator-write path described in §14's promotion boundary. There is no implicit or default-fallback logic anywhere that would cause a Research-produced artifact to become active configuration without that explicit write — this is checked by a contract test (§15) that attempts exactly this conversion through every non-approved path and asserts failure.

---

## 17. Security

**Credential boundaries:** broker credentials exist in exactly one place — `risk_execution/broker/`'s adapter implementations, loaded from environment-isolated secrets storage (never committed to any versioned artifact, per §19) — and nowhere else in the codebase. `intelligence/` (Plane 2, including the LLM component, §13) has zero credential access of any kind. `research/` similarly has no broker credential access, consistent with its complete isolation from live execution (Stage 2 §11/§16).

**Network boundaries:** the deployment topology (§20) provisions no network route at all from the Research environment or from any Plane 2 process to the broker's API endpoint or to Plane 0's write interface — this is a firewall/network-policy fact, not merely an application-level permission, per Stage 2 §16's instruction that isolation be structural.

**Plane 2 permissions:** read access to its own FeatureSnapshot input only; write access limited to producing a CandidateTrade object passed to Plane 3 through the defined interface (§3.2); no filesystem write access beyond its own logging output; no outbound network access except whatever is strictly required for its own inference (e.g., an LLM API call for the component in §13) — and even that is routed through an egress allowlist limited to the specific inference endpoint, not general internet access, given the LLM is treated as potentially compromised/untrusted per this section's governing assumption.

**Research permissions:** read access to historical Plane 1 data and the Cost Model; write access only to its own experiment/evaluation store; no access to live credentials, live broker connections, or Plane 0's write interface.

**Broker permissions:** the broker adapter itself operates under whatever the broker's own account-level permissions allow — no elevated or unusual API scope should be requested beyond order placement/modification/cancellation and account/position/order query, per REG-3's static-IP/OAuth/2FA requirements.

**Filesystem/process permissions:** each plane's runtime process runs under its own restricted service account/container (§20), such that even a full compromise of the Plane 2 process (including the LLM component) cannot read `risk_execution/broker/`'s credential files or write to `governance/config/`'s store, by OS-level/container-level permission, not merely by application logic choosing not to.

**Audit protection:** DecisionRecord and RiskDecision stores are append-only at the storage layer (no UPDATE/DELETE permission granted to any application service account, only INSERT) — this directly protects RR-7/FR-5's reconstructability guarantee against both bugs and any hypothetical compromised component attempting to cover its tracks.

**Treat the LLM as potentially compromised/untrusted — concretely, this means:** prompt-injected content reaching the LLM component (e.g., via a malicious or manipulated news item feeding §13's input) can, at worst, cause a bad `confidence` value or a garbled `rationale` string — both of which are bounded, schema-validated, and subject to the exact same risk/sizing/sanity pipeline as any other candidate. It cannot cause an unauthorized trade, an exfiltrated credential, or a bypassed risk check, because none of those capabilities are reachable from where the LLM component runs. This is the concrete, "lethal trifecta"-resistant design Stage 0 called for (00 §D.5, 01 §12), verified by a specific adversarial test category (§15).

---

## 18. Observability

**Structured logs:** every plane emits structured (not free-text) log events tagged with `decision_id` where applicable, enabling correlation across planes for a single decision cycle without needing the DecisionRecord alone (logs are for operational debugging/latency analysis; the DecisionRecord remains the authoritative reconstruction artifact per §4).

**Decision logs:** the DecisionRecord store itself (§4), queryable by instrument, date range, autonomy level, strategy version, or terminal state.

**Order logs:** the full Order state-history (§9), independent of DecisionRecord, for order-lifecycle-specific debugging (e.g., diagnosing a pattern of RECONCILIATION_REQUIRED outcomes with a specific broker).

**Risk logs:** every RiskDecision (§7), including passed checks, not only rejections — needed to later analyze whether risk limits are meaningfully binding or effectively decorative.

**Error logs:** exceptions/failures at any layer, tagged with the fault-injection category they correspond to where applicable (SF-1 through SF-10), to make post-incident review directly traceable to the requirement it relates to.

**Health state:** a simple, polled or pushed status per plane/adapter (data-feed connectivity, broker connectivity, Plane 2 process liveness) — feeding the operator-facing dashboard, not a heavyweight APM platform (per Stage 2 §18's stated scale-appropriate decision).

**Alerts:** triggered on — kill-switch activation, RR-3 drawdown HALT, any RECONCILIATION_REQUIRED order, any SF-x fault-injection-category event occurring in production (not just in tests), any REG-x gate-relevant regulatory-update detection (DR-6), and any PromotionCandidate awaiting review.

**Reconciliation reports:** scheduled (e.g., end-of-day) comparison of system-believed PortfolioState against a fresh broker query, surfacing any drift immediately rather than waiting for the next trade to expose it.

**P&L reports:** realized/unrealized P&L over operator-selected periods, always presented cost-adjusted (per ER-5's "no gross numbers presented as net" rule extended to live reporting, not just Research reporting).

**Experiment reports:** a view over `research/experiments/`'s full store (including failures), supporting the ER-8 "define disqualifying criteria in advance" workflow and the ER-4 correction's need to see the full attempted-variant set, not a curated subset.

---

## 19. Versioning

| Artifact | Versioning scheme | Notes |
|---|---|---|
| Code | Standard source-control commit hash, tagged at each release | Every other version below records the code commit hash active when it was created, for full reconstructability |
| StrategyVersion | Content-addressed hash of its defining code/config, plus an incrementing human-readable label | Immutable once created (§2) |
| ModelVersion | Explicit version_id including backbone identifier + prompt/weight hash + declared knowledge-cutoff date | The cutoff date is mandatory, not optional, since ER-3 depends on it |
| Prompts (if/when a prompt-based component exists) | Versioned as part of ModelVersion, never edited in place — a prompt change is a new ModelVersion | Directly implements FR-8's "distinguish genuine adaptation from self-modification" by making every prompt change a discrete, comparable artifact |
| Configuration | ConfigurationVersion, append-only, effective_from timestamped (§2, §16) | Never edited in place |
| Risk rules | RiskRuleVersion, tracked separately from general Plane 3 code versioning per RR-9 | This separation is deliberate: Plane 3's *code* may be refactored for engineering reasons without necessarily changing risk *rule* semantics, and RR-9's guarantee is specifically about the rule semantics, so the two must be independently verifiable |
| Cost Model | cost_model_version (§6) | Changes when any underlying rate/fee parameter changes |
| Data | data snapshot version (§5) = raw data set + normalization code version | Required for reproducing any historical backtest exactly |
| Experiments | experiment_id, immutable once completed (§2, §11) | Never deleted, including failures |
| Evaluation results | EvaluationRun, immutable, linked to the exact data/strategy/config versions used (§2) | This is what makes "reproduce why a historical trade happened" (Stage 2 §15) or "reproduce why a backtest concluded X" both actual capabilities |

**Reconstruction guarantee:** any DecisionRecord (§4) contains enough version references (strategy_version_id, model_version_id, cost_estimate's cost_model_version, risk_rule_version_id, config_version_id, input_snapshot_id → data snapshot version) that the exact conditions producing that decision can be reconstructed without ambiguity — this is checked directly by a dedicated integration test (§15) that picks a random historical DecisionRecord and verifies every referenced version is resolvable and internally consistent.

---

## 20. Environment design

| Environment | Can access | Can write to | Network access | Credentials present | Promotion rule |
|---|---|---|---|---|---|
| **Development** | Synthetic/sample data only | Local dev stores only | None external | None (mocked/stubbed adapters only) | N/A |
| **Research** | Historical Plane 1 data (read-only), shared Cost Model | Its own `research/` stores (experiments, evaluation runs) only | No broker network route provisioned at all (firewall-level, §17) | None | Produces StrategyVersion/ModelVersion candidates only; cannot self-promote (§14) |
| **Paper** | Live/replayed market data (read), simulated execution via `SimulatedBrokerAdapter` (§10) | Paper-scoped PortfolioState/Order/DecisionRecord stores, kept separate from live stores | Live *data* feeds only; no real broker order-placement endpoint | Data-feed credentials only; no live-broker trading credentials | Runs a promoted (§14) StrategyVersion, same promotion gate as any Plane 2 change |
| **Staging** (optional, per Stage 2 §21 open question — not required by any Stage 1 requirement) | Live data, live broker at minimal configured exposure | Live-scoped stores, isolated from full-live if the operator chooses to keep it a separate account/sub-limit | Live broker, live data | Live-broker credentials, scoped to minimal-exposure limits | Same promotion rule as live; not a lesser-gated environment |
| **Live** | Everything | Live PortfolioState/Order/DecisionRecord stores (source of truth) | Live broker, live data | Full live-broker credentials (§17-isolated to `risk_execution/broker/`) | Terminal — this is Plane 3/Plane 0's live instance itself |

**Artifact promotion rules across environments:** identical mechanism throughout — an operator-authenticated write to `PromotionCandidate.decision` (§14) is the only way an artifact moves from Research → Paper, and a separate, equally explicit operator decision moves Paper → Staging/Live (§14's "Possible live promotion" step), consistent with AR-2. No environment's deployment pipeline includes an automatic "if tests pass, promote" step for anything touching Paper or above.

**Research → live isolation, restated as a build fact:** this is enforced identically to §17 — network policy plus the §1 import-graph rule together make "Research reaches live execution" not just disallowed but architecturally absent, which is the concrete answer to this section's explicit instruction.

---

## 21. Implementation sequence

Refined from Stage 2 §19's build philosophy into concrete, independently testable vertical slices. Each slice ends in something demonstrable, not merely "code written."

```
Slice 0 — Repository scaffolding + import-graph lint rule (§1)
    Deliverable: empty module structure with the dependency-direction check enforced in CI,
    so every subsequent slice is built against the isolation guarantees from day one, not
    retrofitted later.

Slice 1 — Core domain models (§2)
    Deliverable: all domain objects as typed, tested data structures, with unit tests confirming
    immutability rules and required-field validation (e.g., a CandidateTrade cannot be
    constructed with an empty rationale — this constraint lives in the type itself, not only
    in Plane 3's runtime check, giving defense in depth).

Slice 2 — Historical data ingestion (Plane 1, §5)
    Deliverable: one adapter (a single data source is sufficient for this slice) producing
    validated, normalized, corporate-action-adjusted MarketData records from a real historical
    dataset, with SF-1/SF-2 fault-injection tests passing against synthetic gaps/staleness.

Slice 3 — Feature/context formation + Tier-1 baseline (§5, §12)
    Deliverable: FeatureSnapshot generation, plus the equal-weight buy-and-hold Tier-1 baseline
    running end-to-end (as a CandidateTrade producer) against Slice 2's data.

Slice 4 — Cost Model (§6)
    Deliverable: CostEstimate and ActualCost computation, unit-tested against known worked
    examples of Indian equity cost components, usable standalone before Risk Engine exists.

Slice 5 — Research harness core (§11): walk-forward splitting + ER-1 baseline comparison
    Deliverable: the harness can run Tier-1 baseline through a declared chronological split
    and report cost-adjusted, regime-segmented results — proving Slices 2-4 are trustworthy
    before any "real" strategy is layered on top, per Stage 2's explicit ordering rationale (§19).

Slice 6 — Tier-2 deterministic momentum strategy (§12) + Risk Engine (§7) + Sizing (§8)
    Deliverable: the momentum strategy produces CandidateTrades, which pass through a fully
    built Risk Engine and Sizing module, with adversarial RR-1..9 tests (§15) passing against
    intentionally hostile inputs, and a SimulatedBrokerAdapter (§10) completing the loop.

Slice 7 — Order state machine + reconciliation (§9, §3.4)
    Deliverable: full Order lifecycle against the simulated broker, including a deliberately
    injected ambiguous-response scenario correctly routing to RECONCILIATION_REQUIRED.

Slice 8 — Decision logging + observability core (§4, §18)
    Deliverable: every cycle in Slices 6-7 now produces a complete, queryable DecisionRecord;
    a reconstruction test (§19) passes against a random historical record.

Slice 9 — Research harness completion: contamination checks (ER-3) + PBO/CSCV correction (ER-4)
    + pre-registered criteria (ER-8)
    Deliverable: harness refuses to run a non-compliant evaluation; a synthetic leakage test
    (§15) is caught; a synthetic multi-variant search produces the expected correction.

Slice 10 — Promotion boundary (§14) + Governance/Plane 0 (§16, kill switch, autonomy state)
    Deliverable: the kill-switch adversarial test passes (an attempt from a simulated Plane 2
    or Research process to disable it fails); Tier-2 momentum strategy is formally promoted
    through the PromotionCandidate workflow into a "paper-eligible" StrategyVersion, exercising
    the full boundary for the first time.

Slice 11 — Paper-trading environment (§20)
    Deliverable: the promoted Tier-2 strategy runs end-to-end against live market data with
    simulated execution, autonomy Level 0/1 (per FR-6, demonstrated without rework).

Slice 12 — First AI component (§13)
    Deliverable: the LLM-based confidence-modulation signal, built and run through the Research
    harness against the Tier-2 baseline, with ER-3's contamination check specifically exercised
    for the first time against a real LLM backbone; promoted to paper trading only if it clears
    ER-1 comparison, per its own stated hypothesis (§13) — a negative result here is a valid,
    complete outcome of this slice, not a failure of the slice itself.

Slice 13+ — Broker integration for a real broker (§10), REG-6 ToS review closure, live-execution
    gate work, staging-environment decision (§20's open item), autonomy Level 2 progression —
    sequenced per Stage 1's REG-1/4/5/6/7 gate closures, none of which are technical work and
    all of which can proceed in parallel with Slices 6-12's engineering.
```

**Why this ordering:** it front-loads exactly the components Stage 0 found the field most commonly gets wrong or skips (cost modeling, contamination checking, honest failure-recording) *before* any strategy — deterministic or LLM — is trusted, mirroring Stage 2 §19's stated rationale, and it delays the first LLM component (Slice 12) until the full evaluation and promotion discipline already exists and has been proven against a strategy with zero LLM involvement, so the first real test of "does an LLM help" is run inside a discipline that has already been shaken out on simpler cases.

---

## 22. Technology / dependency decisions

Building on Stage 2 §18's recommendations, now made concrete for the first implementation slices:

| Dependency | What it does | Why needed | Alternatives considered | Why selected | Version/pinning | What would cause replacement |
|---|---|---|---|---|---|---|
| Python 3.x (a specific minor version pinned, e.g., latest stable at build start) | Core language | Per Stage 2 §18 rationale (ecosystem, broker SDK availability) | — (already decided, Stage 2) | — | Pinned exact minor version in a lockfile; upgrades are a deliberate, tested action, not automatic | A hard latency finding Python cannot meet (Stage 2's stated invalidation condition) |
| A data-validation/typed-schema library (e.g., a dataclass/schema-validation approach — specific library left to implementation, since Stage 2 did not mandate one) | Enforces domain-model field constraints (§2) at construction time, not just at plane boundaries | Directly needed for "a CandidateTrade cannot be constructed with an empty rationale" (Slice 1) | Hand-rolled validation functions | A schema library reduces boilerplate and centralizes validation rules, but hand-rolled validation is an acceptable substitute if it adds an unwanted dependency — this is a low-stakes, easily reversible choice | Pinned minor version | Library abandonment/incompatibility — trivially swappable since domain models are pure data structures (§2) |
| A relational database (Postgres-class, per Stage 2 §18) | Stores domain-model records, DecisionRecords, versioned artifacts | FR-4, DR-8, §19's versioning needs are relational/transactional (Stage 2's own rationale, unchanged) | A document store | Transactional integrity across linked records (DecisionRecord's many foreign keys, §4) is a natural fit for relational modeling; a document store would require re-implementing referential integrity manually | Schema-migration-tool-managed versioning | A specific query-latency finding a general relational store cannot serve (Stage 2's stated invalidation condition, unchanged) |
| A time-series-friendly extension or separate store for MarketData (deferred, per Stage 2) | Efficient range queries over historical price/volume | Not required at this project's data volume per Stage 2's assessment | A dedicated time-series database | Deferred — general relational storage is adequate at current scale | N/A yet | Demonstrated query-latency problems at the general store, revisited without re-architecting the rest |
| A CI system with an import-graph/dependency-direction check (§1) | Enforces plane isolation at build time | This is a new, Stage-3-specific requirement (no Stage 2 equivalent) — needed to make the isolation guarantees in §7, §14, §17, §20 checkable facts rather than only code-review conventions | Manual code review alone | Manual review is necessary but insufficient — it does not scale and can miss a violation; an automated check is cheap to add and directly implements RR-9/§16's "no silent conversion" guarantee at the infrastructure level | Standard CI versioning | Not applicable — this is foundational tooling |
| `SimulatedBrokerAdapter` (in-house, §10) | First broker-adapter implementation, enabling Slices 6-11 without a live broker relationship | REG-6 (ToS review) is not yet closed; building against a simulated adapter lets engineering proceed in parallel with regulatory-gate closure (Stage 1 §12.6) | Waiting for a real broker before building Plane 3 | Blocking all of Plane 3's construction on REG-6 would be a needless serialization of independent workstreams | Its own internal versioning, same as any other adapter | A production broker's adapter becoming available (REG-6 closed) — does not replace the simulated adapter, which remains useful for Research/paper environments (§20) indefinitely |
| Broker SDK for a specific broker | Real order placement/query | Only needed once REG-6 closes and a broker is selected | N/A — genuinely deferred, no candidate evaluated yet | — | — | — |
| LLM API access (for §13's component, when built) | Inference for the confidence-modulation signal | Only needed at Slice 12 | Self-hosted model vs. hosted API — not yet evaluated, since Slice 12 is not imminent in the build sequence | Deferred | Pinned ModelVersion per §19 | A specific latency/cost/contamination-tracking finding at Slice 12 time |

**Dependency-sprawl discipline:** no dependency above is adopted for a capability not required by a named slice in §21; several rows above are explicitly "deferred, not chosen," consistent with Stage 2 Principle 1 carried into Stage 3.

---

## 23. Requirements traceability (Requirement → Architecture → Technical Component → Test)

This extends Stage 2 §22's plane-level traceability down to the module and test level. Full detail for every one of Stage 1's 72 requirements is maintained in a living traceability table (recommended as a structured artifact in the Research/observability store itself, per DOC-1 through DOC-5's discipline, once tooling exists — summarized here by group):

| Requirement group | Architecture (Stage 2) | Technical component (Stage 3) | Test category (§15) |
|---|---|---|---|
| FR-1–FR-8 | Planes 1-4 | `data/`, `intelligence/interface/`, `observability/decision_log/`, DecisionRecord schema (§4) | Integration, contract |
| TR-1–TR-7 | Plane 0 + Plane 3 | `governance/config/` (universe, TR-1/TR-7), `risk_execution/cost_model/` (TR-2), `risk_execution/sizing/` (TR-3), Tier-2 baseline's HOLD handling (TR-4), `risk_execution/cost_model/` intraday-vs-delivery parameterization (TR-5), `intelligence/interface/` decoupling from `data/adapters/` (TR-6) | Unit, integration, contract |
| AR-1–AR-5 | Plane 0 + Plane 3 autonomy gate | `governance/autonomy/`, AutonomyLevel object (§2) | Contract, deployment-gate |
| RR-1–RR-9 | Plane 3, isolated | `risk_execution/risk_engine/` (§7), import-graph lint (§1, §22) for RR-9 specifically | Adversarial (§15), one test per RR-x |
| SF-1–SF-10 | §13 of Stage 2 | `data/validation/` (SF-1/2), `risk_execution/` schema validators (SF-3), adapter fail-safe defaults (SF-4/5/6), abnormal-market detector (SF-7), sizing sanity checks (SF-8), Plane 2-internal resolution rule (SF-9, deferred until multi-component Plane 2 exists), mandatory confidence field (SF-10) | Fault-injection (§15), one test per SF-x |
| PR-1–PR-9 | Plane 4 / Research harness | `research/harness/`, `observability/reporting/` | Backtest-validation, paper-trading tests; thresholds remain operator/TBD per Stage 1 |
| DR-1–DR-8 | Plane 1 | `data/adapters/`, `data/normalization/`, DecisionRecord's data_sources field | Integration |
| ER-1–ER-8 | Research & Backtesting environment | `research/harness/`, `research/contamination/`, `research/stats/`, `research/experiments/` | Backtest-validation |
| REG-1–REG-8 | Execution gate, Plane 0 config, DR-6 | `governance/config/` gate flags (§20), `risk_execution/broker/` REG-3 controls, `risk_execution/risk_engine/` RR-5 order-rate ceiling (REG-4) | Deployment-gate |
| DOC-1–DOC-7 | §15 versioning discipline | `shared/versioning/`, this document series itself | N/A (process, not code) |

**No orphan requirements:** every requirement group above has at least one named module and one named test category; §15 additionally lists SF-x/RR-x at the individual-ID level, satisfying the prompt's explicit "no orphan requirements" instruction at that granularity for the two groups it specifically called out.

---

## 24. ADRs — new Stage 3 decisions

### ADR-6: Import-graph / dependency-direction enforcement as a build-time check

- **Problem:** Stage 2's plane-isolation guarantees (RR-9, §11, §16, §20) are stated architecturally, but nothing in Stage 2 specifies how they remain true as the codebase grows and multiple people/sessions touch it over time.
- **Context:** a codebase without an enforced boundary tends to accumulate convenience imports across intended boundaries, especially under time pressure, and the consequence here (a self-improvement artifact gaining a path to risk rules) is exactly the failure mode Stage 0/1/2 spent the most effort guarding against.
- **Options:** (a) rely on code review alone; (b) a documented convention with no tooling; (c) an automated CI check that fails the build on a disallowed import.
- **Decision:** (c) — implement an automated dependency-direction check (§1, §22) as part of the CI pipeline from Slice 0 onward.
- **Trade-offs:** small upfront tooling cost; some friction if a genuinely legitimate cross-plane need arises later (mitigated by requiring an explicit, reviewed exception mechanism rather than simply disabling the check).
- **Consequences:** RR-9, §11's isolation, and §17's security boundaries become checkable facts in CI, not just design intentions.
- **What would invalidate it:** none identified — this strictly strengthens an already-decided architectural guarantee at negligible cost.

### ADR-7: Two-tier baseline (naive static + deterministic momentum) rather than a single baseline strategy

- **Problem:** Stage 2 left "the exact Plane 2 v1 deterministic baseline strategy design" as an open question (§21, item 1).
- **Context:** ER-1 explicitly requires comparison against *both* a naive static baseline and a well-tuned classical/deterministic strategy — these are two different roles, and Stage 0's strongest cross-cutting finding (02 §8) is that baseline rigor is the single biggest determinant of whether a later result can be trusted.
- **Options:** single baseline serving both roles; two separate, purpose-built baselines (chosen).
- **Decision:** adopt both a Tier-1 (naive equal-weight buy-and-hold) and Tier-2 (12-1 month momentum) baseline, per §12.
- **Trade-offs:** marginally more to build and maintain than a single baseline; directly avoids conflating "beats doing nothing" with "beats a genuinely competent simple strategy," which Stage 0 found is exactly where the field's evidence most often overstates itself.
- **Consequences:** every future Plane 2 candidate is held to the stronger of the two bars, not the weaker one, by construction.
- **What would invalidate it:** none identified within current evidence; a future finding that momentum specifically is inappropriate for the eventual permitted universe (e.g., if the universe ends up dominated by illiquid names where momentum literature doesn't clearly apply) would prompt reconsidering Tier 2's specific factor choice, not the two-tier structure itself.

### ADR-8: `SimulatedBrokerAdapter` as the first broker-adapter implementation

- **Problem:** REG-6 (broker ToS AI-restriction review) is an open gate, and Plane 3/Slice 6-11 engineering should not be blocked on its closure.
- **Decision:** build a fully-featured simulated adapter implementing the exact broker-neutral interface (§10) as the first concrete implementation, used throughout Research, paper trading, and development.
- **Trade-offs:** the simulated adapter's fill/latency model is necessarily an approximation of real broker behavior; this is an accepted, explicit limitation of paper-trading results until a real broker is integrated (Slice 13+), not a hidden one.
- **Consequences:** the entire Plane 1-4 pipeline, Risk Engine, and promotion boundary can be built, tested, and exercised end-to-end well before any broker/regulatory gate closes.
- **What would invalidate it:** none — this is additive; the simulated adapter is retained even after a real broker is integrated, since Research and pure paper-trading dry-runs continue to need it.

---

## 25. Build readiness gate

## ARE WE READY TO CODE?

**Yes.**

**Why:** every plane from Stage 2 now has a concrete module structure (§1), every cross-plane interface has a defined schema with explicit inclusion/exclusion rules (§3), every domain object needed for the first several implementation slices is specified (§2), the two components Stage 2 left open (baseline strategy design, §12; first AI component design, §13) are now resolved with explicit rationale, every Stage 1 SF-x and RR-x requirement has a named test (§15, §23), and the promotion/isolation boundaries that the entire project's risk posture depends on (§14, §17, §20) are specified as buildable, checkable mechanisms (import-graph enforcement, credential isolation, network-topology isolation) rather than as prose intentions. The remaining open items (§21's Slice 13+ dependencies: broker selection, REG-6 closure, numeric threshold values, staging-environment decision) are correctly external to engineering readiness — they are regulatory/operator decisions that can proceed in parallel with Slices 0-12, exactly as Stage 2 §23 anticipated.

### FIRST IMPLEMENTATION MILESTONE

**Milestone: Slice 0 + Slice 1 — Repository scaffolding with enforced plane isolation, and a fully tested core domain model.**

**Scope:**
- Repository structure per §1, with the import-graph/dependency-direction CI check (ADR-6) live and enforcing the plane-isolation rules from day one (a deliberately provocative test — e.g., a stub module in `research/` attempting to import from `risk_execution/broker/` — is included specifically to prove the check works, not just that it exists).
- Every domain object in §2 implemented as a typed, immutable-where-specified data structure, each with unit tests confirming: required fields cannot be omitted (e.g., CandidateTrade.rationale, confidence), immutability is enforced where specified, and version-reference fields are present and correctly typed.
- No plane logic, no data ingestion, no broker adapter, no strategy logic yet — this milestone is deliberately narrow, per the prompt's instruction that the first implementation should not attempt the entire system.

**Why this is the right first milestone:** every other slice in §21 depends on both the isolation guarantee (so later slices are built inside the correct boundaries from the start, not retrofitted) and the domain model (so every subsequent component speaks the same, already-agreed data language). Getting these two things right and tested first is the lowest-risk, highest-leverage starting point, and is small enough to be fully completed and verified independently before Slice 2 begins.

---

## 26. Notion / project log

Per the established discipline in prior sessions, this transition is recorded here pending confirmed Notion write access:

> **Stage 2 COMPLETE → Stage 3 STARTED → Stage 3 (Detailed Technical Design v0.1) COMPLETE — READY FOR IMPLEMENTATION (dated this session).** Full technical design produced across 25 sections: repository structure, domain model, plane interfaces (including the canonical CandidateTrade contract), decision schema, data pipeline, Cost Model, Risk Engine, sizing, order state machine, broker abstraction, Research/backtesting engine, baseline strategy selection (two-tier: naive buy-and-hold + 12-1 month momentum), first AI component design (bounded confidence-modulation signal, explicit falsifiable hypothesis), self-improvement promotion boundary, testing design, configuration, security, observability, versioning, environment design, a 13-slice implementation sequence, technology/dependency decisions, full requirements traceability, three new ADRs (import-graph enforcement, two-tier baseline, simulated-broker-first), and a build-readiness gate concluding YES with a defined first milestone (repository scaffolding + core domain model). No Stage 0/1/2 content was reopened or altered. Next: begin implementation per §21's slice sequence, in parallel with REG-6/REG-7 regulatory-gate closure work.

As with prior sessions, Notion write access has previously failed with a "No approval received" error of unconfirmed resolution status. I have **not** assumed success and have not fabricated a write. If you'd like me to attempt the write now, I will and will report the exact result.

---

*This document specifies how to build the system defined by Stage 1 (Requirements) within the architecture defined by Stage 2. It does not write implementation code. Implementation begins with the milestone defined in §25.*
