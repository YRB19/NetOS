# STAGE 1 — REQUIREMENTS BASELINE v0.2
**AI Trading Agent Research & Engineering Project**
Status: **APPROVED FOR ARCHITECTURE** · Stage 1 (Requirements) · CLOSED
Supersedes: v0.1 (content preserved below, not deleted — see Changelog). Stage 0 findings preserved as historical record, not overwritten.

---

## Changelog from v0.1

Per DOC-6 (versioned revisions, not silent in-place edits), the following is the complete record of what changed between v0.1 and v0.2:

- Added this Changelog section.
- Added the **Sign-off Record** (below), verifying the 11 closure criteria against the existing baseline.
- No requirement IDs were added, removed, renumbered, or had their substance changed.
- No numeric thresholds were invented. All items marked TBD in v0.1 remain TBD in v0.2.
- No technology, broker, model, or architecture was selected in this document — those decisions begin in Stage 2 (companion document, 04-Stage2-System-Architecture-v0.1.md).
- Header and status line updated to reflect closure.

Everything else below is carried forward from v0.1 unchanged, since the closeout instruction was explicit: *"Make only the minimum changes necessary… Do not endlessly optimize wording."*

---

## Sign-off Record

Verifying the 11 requirements sign-off criteria against the baseline as it stands:

| # | Criterion | Status | Where satisfied |
|---|---|---|---|
| 1 | System's ultimate objective is unambiguous | ✔ Met | §0 System summary |
| 2 | Functional requirements defined | ✔ Met | §1 (FR-1–FR-8) |
| 3 | Trading requirements defined | ✔ Met | §2 (TR-1–TR-7) |
| 4 | Autonomy requirements defined | ✔ Met | §3 (AR-1–AR-5) |
| 5 | Risk limits defined conceptually | ✔ Met | §4 (RR-1–RR-9) — thresholds correctly left as operator inputs, not invented |
| 6 | Failure/safety behavior defined conceptually | ✔ Met | §5 (SF-1–SF-10) |
| 7 | Performance measured net of real-world costs | ✔ Met | §6 (PR-6, PR-9), reinforced by TR-2, ER-5 |
| 8 | Evaluation prevents leakage, temporal contamination, multiple-testing bias | ✔ Met | §8 (ER-2, ER-3, ER-4) |
| 9 | Regulatory constraints/gates explicitly identified | ✔ Met | §9 (REG-1–REG-8), all gates marked |
| 10 | Documentation/provenance requirements defined | ✔ Met | §10 (DOC-1–DOC-7) |
| 11 | Genuinely architectural/empirical items remain TBD, not invented | ✔ Met | §12.2, §12.3 — thresholds, evaluation-period length, provider/framework choices all explicitly deferred |

**All 11 criteria are satisfied. STAGE 1 = COMPLETE.**

This is a judgment that the baseline is *stable enough to design against*, not that every requirement is final — DOC-6 remains in force, and any requirement here may still be revised in a future v0.3+ if Architecture or empirical work surfaces a genuine conflict. Revision is not a sign Stage 1 "failed"; re-opening Stage 0-style broad research without a specific blocking factual issue is what would be out of process, per the closeout instruction.

---

## 0. System summary (what we are trying to build)

A system that, by its final form, autonomously manages a personal Indian-equities trading account: it ingests market and contextual data, forms views, decides what to buy/sell/hold and in what size, executes those decisions through a broker, monitors its own positions and behavior, and is expected to do all of this without per-trade human approval — while remaining profitable after real-world costs over a meaningful evaluation horizon, and while never taking actions that fall outside limits set by its human operator.

Full autonomy is the end state, not the starting state. The system is expected to pass through supervised and delegated stages (Requirement AR-1) before reaching that end state, and through paper trading before touching real capital (Requirement SF-gate items below). Whether it uses one LLM, many agents, classical quantitative methods, self-improving mechanisms, or some combination of these is explicitly **not decided by this document** — Stage 0 found weak, mixed, or absent evidence for several of these choices (multi-agent vs. single-agent, self-improvement vs. static), and Requirements intentionally does not pre-select an answer Stage 0 couldn't support.

The rest of this document defines what the system must do, tolerate, and never do — not how. (Stage 2 now begins answering "how" — see the companion Architecture document.)

---

## 1. Functional requirements

| ID | Requirement | Rationale | Priority | Verification method | Dependencies | Source |
|---|---|---|---|---|---|---|
| FR-1 | The system must be able to ingest current and historical Indian-equity market data (price, volume, and any other category defined in §7) sufficient to form a trading decision. | Baseline capability; nothing else is possible without it. | Must | Demonstration against a live/replayed data feed | DR-1 | Derived from North-star objective (00, §L) |
| FR-2 | The system must be able to produce a discrete trading decision (buy/sell/hold, including sizing) for a given instrument at a given point in time. | Core purpose of the system. | Must | Unit-level decision test against known inputs | FR-1 | 00 §L |
| FR-3 | The system must be able to submit, modify, and cancel orders through a broker-provided interface. | Decisions are worthless without execution. | Must | Integration test against broker sandbox/paper environment | FR-2 | 00 §M |
| FR-4 | The system must be able to track its own current positions, cash balance, and realized/unrealized P&L at all times. | Required for both decision-making and risk enforcement. | Must | Reconciliation test against broker-reported state | FR-3 | — |
| FR-5 | The system must be able to record, for every decision it makes (including "hold"), the inputs it considered and the reasoning/basis for the decision. | Needed for auditability, debugging, evaluation, and regulatory defensibility (00 §D.5). | Must | Log/audit-trail inspection | FR-2 | 00 §D.5, §J |
| FR-6 | The system must be able to operate at each of the autonomy levels defined in AR-1 without architectural rework between levels. | Staged validation (00 §L Q5) requires moving through levels; rebuilding at each transition defeats the purpose of staging. | Must | Demonstrated operation at Level 0 and Level 1 using the same core decision logic | AR-1 | 00 §P |
| FR-7 | The system must expose its current state (positions, pending decisions, recent reasoning, active risk limits) to a human operator on demand. | Human oversight is required at every autonomy level below full autonomy, and even at full autonomy per RR-8. | Must | Manual inspection / operator interface test | FR-4, FR-5 | 00 §P |
| FR-8 | The system must be able to distinguish, in its own outputs and logs, between "improved because of genuine adaptation" and "changed because of self-modification" if any self-improvement mechanism is later adopted. | Stage 0 found these are empirically dissociable, not synonymous (01 §2, "Harness Updating Is Not Harness Benefit"). | Should | Log inspection once/if a self-improvement mechanism exists | Architecture decision (not yet made) | 01 §2, §7 |

---

## 2. Trading requirements

| ID | Requirement | Rationale | Priority | Verification method | Dependencies | Source |
|---|---|---|---|---|---|---|
| TR-1 | The system must define, for itself, what universe of instruments it is permitted to trade at any given time, and this universe must be explicitly configurable by the operator. | Prevents silent scope creep into instruments the operator hasn't reviewed (e.g., illiquid, F&O, non-equity). | Must | Configuration audit | — | 00 §L Q2 |
| TR-2 | The system must incorporate, in its decision process, an estimate of transaction costs, taxes, and slippage before deciding to act. | Stage 0 found this is the single most commonly *missing* element in the literature (01 §7, "only 1/19 studies model transaction costs") and directly determines whether "profitable" survives contact with reality. | Must | Decision trace shows a cost estimate influencing size/action | DR-4 | 01 §7, 02 §9 |
| TR-3 | The system must be able to size a position according to an explicit, inspectable rule (not an opaque single-shot LLM output with no constraint applied after it). | Risk requirements (§4) cannot be enforced against a black-box size decision. | Must | Trace shows a bounding rule applied to any proposed size | RR-1, RR-2 | Derived from RR-1/RR-2 |
| TR-4 | The system must be able to hold a position, including holding cash/no position, as a first-class decision — not merely a default fallback when nothing else fires. | Stage 0 (FINSABER, 02 §4.1) found LLM strategies are miscalibrated in both directions (too passive in bull markets, too aggressive in bear); an explicit "hold is a decision" requirement is a partial structural mitigation. | Must | Decision log shows hold decisions with recorded reasoning, not silent no-ops | FR-2, FR-5 | 02 §4.1, §10 |
| TR-5 | The system must distinguish intraday from delivery/positional trades in its decision and risk logic, since regulatory, tax, and margin treatment differ. | 00 §M.4 flags business-income-vs-capital-gains tax classification and margin/leverage rules as open, materially relevant items. | Must | Configuration/logic review | REG-2 | 00 §M.4 |
| TR-6 | The system's decision logic must be evaluable independent of any specific data provider or broker, i.e., the trading logic and the integration layer must be separable. | Stage 2 (Architecture) will select providers/brokers; Requirements must not implicitly lock these in via how trading logic is specified. | Must | Design review at Architecture handoff | — | Waterfall rule |
| TR-7 | The system must have a defined process for adding or removing an instrument from its tradable universe that includes a review step, not an automatic/unattended expansion. | Prevents an autonomous system from silently trading instruments never evaluated by the operator. | Must | Process walkthrough / configuration test | TR-1 | Derived |

---

## 3. Autonomy requirements

| ID | Requirement | Rationale | Priority | Verification method | Dependencies | Source |
|---|---|---|---|---|---|---|
| AR-1 | The system must implement, at minimum, the four autonomy levels identified in Stage 0's grounded taxonomy: Level 0 (Advisory — recommends only), Level 1 (Supervised — executes pre-approved transaction types within strict limits, human approves exceptions), Level 2 (Delegated — executes broadly within policy, human reviews periodically), Level 3 (Fully Autonomous — no per-transaction oversight, human sets only high-level goals/constraints). | This is the project's own adopted vocabulary (00 §P), grounded in a citable finance-specific source (SoK: Security of Autonomous LLM Agents, arXiv 2604.15367) rather than an invented scale. | Must | Demonstrated operation at each level in sequence | FR-6 | 00 §P |
| AR-2 | Progression from one autonomy level to the next must require an explicit, documented operator decision — the system must never self-promote its own autonomy level. | Directly addresses 00 §L Q5's concern that human-loop stages must not "quietly become the permanent destination," but equally must not be silently skipped in the other direction. | Must | Configuration/permission test — system cannot alter its own autonomy-level setting | — | 00 §L Q1, Q5 |
| AR-3 | At every autonomy level, the operator must be able to unilaterally revoke the system's trading authority (a "kill switch") with immediate effect, without needing the system's cooperation or acknowledgment. | Basic operator control; consistent with the field's own stated (if under-implemented) prescription for kill-switch logic (01 §12). | Must | Kill-switch test — verify orders stop and no new orders are placed after activation | SF-9 | 01 §12 |
| AR-4 | "Fully autonomous" (Level 3) must still operate within operator-set high-level constraints (e.g., maximum capital at risk, maximum drawdown, permitted instrument universe) that the system cannot alter itself. | Full autonomy as defined in the SoK taxonomy is bounded autonomy, not unconstrained autonomy; this matches the project's own stated target (00 §L Q1/Q5). | Must | Configuration test — constraint values are operator-writable, system-read-only | RR-1 through RR-7 | 00 §L Q1, §P |
| AR-5 | The system must log which autonomy level it was operating under for every decision made. | Needed for post-hoc evaluation and for distinguishing performance attributable to different autonomy levels during staged validation. | Must | Log inspection | FR-5, AR-1 | Derived |

---

## 4. Risk requirements — what the system must never be allowed to do

| ID | Requirement | Rationale | Priority | Verification method | Dependencies | Source |
|---|---|---|---|---|---|---|
| RR-1 | The system must never place a position (single or aggregate) that exceeds an operator-defined maximum exposure limit, expressed as a percentage of total capital. | Baseline capital-preservation control. | Must | Automated limit-enforcement test with adversarial/edge-case sizing attempts | AR-4 | Derived |
| RR-2 | The system must never exceed an operator-defined maximum leverage/margin utilization threshold. | Directly relevant given 00 §M.4's flag that margin/leverage rules interact with autonomous risk control and are not yet researched in depth. | Must | Limit-enforcement test | REG-3 | 00 §M.4 |
| RR-3 | The system must never breach an operator-defined maximum drawdown threshold without halting new position-opening activity. | Standard capital-preservation control; matches the field's own (under-implemented) stated prescription (01 §12). | Must | Simulated drawdown-breach test | SF-9 | 01 §12 |
| RR-4 | The system must never trade an instrument outside its currently-configured permitted universe (TR-1). | Prevents scope creep into unreviewed/illiquid/unsuitable instruments. | Must | Attempted out-of-universe order rejected in test | TR-1 | Derived |
| RR-5 | The system must never exceed any exchange-mandated order-rate threshold that would trigger a regulatory reclassification (e.g., the ~10 orders/second threshold flagged in 00 §M.3, pending final confirmation). | Crossing this threshold changes the system's regulatory category (00 §M.2) with compliance consequences not yet fully mapped. | Must | Rate-limiting test | REG-1 | 00 §M.2, §M.3 |
| RR-6 | The system must never execute a trade for any party other than the operator (and, if applicable, immediate family as defined by the "tech-savvy retail investor" category) without a separate, explicit regulatory review. | The "tech-savvy retail investor" exemption from Algo Provider/RA-licensing obligations (00 §M.2) is conditioned on personal/immediate-family use only; trading for others would likely change the system's regulatory category entirely. | Must | Configuration/scope review | REG-1 | 00 §M.2 |
| RR-7 | The system must never take an action based on a data source or signal it cannot attribute and log (no untraceable/black-box-only justification for a live trade). | Directly supports auditability (FR-5) and defends against the "black box" regulatory characterization risk noted in 00 §M.2. | Must | Audit-trail review — every executed trade has a logged, attributable rationale | FR-5 | 00 §M.2 |
| RR-8 | The system must never remove or bypass the operator's kill-switch/override capability (AR-3), regardless of autonomy level or any self-improvement mechanism later adopted. | This is the one control that must survive any future architectural or self-modification decision. | Must | Adversarial test — attempt to have the system disable its own override path; must fail | AR-3 | 01 §12 |
| RR-9 | If a self-improvement mechanism is ever adopted, the system must never allow that mechanism to modify RR-1 through RR-8 or any operator-set constraint in AR-4. | Stage 0 found self-modification and capability expansion are exactly the mechanism through which risk controls could otherwise be quietly eroded (01 §12, "Statistical Limits of Self-Improving Agents" capacity-bounding argument). | Must | Design review at Architecture stage (this requirement constrains any future self-improvement design, it does not require one to exist) | AR-4, RR-1–RR-8 | 01 §5, §7, §12 |

---

## 5. Safety / failure requirements

The system must have a defined, non-default behavior for each of the following conditions. "Non-default" means the behavior must be an explicit design decision, not whatever happens to occur when nothing is specified.

| ID | Condition | Required behavior (minimum bar) | Priority | Verification method | Source |
|---|---|---|---|---|---|
| SF-1 | Market data is missing | System must not act on an instrument for which required data is missing; must log the gap and either hold or fall back to a defined degraded mode. | Must | Fault-injection test (withhold a data field) | Derived from 00 §D.5, §J |
| SF-2 | Market data is stale | System must detect staleness against a defined freshness threshold and treat stale data as missing (SF-1) rather than as current. | Must | Fault-injection test (delay a feed) | Derived |
| SF-3 | The model/decision component fails or returns malformed/nonsensical output | System must reject the malformed output, not act on it, and fall back to hold/no-action; failure must be logged and surfaced to the operator. | Must | Fault-injection test (malformed model output) | 01 §12 (reward-hacking/Goodhart concern generalizes to malformed-output risk) |
| SF-4 | An external API (data, broker, or otherwise) fails or times out | System must fail safe (no action, not "guess and proceed") and retry/alert per a defined policy. | Must | Fault-injection test (API failure/timeout) | Derived |
| SF-5 | The broker itself fails or is unreachable | System must halt new order placement; must not assume orders succeeded without confirmation. | Must | Simulated broker outage test | Derived |
| SF-6 | Connectivity disappears entirely | System must default to a safe state (no new positions; existing positions and their own broker-side risk controls, if any, remain the operator's separate concern to define at Architecture). | Must | Connectivity-loss test | Derived |
| SF-7 | The market behaves abnormally (e.g., circuit breaker, extreme volatility, halt) | System must have a defined abnormal-market detection trigger that suspends normal decision logic and reverts to a conservative/no-new-position mode. | Must | Simulated abnormal-market scenario test | Derived, informed by 02 §4.1 (regime-miscalibration finding) |
| SF-8 | The system produces an obviously bad decision (by some operator-defined sanity check) | A pre-execution sanity/plausibility check must exist and must be able to block execution independent of the primary decision logic. | Must | Adversarial test — inject a decision designed to fail the sanity check | RR-1–RR-7 |
| SF-9 | Internal components disagree (e.g., in a multi-component design) | System must have a defined resolution rule (e.g., default to the more conservative action) rather than an undefined/random tie-break. | Must | Design review; test once Architecture defines component structure | Derived, informed by 02 §2 (mechanism heterogeneity) |
| SF-10 | The system becomes "uncertain" (however uncertainty is eventually operationalized) | System must have a defined lower-confidence fallback (e.g., smaller size, hold, or escalate to human) rather than treating uncertain and confident decisions identically. | Must | Design review; test once Architecture defines a confidence signal | Derived |

**Deployment-gate note:** Requirements SF-1 through SF-10 and RR-1 through RR-9 must all be demonstrated as working in a paper-trading environment before any transition to live capital, per the Waterfall stage sequence (paper trading precedes Live Deployment Gate). This is recorded as a gate, not re-derived here (see §"Deployment gates" below).

---

## 6. Performance requirements

Per instruction, no arbitrary numeric thresholds are invented here. Each item below defines *what must be measured*, not the passing value, unless a value is already fixed by an external constraint (e.g., a regulatory threshold, which belongs in §9).

| ID | Requirement | Threshold status | Priority | Verification method | Source |
|---|---|---|---|---|---|
| PR-1 | Decision quality must be measurable against at least one baseline defined in ER-1 (see §8). | TBD — requires validation (which baseline(s), and what "beats" means, deferred to Evaluation design) | Must | Backtesting/evaluation harness | 02 §9 |
| PR-2 | Execution quality (fill rate, realized vs. intended price) must be measured for every order once live/paper trading begins. | TBD — requires validation (acceptable slippage bounds) | Must | Trade-log analysis | TR-2 |
| PR-3 | Decision and execution latency must be measured, with a defined maximum acceptable latency appropriate to the trading style eventually chosen (intraday vs. delivery). | TBD — requires validation; likely depends on TR-5's intraday/delivery distinction | Should | Latency logging/profiling | TR-5 |
| PR-4 | System reliability (uptime, successful decision-cycle completion rate) must be measured continuously once operating at any autonomy level above Level 0. | TBD — requires validation (acceptable downtime) | Must | Uptime/monitoring logs | AR-1 |
| PR-5 | Maximum realized drawdown must be measured and compared against the operator-set limit in RR-3. | Threshold set by operator per RR-3, not invented here | Must | P&L/drawdown tracking | RR-3 |
| PR-6 | Transaction costs and taxes actually incurred must be measured and reconciled against the estimates used in TR-2's decision process. | No threshold; this is a measurement/reconciliation requirement | Must | Cost reconciliation report | TR-2 |
| PR-7 | Slippage (difference between decision-time price and executed price) must be measured per trade. | TBD — requires validation (acceptable bounds) | Should | Trade-log analysis | PR-2 |
| PR-8 | Robustness must be measured as performance consistency across at least the range of market regimes the evaluation design (ER-2) specifies, not a single favorable window. | TBD — requires validation; directly informed by FINSABER's finding (02 §4.1) that short/narrow evaluation windows overstate performance | Must | Multi-regime backtest/evaluation | 02 §4.1, §9 |
| PR-9 | "Profitability" for the purpose of the project's success definition (00 §L Q3) must be evaluated net of transaction costs, taxes, and slippage, over an evaluation period long enough to include more than one market regime. | Exact period length TBD — requires validation; exact profitability threshold explicitly deferred per 00 §L Q3 | Must | Evaluation-harness design + backtest/paper-trade results | 00 §L Q3, 02 §9 |

---

## 7. Data requirements

Categories only — no provider selection.

| ID | Category | Rationale | Priority | Source |
|---|---|---|---|---|
| DR-1 | Real-time and historical price/volume data for the permitted instrument universe (TR-1). | Baseline requirement for any decision (FR-1). | Must | Derived |
| DR-2 | Corporate-action data (splits, dividends, bonuses, delistings) sufficient to avoid decision or backtest errors from unadjusted series. | Backtest/evaluation integrity; survivorship-handling was flagged in Stage 0 as commonly missing field-wide (01 §7). | Must | 01 §7 |
| DR-3 | Fundamental/company data, to the extent the eventual strategy design uses it (not yet decided — Architecture question). | Contingent requirement; recorded now so Architecture isn't blocked discovering it later. | Should | Derived |
| DR-4 | Transaction-cost and fee-schedule data (brokerage, STT, exchange charges, GST, stamp duty) specific to Indian equities, current as of whatever period is being evaluated. | Directly required by TR-2 and PR-6/PR-9; Stage 0 flagged Indian-specific tax/cost treatment as an open research item (00 §M.4). | Must | 00 §M.4 |
| DR-5 | Order-book/market-microstructure data sufficient to estimate slippage and market impact, at least at the level of detail needed for PR-7. | Required for realistic cost/slippage estimation, which Stage 0 found is the most commonly *omitted* element field-wide (01 §7). | Should | 01 §7 |
| DR-6 | Regulatory/circular update data (SEBI, exchange), at minimum enough to detect when a rule the system depends on (e.g., the order-rate threshold in RR-5) has changed. | The regulatory framework itself changed twice during Stage 0's own research window (00 §M.1); a static assumption about current rules is not safe long-term. | Must | 00 §M.1 |
| DR-7 | News/sentiment/alternative data, to the extent the eventual strategy design uses it (not yet decided — Architecture question). | Contingent requirement, same reasoning as DR-3. | Could | Derived |
| DR-8 | A record of the system's own historical decisions and their outcomes (distinct from market data) — i.e., the system's own decision log (FR-5) treated as a first-class data source for its own evaluation. | Needed for PR-1/PR-2/PR-6/PR-8 and for any future self-improvement evaluation (RR-9). | Must | FR-5 |

---

## 8. Evaluation requirements

| ID | Requirement | Rationale | Priority | Verification method | Source |
|---|---|---|---|---|---|
| ER-1 | The evaluation framework must compare the system against, at minimum: (a) a naive static baseline (e.g., buy-and-hold or an equally-weighted approach, per DeMiguel et al.'s standard), (b) a well-tuned classical/deterministic strategy, and (c) the system's own prior version, once one exists. | Stage 0's single strongest cross-cutting finding is that the apparent case for adaptation/sophistication is inversely related to the rigor of the baseline tested against it (02 §8). A weak-baseline evaluation would silently reproduce the exact failure mode Stage 0 spent two sessions documenting. | Must | Evaluation-harness design review | 02 §3.1, §8, §9 |
| ER-2 | The evaluation framework must use chronologically disciplined, genuinely held-out data (walk-forward or an equivalent train/validation/test split with no leakage), not a single convenient window. | Stage 0 found only 2 of 19 field-wide studies report an extractable, time-consistent split (01 §7); this project's own evaluation must not repeat that gap. | Must | Split-protocol audit before any backtest is trusted | 01 §7, §8 |
| ER-3 | The evaluation framework must explicitly check for and control temporal/knowledge-cutoff contamination (any model used must not be evaluated on periods overlapping data it could have memorized). | Directly addresses "Profit Mirage," "The Alpha Illusion," and KTD-Fin (01 §7) — a documented, LLM-specific failure mode distinct from classical overfitting. | Must | Contamination-check procedure (e.g., leakage-robust benchmarking, per FactFin/FinLake-Bench as a candidate methodology) applied before trusting any result | 01 §7 |
| ER-4 | The evaluation framework must apply a correction for the number of strategy/parameter variants tried (a PBO/CSCV-style or equivalent multiple-testing correction) before any backtest result is treated as evidence of genuine skill. | Classical overfitting-detection tooling exists and predates LLMs but is absent from nearly all LLM-trading literature reviewed in Stage 0 (01 §7); this project should not repeat that omission. | Must | Statistical-correction procedure applied and documented per evaluated candidate | 01 §7 |
| ER-5 | The evaluation framework must include realistic transaction-cost, tax, and slippage modeling (TR-2, DR-4, DR-5) in every reported result — no "gross" performance numbers presented as if they were net. | Same rationale as TR-2; explicitly named as commonly missing field-wide (01 §7). | Must | Report-format review — every performance figure is cost-adjusted or explicitly labeled otherwise | 01 §7, TR-2 |
| ER-6 | The evaluation framework must separately report performance by market regime (at minimum: rising, falling, and range-bound/volatile), not only as an aggregate figure. | FINSABER's finding that LLM strategies fail in opposite, regime-specific ways (too passive in bull, too aggressive in bear) would be invisible in an aggregate-only report (02 §4.1). | Must | Regime-segmented reporting | 02 §4.1 |
| ER-7 | If a self-improvement mechanism is adopted, the evaluation framework must separately report (a) performance attributable to initial strategy discovery and (b) performance attributable to ongoing post-deployment adaptation, rather than a single combined figure. | Stage 0 found conflating these two claims is "the single most common source of overstated 'self-improvement works' claims in the literature" (02 §9, item 8). | Should (Must, if self-improvement is adopted) | Evaluation-report structure review | 02 §2, §9, §11 |
| ER-8 | The evaluation framework must define, in advance of running any evaluation, what would count as a negative/disqualifying result — not only what would count as success. | Stage 0's own methodology (actively seeking negative results rather than filtering them, 02 §10) should carry forward into how this project evaluates its own system, not just how it evaluated the literature. | Should | Pre-registered evaluation criteria document | 02 §10 |

---

## 9. Regulatory / operational requirements

These capture Stage 0 constraints as requirements. No new regulatory research is performed here; open items are marked as gates/TBD per instruction.

| ID | Requirement | Status | Priority | Source |
|---|---|---|---|---|
| REG-1 | The system must operate within the "tech-savvy retail investor" category (self-built, self-hosted, personal/immediate-family use, self-borne P&L) as currently understood, unless and until a formal legal reading confirms otherwise. | Working interpretation only, not a ruling (00 §M.2) — **GATE**: requires legal/compliance confirmation before live deployment. | Must | 00 §M.2 |
| REG-2 | The system must comply with SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 and its amendments as currently in force. | Confirmed live as of the framework's stated effective date (00 §M.1); **TBD**: ongoing monitoring requirement (DR-6) to catch future amendments. | Must | 00 §M.1 |
| REG-3 | All order-placement API access must use static IP whitelisting, OAuth-based auth, and 2FA as mandated broker-wide since April 1, 2026. | Confirmed at primary-source level (00 §M.3). | Must | 00 §M.3 |
| REG-4 | The system must not exceed the exchange-mandated order-rate threshold without formal registration as an Algo Provider (with attendant RA-licensing implications). | Threshold confirmed at 10 orders/second via Upstox primary documentation (00 §M.3); **GATE**: the underlying NSE/ISF circular itself has not yet been directly pulled and read. | Must | 00 §M.3 |
| REG-5 | Market/IOC order restrictions confirmed for the commodity segment (NSE/MSD/67753) must be checked for an equities-segment equivalent before the system relies on either order type. | **TBD** — equities-segment specifics not yet confirmed (00 §M.2). | Must | 00 §M.2 |
| REG-6 | Individual broker Terms of Service must be checked for AI/LLM-specific restrictions on automated order generation, beyond SEBI's regulatory floor. | **TBD / open backlog item** (00 §M.4) — explicitly named as unresearched; this is Priority 2 of the "stage0 3.0" workflow referenced in project memory and should be resolved before or during Architecture, not assumed benign. | Must | 00 §M.4 |
| REG-7 | The tax classification of the system's trading activity (business income vs. capital gains) must be determined, since it affects both compliance and the net-profitability calculation in PR-9. | **TBD / open backlog item** (00 §M.4) — this is Priority 1 of the "stage0 3.0" workflow referenced in project memory. | Must | 00 §M.4 |
| REG-8 | The system must maintain records sufficient to satisfy whatever tax-reporting obligation results from REG-7's eventual determination. | Contingent on REG-7. | Must | REG-7 |

---

## 10. Documentation requirements

| ID | Requirement | Priority |
|---|---|---|
| DOC-1 | Every requirement in this baseline must carry a unique ID (done throughout this document). | Must |
| DOC-2 | Every requirement must state its rationale and, where applicable, its Stage 0 source (done throughout). | Must |
| DOC-3 | Every requirement must carry a priority (Must / Should / Could), consistent with the categories used above. | Must |
| DOC-4 | Every requirement must state its verification method, even if that method is itself deferred (e.g., "design review at Architecture handoff"). | Must |
| DOC-5 | Every requirement must state its dependencies on other requirements where relevant. | Must |
| DOC-6 | Changes to any requirement in future revisions of this document must be tracked (added, not overwritten) — a v0.2, v0.3, etc. convention should be used rather than silent in-place edits, consistent with the "preserve the evolution of decisions" instruction. | Must |
| DOC-7 | This document, and all future Requirements-stage documents, should be written to the project's Notion workspace once write access is confirmed working; until then, this markdown file is the authoritative record, consistent with the fallback pattern established in Stage 0. | Must |

---

## 11. Notion / project log

Per instruction, this closure is recorded here pending confirmed Notion write access:

> **Stage 1 REQUIREMENTS BASELINE v0.2 — APPROVED FOR ARCHITECTURE (dated this session).** All 11 sign-off criteria verified against the existing baseline (see Sign-off Record above); no requirement content changed, no thresholds invented, no technology selected. Stage 0 and v0.1 material preserved in full. Stage 2 — System Architecture v0.1 produced as a companion document immediately following this closure, per instruction not to reopen broad research.

As with prior sessions, Notion write access has previously failed with a "No approval received" error of unconfirmed resolution status. I have **not** assumed success and have not fabricated a write. If you'd like me to attempt the write now, I will and will report the exact result.

---

## 12. Summary: identified requirements, open questions, TBDs, and next steps

### 12.1 Requirements identified
This baseline defines **9 functional**, **7 trading**, **5 autonomy**, **9 risk**, **10 safety/failure**, **9 performance**, **8 data**, **8 evaluation**, **8 regulatory**, and **7 documentation** requirements (72 total), each with an ID, rationale, priority, verification method, and dependency mapping.

### 12.2 Open questions (not yet answerable, not yet researched further per instruction)
- What specific numeric thresholds belong in RR-1, RR-2, RR-3 (exposure, leverage, drawdown limits)? These are operator decisions, not research questions — they should be elicited from you directly rather than researched.
- What evaluation-period length satisfies PR-9's "more than one market regime" bar for Indian equities specifically? Requires either empirical regime analysis or a stated policy choice.
- Whether the eventual strategy design will need DR-3 (fundamental data) or DR-7 (alternative/sentiment data) — contingent on Architecture-stage decisions, now partially addressed in Stage 2 §E.

### 12.3 TBDs requiring validation
PR-1 through PR-9 (baseline comparators, latency bounds, uptime bounds, slippage bounds, evaluation-period length, profitability threshold) — all explicitly left as TBD rather than invented, per instruction.

### 12.4 Requirements that depend on empirical testing
ER-1 through ER-8 cannot be marked "satisfied" until an actual evaluation harness exists and is run; they are design requirements for that harness, not yet-achieved results. Stage 2 §F now specifies the architecture of that harness.

### 12.5 Requirements that must become deployment gates
All of §5 (Safety/Failure, SF-1–SF-10) and §4 (Risk, RR-1–RR-9) must be demonstrated in paper trading before Live Deployment Gate, per the Waterfall sequence. REG-1, REG-4, REG-5, REG-6, REG-7 are explicit compliance gates that must be closed before live deployment regardless of technical readiness.

### 12.6 Status relative to Architecture
This baseline is now closed and approved for Architecture. Items in 12.2/12.3 remain open but do not block Architecture from proceeding — Stage 2 is expected to surface where architectural choices are and are not sensitive to these open items, and to flag (not resolve) any case where an architectural decision cannot responsibly proceed without one of them being closed first.

---

*This document defines what the system must accomplish. It does not propose how. No model, framework, broker, database, cloud provider, agent architecture, API, or programming language has been selected in this document. Those decisions begin in Stage 2 — Architecture (companion document).*
