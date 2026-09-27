# STAGE 2 — SYSTEM ARCHITECTURE v0.1
**AI Trading Agent Research & Engineering Project**
Status: Draft for discussion · Stage 2 (Architecture) · Depends on: Stage 1 Requirements Baseline v0.2 (APPROVED)

This document does not reopen Stage 0 research or Stage 1 requirements. Every architectural choice below is justified by reference to a specific requirement ID (Stage 1) or a specific Stage 0 evidence finding, cited by report/section. Where a choice cannot be justified this way, it is left as an **Open Architectural Question**, not invented.

---

## 1. Executive architecture summary

The requirements (Stage 1) describe a system that must, eventually, autonomously trade Indian equities — but Stage 0's evidence base does not support starting from a large, sophisticated, multi-agent, self-improving design. It supports something narrower: **a deterministic risk-and-execution core that a replaceable, evaluable "intelligence layer" plugs into**, built and validated incrementally, with self-improvement (if any) confined to an offline research environment until it earns its way into anything live.

The central architectural bet this document makes, and the evidence behind it:

- **The risk/execution boundary must be deterministic and independent of whatever produces trading ideas** (RR-1–RR-9, AR-4). This is non-negotiable regardless of what else changes.
- **The "intelligence layer" (what decides what to trade) should start as simple as the requirements allow, and only grow in complexity when a specific, evaluated deficiency justifies it** — because Stage 0 found no evidence that multi-agent architectures outperform simpler ones (00 §F, 02 §O), found contradictory backbone-dependent results where they were compared, and found that added sophistication of any kind consistently underperformed a strong static baseline once evaluation was rigorous (02 §8, DeMiguel et al.).
- **Self-improvement is architecturally separated from live trading entirely at first**, confined to the research/backtesting environment, because Stage 0 found the strongest evidence for AI value in *research automation*, not *live adaptation* (02 §11), and found self-modification to be the single mechanism most structurally prone to undetected overfitting (01 §7) and risk-control erosion (RR-9).
- **The research/backtesting environment is a first-class component, built before trading intelligence, not after** — because Stage 0 found the field-wide absence of disciplined evaluation infrastructure (proper splits, cost modeling, contamination checks) to be a bigger source of illusory results than any specific architecture choice (01 §7, ER-1–ER-8).

This is a "boring core, replaceable brain" architecture: the parts that must never fail (risk, execution, audit) are simple, deterministic, and stable; the part that's actually experimental (what decides trades) is deliberately kept swappable and evaluated against baselines every time it changes.

---

## 2. Architecture principles

These govern every decision below and are the standard against which any future architectural change should be checked.

1. **Minimum complexity required to satisfy the requirements.** Every agent, model, service, or feedback loop must trace to a requirement it satisfies that a simpler design could not. (Per closeout instruction; also consistent with 02 §6's finding that complexity has documented, sometimes uncompensated, cost.)
2. **The risk boundary is authoritative over the intelligence layer, never the reverse** (RR-1–RR-9, AR-4).
3. **Nothing is trusted until it beats a strong, disclosed baseline, evaluated with contamination and leakage controls** (ER-1 through ER-4, 02 §8).
4. **Research and live execution are architecturally separated environments**, not modes of the same running system (§L instruction; SF-1–SF-10 fail-closed philosophy).
5. **Every decision must be reconstructable after the fact** (FR-5, RR-7, §J).
6. **Autonomy level, self-improvement, and architecture are independent axes.** Increasing one must not silently require increasing another (FR-6, AR-1, RR-9).
7. **Fail closed, not open.** Every ambiguous or failed state defaults to "no new action," never to "proceed and hope" (§5 SF-1–SF-10).
8. **Provider/broker/model independence at the design level** (TR-6) — the architecture must not assume a specific vendor even where Stage 2 does select initial candidates for build purposes.

---

## 3. System context

**Actors:**
- **Operator** (you) — sets constraints, approves autonomy-level transitions, holds the kill switch, reviews research outputs before promotion.
- **The system** — ingests data, forms decisions, requests execution, subject to the risk boundary at all times.
- **Broker** — external system of record for orders, positions, and cash; authoritative for what actually happened, not the system's own belief about what happened.
- **Data providers** — external sources of market, fundamental, cost, and regulatory data (not yet selected — TR-6).
- **Regulators/exchanges** — impose constraints the system must never cross (REG-1–REG-8), independent of the system's own internal risk settings.

**System boundary:** the system's authority ends at "generate and submit an order request to the broker under approved risk constraints." It does not extend to broker-side matching, clearing, settlement, or custody — those remain the broker/exchange's domain and are treated as external, potentially-failing dependencies (SF-4, SF-5).

---

## 4. Component architecture (overall system)

At the top level, the system is five architecturally-separated planes, each independently testable and independently replaceable:

```
┌─────────────────────────────────────────────────────────────────────┐
│  PLANE 0 — GOVERNANCE (operator-owned, system-read-only)             │
│  Autonomy level · Risk constraint values · Instrument universe ·     │
│  Kill switch · Promotion approvals                                    │
└───────────────────────────────┬───────────────────────────────────────┘
                                 │ (read-only to planes below; write-only by operator)
┌────────────────────────────────▼──────────────────────────────────────┐
│  PLANE 1 — DATA                                                       │
│  Ingestion → Validation/staleness → Normalization → Feature/context   │
│  formation → Decision-log store (also captures the system's own       │
│  outputs as data, per DR-8)                                           │
└────────────────────────────────┬──────────────────────────────────────┘
                                 │
┌────────────────────────────────▼──────────────────────────────────────┐
│  PLANE 2 — INTELLIGENCE (replaceable "brain")                         │
│  Analysis → Candidate trade generation → Confidence/uncertainty       │
│  signal. Versioned. Swappable. Never has execution authority.         │
└────────────────────────────────┬──────────────────────────────────────┘
                                 │  (candidate trade + rationale, NOT an order)
┌────────────────────────────────▼──────────────────────────────────────┐
│  PLANE 3 — RISK & EXECUTION (deterministic, non-LLM)                  │
│  Cost estimation → Risk validation → Position sizing → Sanity checks  │
│  → Order generation → Broker interface → Confirmation → Reconciliation│
└────────────────────────────────┬──────────────────────────────────────┘
                                 │
┌────────────────────────────────▼──────────────────────────────────────┐
│  PLANE 4 — OBSERVABILITY & EVALUATION                                 │
│  Outcome logging → Reconciliation vs. broker truth → Evaluation       │
│  harness (offline) → Regime/cost/leakage-aware reporting              │
└─────────────────────────────────────────────────────────────────────┘
```

**Why this shape, specifically:** the requirement that risk controls "must not depend solely on the intelligence/model that generates the trade" (per closeout instruction §H) is only enforceable if Plane 2 and Plane 3 are genuinely separate components with a narrow, well-typed interface between them (a candidate trade + confidence, not an order) — not two responsibilities inside one monolithic agent. This also directly satisfies TR-3 (inspectable sizing rule) and RR-7 (attributable rationale), since Plane 3 cannot act on anything Plane 2 didn't hand it through that interface, and everything crossing the interface is logged by construction (Plane 1/4).

A sixth, deliberately *separate* environment — the **Research & Backtesting environment (§F)** — consumes the same Plane 1 data contracts and can produce new candidate Plane 2 versions, but has no connection to Plane 3 at all. This is the architectural enforcement of "research/self-improvement experiments must not directly modify the live trading environment" (closeout §L).

---

## 5. ADR-1 — Agent / trading-intelligence architecture (single vs. multi-agent vs. hybrid)

**Problem:** What should Plane 2 (Intelligence) look like — one LLM call, a single agent with tools, a multi-agent "trading firm," or a deterministic/LLM hybrid?

**Options considered:**

| Option | Description |
|---|---|
| A. Multi-agent specialist team (TradingAgents-style) | Role-specialized agents (fundamental/sentiment/news/technical analysts, bull/bear researchers, trader, risk manager) coordinated via an orchestration graph |
| B. Single LLM agent with tools | One agent, given data access and tools, produces the candidate trade directly |
| C. Deterministic/quant core + LLM as one input among several | Classical factor/signal logic does the heavy lifting; an LLM contributes a bounded, specific input (e.g., news interpretation) that is one signal among several, not the final decision-maker |
| D. Hybrid, staged: start at (B) or (C), architect Plane 2 so (A) is a later, empirically-justified upgrade, not a starting assumption | — |

**Comparison against evidence:**
- Stage 0 found **no evidence that multi-agent architectures outperform simpler ones**; the flagship multi-agent paper (TradingAgents) never benchmarked against a simpler analyst+executor baseline (00 §F). Controlled ablations that do exist directly **contradict each other**: AlphaQuanter found single-agent beat multi-agent on 6/7 backbones (with multi-agent costing ~6.7x more tokens for worse results); a crypto-portfolio paper found the opposite across 3 backbones (02 §O). The best reconciling hypothesis found (benefit shrinks as backbone capability increases) is itself unconfirmed in the trading domain (02 §O).
- Multi-agent debate has a documented cost: **injecting noise / amplifying hallucination in smaller models**, and a **~6.7x token cost** in the one paper that measured it directly (02 §O, AlphaQuanter).
- StockBench found that **capability on static financial knowledge tasks does not translate into effective trading behavior** (02 §4.2) — i.e., adding more LLM reasoning steps (which is what more agents mostly buys) is not obviously the lever that matters.
- Principle 1 (minimum complexity) and the requirement that Plane 2 be swappable without Plane 3 rework (FR-6) both favor starting simple.

**Trade-offs:**
- Option A is the "fashionable" choice and the most-published pattern, but Stage 0 explicitly warns against choosing it "simply because it sounds sophisticated" (closeout §C) — and the evidence doesn't support it as a default.
- Option C (deterministic-core-first) is the most conservative and the easiest to evaluate/attribute (supports RR-7, TR-3 directly), but risks under-using the one thing LLMs are evidenced to help with in this space: research/strategy-discovery acceleration (02 §11), if taken too literally as "no LLM in the loop at all."
- Option B is a reasonable middle ground but still concentrates all reasoning in one component with no internal separation of concerns (e.g., a factual data-reading step vs. a decision step), which makes debugging/attribution (RR-7) harder than necessary.

**Recommendation: Option D — start at Option C's spirit (deterministic/quant baseline strategies as the first working Plane 2 implementations), add a single, narrowly-scoped LLM-assisted analysis component only once a deterministic baseline exists to compare it against, and treat multi-agent decomposition as a Phase-3+ experiment run through the Research environment (§F) and promoted only if it demonstrably beats the then-current single-agent/deterministic Plane 2 on the ER-1 baseline comparison.**

**Why:** This directly implements ER-1 (must compare against a naive static baseline and a well-tuned deterministic strategy) by making the deterministic strategy the *starting* Plane 2, not an afterthought benchmark bolted on later. It also means the very first live-capable version of the system is the easiest one to risk-certify (SF-1–SF-10) and audit (RR-7), since deterministic logic is maximally inspectable. LLM-based components are added incrementally, each one required to clear the ER-1–ER-8 evaluation bar before promotion (§F, §M), rather than being assumed necessary from day one.

**What would invalidate this decision:** A rigorous, contamination-controlled, cost-adjusted evaluation (built per §F) showing a specific LLM-based or multi-agent Plane 2 variant reliably beats the current deterministic/single-agent baseline across multiple regimes (ER-6) with a properly corrected significance level (ER-4) — not a single favorable backtest. Absent that evidence, the system should not carry more Plane 2 complexity than the deterministic baseline needs.

---

## 6. ADR-2 — Self-improvement architecture

**Problem:** Where, if anywhere, does self-improvement live, and what exactly is allowed to change?

Per the closeout instruction, distinguishing:
1. Static system
2. Runtime adaptation
3. Strategy/prompt/harness improvement
4. Offline model improvement
5. Weight-level model adaptation
6. Autonomous modification of its own code

| Type | What it could improve | What could go wrong | Belongs in live system? | Isolated from live? | How evaluated | Must NEVER modify |
|---|---|---|---|---|---|---|
| 1. Static system | N/A — baseline | N/A | Yes (this is Plane 2 v1, per ADR-1) | N/A | ER-1–ER-8, on promotion only | — |
| 2. Runtime adaptation (e.g., regime-conditioned parameter switch, decided by a fixed rule at run time) | Reaction speed to detected regime shift | Reacting to noise as if it were regime change; lag (02 §3.2) | Only if the *rule* itself is static and was validated offline (i.e., "adaptation" here means "a pre-approved conditional," not "the system decides new conditionals live") | N/A — the rule is fixed at deploy time, so there's nothing live to isolate | Regime-segmented backtest (ER-6) before deployment | Risk constraints (RR-1–RR-9), autonomy level (AR-2) |
| 3. Strategy/prompt/harness improvement | Decision quality, e.g. via prompt optimization (ATLAS-style) | Field's one controlled result found this helps; reflection specifically did **not** (02 §13) — mechanism-dependent, not uniformly good | **No — research environment only.** Promoted to live only as a new versioned Plane 2 release, same as any other change | **Yes, fully isolated.** Runs entirely in §F | ER-1–ER-8, with ER-7's discovery-vs-adaptation split applied | Anything in Plane 3 |
| 4. Offline model improvement (e.g., evolutionary strategy/alpha generation, CogAlpha-style) | Candidate strategy discovery | Structurally the closest thing to automated overfitting (01 §7); requires PBO/CSCV correction | **No — research environment only**, by design (this is squarely "research productivity," the best-evidenced value case, 02 §11) | **Yes, fully isolated** | ER-1–ER-8 in full, including ER-4's multiple-testing correction | Anything in Plane 3; also may not silently expand DR-3/DR-7 data usage without a data-requirement review (Stage 1 §7 note) |
| 5. Weight-level model adaptation (fine-tuning/RL, e.g. FinRL-DeepSeek-style) | Policy quality | Stage 0's own disclosed finding: "the use of LLM always worsens performance" in at least one tested configuration (01 §6) — genuinely mixed, not safe to assume beneficial | **No — research environment only**, and only as an explicit, human-reviewed experiment, not an automated loop | **Yes, fully isolated**, and additionally version-pinned (a specific weight snapshot is what gets promoted, not an ever-updating model) | Same as #4, plus explicit reporting of any regression vs. the non-fine-tuned baseline | Anything in Plane 3; must not be allowed to silently replace a pinned Plane 2 version without going through promotion review |
| 6. Autonomous code/architecture self-modification (DGM/HGM-style) | The agent's own orchestration logic | **No credible evidence this exists safely anywhere in finance** (01 §5); HGM's own safety model assumes resettable, repeatable trials, which financial markets are not (01 §5) | **No.** Not adopted at all in this architecture version. | N/A | N/A | N/A |

**Decision:** Self-improvement of any kind (types 2–5) is **architecturally confined to the Research & Backtesting environment (§F)**, which has no live execution capability at all. Nothing self-improving ever runs against real capital directly; it only ever produces a *candidate new versioned Plane 2 artifact*, which must clear the same promotion gate (§M) as any human-authored change before it can run in paper trading, and the same gate again before live. Type 6 (autonomous code self-modification) is explicitly **out of scope for this architecture** — not deferred, rejected, given the total absence of finance-relevant evidence (01 §5) and the RR-9 requirement that no self-improvement mechanism may touch risk constraints, which an architecture-modifying agent could not credibly guarantee.

This directly implements RR-9: since self-improvement never has write access to Plane 3 or Plane 0, and its only output is a candidate artifact subject to human-gated promotion (AR-2-style: no self-promotion), there is no path by which a self-improving mechanism could erode a risk constraint even if it wanted to.

**What would invalidate this decision:** Evidence from our own Research environment (not the published literature, which Stage 0 found insufficiently rigorous, 01 §7) that a specific self-improvement mechanism reliably outperforms the then-current static baseline across regimes, after ER-4's multiple-testing correction, with the discovery-vs-adaptation distinction reported separately (ER-7). Even then, this would justify promoting a *specific resulting artifact*, not turning on a live, ongoing self-modification loop — the live/research separation itself does not go away.

---

## 7. Data architecture

| Data category | Stage 1 requirement | Architectural treatment |
|---|---|---|
| Market price/volume (real-time + historical) | DR-1 | Single ingestion adapter interface; provider-agnostic (TR-6); normalized into a common internal schema before anything downstream touches it |
| Corporate actions | DR-2 | Applied at the normalization step, before features are formed — never left to each Plane 2 implementation to handle individually (prevents the survivorship/adjustment bugs Stage 0 flagged as field-wide, 01 §7) |
| Fundamentals | DR-3 (Should) | Adapter interface exists but is not populated in the v1 build unless a specific Plane 2 strategy needs it; contingent, not default |
| Transaction cost / tax / fee data | DR-4 | A dedicated **Cost Model** component, versioned separately from Plane 2, since it must be current as of the period being evaluated (ER-5) and current as of "now" in live use — these can differ and must not be conflated |
| Order-book/microstructure | DR-5 (Should) | Adapter interface exists; populated when PR-7 (slippage measurement) requires it |
| Regulatory/circular updates | DR-6 | Treated as data, not configuration — feeds an operator-facing alert, not an automatic rule change (a regulatory change must never silently alter RR-1–RR-9 without operator review, consistent with AR-2's "no self-promotion" spirit) |
| News/sentiment/alternative | DR-7 (Could) | Adapter interface reserved, not built in v1 |
| System's own decision/outcome log | DR-8 | Written by Plane 1 as a first-class output of every decision cycle (not bolted on by Plane 4 after the fact); this is what makes FR-5, RR-7, and the entire evaluation harness (§F) possible at all |

**Data flow principle:** all data enters through Plane 1's ingestion → validation/staleness (SF-1, SF-2) → normalization pipeline before any other plane sees it. No Plane 2 implementation, however it's built, is permitted its own separate, unvalidated data path — this is what makes "swap Plane 2 without touching the rest" (FR-6) actually true rather than aspirational.

---

## 8. Decision architecture (lifecycle)

The closeout's proposed lifecycle is adopted with one addition (an explicit uncertainty/confidence checkpoint, to satisfy SF-10) and one clarification (the plane boundary is made explicit):

```
Data                                              [Plane 1]
 ↓
Data validation (SF-1, SF-2)                      [Plane 1]
 ↓
Feature/context formation                         [Plane 1]
 ↓
Analysis                                          [Plane 2]
 ↓
Candidate trade + confidence/uncertainty signal   [Plane 2]  ← interface boundary
 ↓
Cost estimation (TR-2)                            [Plane 3]
 ↓
Risk validation (RR-1–RR-7)                       [Plane 3]
 ↓
Position sizing (TR-3)                            [Plane 3]
 ↓
Uncertainty check (SF-10) — low confidence routes
  to smaller size / hold / human escalation        [Plane 3]
 ↓
Pre-execution sanity checks (SF-8)                [Plane 3]
 ↓
Order generation                                  [Plane 3]
 ↓
Execution (broker)                                [Plane 3 / external]
 ↓
Confirmation (SF-5)                               [Plane 3]
 ↓
Position reconciliation (FR-4)                    [Plane 3 → Plane 1]
 ↓
Outcome logging (DR-8)                            [Plane 1]
 ↓
Evaluation / learning                             [Plane 4 / §F — offline only]
```

**Why the interface boundary sits exactly where it does:** everything above the line ("Candidate trade + confidence") is Plane 2's responsibility and may be swapped freely; everything below is Plane 3 and must remain stable and auditable regardless of what Plane 2 currently is. This is the direct architectural implementation of closeout §H's instruction that "the intelligence layer must NOT be able to override these controls" — it's not a policy Plane 2 agrees to follow, it's a hard boundary Plane 2 has no code path to cross.

---

## 9. Risk architecture

The Risk & Execution plane (Plane 3) is deliberately **not** an LLM component and has no dependency on whichever Plane 2 implementation is active. It enforces, as hard gates (not advisory checks):

- Maximum exposure (RR-1), leverage/margin (RR-2), drawdown-triggered halt (RR-3)
- Permitted universe membership (RR-4, TR-1/TR-7)
- Order-rate ceiling (RR-5)
- Scope-of-use check (RR-6)
- Attributability check — a candidate trade lacking a loggable rationale is rejected outright, not passed through with a blank reason (RR-7)
- Kill switch (AR-3, RR-8) — implemented as a state Plane 3 checks *before every single action*, not a background process Plane 2 or 3 could race past
- Autonomy-level gate (AR-1, AR-4) — the set of actions Plane 3 will execute without further approval is a direct function of the current autonomy level, which Plane 3 reads from Plane 0 (operator-owned) and cannot itself write

**Why this must be architecturally separate, not just logically separate:** Stage 0's own finding (RR-9's justification, 01 §12) is that self-modification is exactly the mechanism through which risk controls get quietly eroded over time. A "separate risk module" that is nonetheless part of the same self-improving artifact as Plane 2 does not actually protect against this — it must be a genuinely different codebase/service with no shared mutable state, updated only through the human-gated promotion process (§M), never through anything Plane 2 or the Research environment can trigger on its own.

---

## 10. Execution architecture

- **Boundary:** decision (Plane 2) → risk approval (Plane 3) → broker execution (external). Plane 2 never talks to the broker directly, under any autonomy level, including Level 3 — "no per-transaction human oversight" (AR-1's Level 3 definition) describes the *operator's* role, not a shortcut that lets Plane 2 skip Plane 3.
- **Broker abstraction:** a single internal interface (order placement/modification/cancellation, position/balance query) that any specific broker's API must be adapted to (TR-6). This is what lets Architecture defer the actual broker selection without blocking other design work.
- **Regulatory/contractual gate, explicit:** per closeout §I, technical API capability is not treated as equivalent to legal/contractual permission. The execution path is marked, in this architecture, as **blocked from live use until REG-1, REG-4, REG-5, REG-6, REG-7 are closed** (Stage 1 §9), regardless of how technically ready Plane 3 is. This is a deployment gate, not a technical dependency, and is tracked as such (§L below).
- **Confirmation discipline (SF-5):** the system never marks an order as filled based on its own request having been sent; it waits for and reconciles against the broker's own confirmation, consistent with FR-4's "track positions... at all times" being defined relative to broker-reported truth, not the system's optimistic assumption.

---

## 11. Research / backtesting architecture

This is a first-class, separately-deployed component — not a mode of the live system — because Stage 0's single strongest field-wide finding is that evaluation-infrastructure quality, not architecture sophistication, is what determines whether a result can be trusted at all (01 §7, ER-1–ER-8).

**Required capabilities (mapped to Stage 1 evaluation requirements):**

| Capability | Satisfies | Architectural note |
|---|---|---|
| Historical replay | FR-1, PR-8 | Operates against Plane 1's *stored* historical data, using the same normalization pipeline live trading uses, so a candidate Plane 2 is tested against data shaped exactly as it would see live |
| Walk-forward evaluation with genuinely held-out splits | ER-2 | Chronological split enforcement is a property of the harness itself, not left to each experiment's discipline — the harness refuses to run an evaluation without a declared, checked split |
| Baseline comparison (naive static, deterministic, prior version) | ER-1 | The harness always runs the candidate *and* the current baseline(s) side by side on the identical window; a candidate cannot be "evaluated" without this comparison being produced |
| Contamination/leakage checks | ER-3 | A pre-flight check comparing the evaluation window against any LLM component's known training-data cutoff; flags (does not silently proceed past) overlap |
| Multiple-testing correction (PBO/CSCV-style) | ER-4 | Tracked at the harness level across *all* variants tried for a given candidate line, not just the one that "won" — this requires the harness to log every attempted variant, not only the reported best one |
| Cost/tax/slippage modeling | ER-5, TR-2, DR-4, DR-5 | Uses the same Cost Model component Plane 3 uses live, so research-stage cost assumptions and live-stage cost assumptions cannot silently diverge |
| Regime-segmented reporting | ER-6 | A regime-labeling step (rising/falling/range-bound, at minimum) applied to every reported result, not an optional add-on |
| Discovery-vs-adaptation separated reporting | ER-7 | Only relevant once/if any self-improvement mechanism (§6, types 2–5) is under evaluation; the harness's reporting schema reserves separate fields for this from the start so it isn't bolted on awkwardly later |
| Pre-registered negative/disqualifying criteria | ER-8 | A required field before an evaluation run is accepted by the harness — "what would count as this candidate failing" must be declared before results are seen |
| Version comparison / reproducibility | §M | Every run records exact data version, code version, config, and random seed used |

**Isolation:** the Research environment has read access to historical Plane 1 data and read access to the Cost Model, and produces versioned candidate-artifact outputs. It has **no** write access to Plane 3, Plane 0, or any live broker connection, and no network path to one is provisioned. This isn't a policy — it's the deployment topology (§L).

---

## 12. Observability / audit architecture

Directly implementing closeout §J's question list, each decision cycle's log record must be able to answer, without needing to re-derive anything:

- What did it know? → the exact Plane 1 feature/context snapshot used, referenced by version
- What data did it use? → source + version + timestamp of every input
- What did it decide? → the candidate trade + confidence from Plane 2
- Why? → Plane 2's logged rationale (RR-7 — no black-box-only justification permitted)
- What risk limits were applied? → the specific RR-x checks evaluated and their pass/fail state at that moment
- What order was generated? → the exact order request Plane 3 sent
- What actually happened? → the broker's confirmed fill/rejection, not the request
- What did it cost? → realized cost vs. TR-2's pre-trade estimate, reconciled (PR-6)
- What was the resulting P&L? → tied back through FR-4's position tracking
- Which version of the system made the decision? → Plane 2 artifact version + Plane 3 version + Cost Model version, all independently tracked (per §M)
- Which autonomy level was active? → per AR-5

**Design consequence:** the decision log (DR-8) is not a side effect of logging statements scattered through the code — it is a structured, versioned record that Plane 1 constructs deliberately at each stage of §8's lifecycle, because reconstructability (FR-5) is a requirement, not a debugging convenience.

---

## 13. Failure architecture

Direct mapping of Stage 1's SF-1–SF-10 to architectural mechanism:

| Requirement | Mechanism |
|---|---|
| SF-1 (missing data) | Plane 1 validation stage rejects incomplete feature sets before they reach Plane 2; Plane 2 never receives a "silently null" field |
| SF-2 (stale data) | Plane 1 attaches a freshness timestamp to every datum; a configurable staleness threshold converts stale → treated-as-missing (SF-1 path) |
| SF-3 (malformed model output) | Plane 3's input parser for the Plane 2 → Plane 3 interface schema-validates the candidate trade; anything that fails validation is discarded, logged, and treated as "no candidate this cycle" |
| SF-4 (external API failure) | All external adapters (data, broker) implement a fail-safe default (no data → SF-1 path; broker call failure → SF-5 path), never a retry-with-guessed-value |
| SF-5 (broker failure) | Plane 3 halts new order placement on any unconfirmed broker state; existing orders are not assumed successful without explicit confirmation |
| SF-6 (connectivity loss) | Plane 3's default state on any loss of its data/broker connections is "no new positions" — this is the resting state of the system, not an exception path bolted on |
| SF-7 (abnormal market) | A dedicated abnormal-market detector (circuit-breaker/halt/extreme-volatility signals) sits ahead of Plane 2 in the pipeline and can force the cycle straight to "hold," bypassing Plane 2 entirely when triggered |
| SF-8 (bad decision, sanity check) | A rule-based sanity check inside Plane 3, independent of Plane 2's own confidence signal, can veto any candidate trade regardless of source |
| SF-9 (component disagreement) | Only relevant if Plane 2 itself is internally multi-component (ADR-1's Option A/D-later case); the resolution rule (default to the more conservative action) is defined at the Plane 2 internal-interface level and does not require Plane 3 to know Plane 2's internals |
| SF-10 (uncertainty) | The confidence/uncertainty field is mandatory in the Plane 2 → Plane 3 interface (not optional); Plane 3's sizing logic is a direct function of it |

**Principle applied throughout:** every failure mode's default is "no new action," never "best guess and proceed" — this is what "fail-closed" means architecturally, not just as a stated value.

---

## 14. Environment separation

| Environment | Purpose | Connected to live broker? | Connected to real capital? | Can write to Plane 3/Plane 0? |
|---|---|---|---|---|
| Development | Code changes, unit tests | No | No | No |
| Research/backtesting (§11) | Strategy discovery, self-improvement experiments, evaluation | No | No | No |
| Paper trading | End-to-end validation of Plane 1–3 wiring against live *data* with simulated execution | Simulated / broker paper-mode only | No | No (a promoted artifact runs here, but paper trading itself has no path to live capital) |
| Staging | Pre-live rehearsal at the smallest meaningful real capital exposure, if the operator chooses to define one (not required by any Stage 1 requirement, offered as good practice) | Yes, live broker, minimal exposure | Optionally, operator-approved minimal | No — same promotion rule as live |
| Live | Real trading | Yes | Yes | N/A — this *is* Plane 3/Plane 0's live instance |

No environment above Research can be reached by anything the Research environment produces without passing through the promotion gate (§M) and, for paper→staging→live specifically, an explicit autonomy-level/deployment-gate decision by the operator (AR-2).

---

## 15. Versioning / reproducibility

Every one of the following is independently versioned, because §M requires reconstructing *why* a historical trade happened, which requires knowing exactly which combination of these was active at that moment:

- Plane 2 artifact (strategy/prompt/model/weights, whichever is current)
- Plane 3 logic (risk rules, sizing rules)
- Cost Model
- Data snapshot/version used for any given decision or backtest
- Configuration (all operator-set constraint values, per Plane 0)
- Risk-rule version specifically (distinct from general Plane 3 versioning, since RR-9 makes this the one thing that must be provably untouched by any self-improvement artifact)
- Every Research-environment experiment (including ones that did *not* get promoted — required for ER-4's multiple-testing correction to be honest)
- Every live/paper decision and its outcome (DR-8)

**Architectural mechanism:** every artifact above carries an immutable version identifier; the decision log (§12) records the exact identifier set active for every decision. This is what makes "reproduce why a historical trade happened" (closeout §M) an actual capability rather than an aspiration.

---

## 16. Security boundaries

Not exhaustively re-derived here (Stage 0's security findings, 00 §D.5/§H, stand), but architecturally located:

- The **kill switch (AR-3/RR-8)** is implemented at the Plane 3 boundary with its own independent trigger path — it must not depend on Plane 2, the Research environment, or any LLM-based component being cooperative or even responsive to shut down.
- **Credential/secrets isolation:** broker credentials and any order-placement capability live only inside Plane 3's execution adapter; Plane 2 (wherever an LLM lives) has no credential access of any kind, which is a direct structural defense against the "lethal trifecta" (excessive agency + untrusted input + exfiltration capability) pattern Stage 0 flagged (00 §D.5, 01 §12) — an LLM component that is never given credentials cannot exfiltrate or misuse them, regardless of prompt injection risk.
- **Static IP / OAuth / 2FA (REG-3)** apply at the broker-adapter layer specifically, since that's the only component that talks to the broker's order-placement API.
- **The Research environment's isolation (§11, §14)** is itself a security boundary, not just a methodological one: since it has no live-broker network path provisioned, a compromised or misbehaving self-improvement experiment cannot reach real capital even if it tried.

---

## 17. Major Architecture Decision Records — summary

| ADR | Decision | Status |
|---|---|---|
| ADR-1 | Plane 2 (intelligence) starts deterministic/simple; multi-agent is a later, evidence-gated upgrade, not a default | Recommended |
| ADR-2 | Self-improvement confined entirely to the Research environment; no live/online adaptation; no autonomous code self-modification adopted | Recommended |
| ADR-3 (implicit, §9) | Risk/execution (Plane 3) is a separate, deterministic, non-LLM component with hard veto power over Plane 2 | Recommended |
| ADR-4 (implicit, §10) | Live execution path is technically designed but gated closed pending REG-1/4/5/6/7 closure | Recommended |
| ADR-5 (implicit, §11) | Research/backtesting environment is built before, and is a prerequisite to trusting, any Plane 2 beyond the deterministic baseline | Recommended |

---

## 18. Technology decisions

Per instruction, only what the architecture actually requires is selected now; nothing is chosen for its own sake, and each choice states what would change the recommendation.

| Category | Recommendation | Why | What would invalidate it |
|---|---|---|---|
| Programming language (core system) | Python | Dominant ecosystem for quantitative finance, data handling, and every backtesting/LLM-orchestration tool surfaced across Stage 0's entire research corpus (TradingAgents, FinMem, FinCon, CogAlpha, HASE all Python); minimizes integration friction with broker SDKs (Kite Connect, Upstox, Fyers all ship Python SDKs) | A hard latency requirement (PR-3, still TBD) that Python genuinely cannot meet even with standard optimization (numpy/vectorization, async I/O) — not established at this stage |
| Plane 2 orchestration (if/when multi-step LLM reasoning is used) | Deliberately **not selected yet.** Start with direct, explicit function calls (no framework) for the deterministic and single-agent Plane 2 versions; only adopt a graph/orchestration framework (e.g., LangGraph-style) if and when ADR-1's evidence bar for multi-agent is actually cleared | Adopting an orchestration framework before it's needed adds a dependency and a failure surface (Principle 1) for a capability (multi-agent coordination) not yet justified | A promoted, evidence-cleared multi-agent Plane 2 candidate from the Research environment |
| Data storage | A relational store (e.g., Postgres-class) for positions/decisions/config, plus a time-series-oriented store for market data, kept as separable concerns via the Plane 1 adapter interface | FR-4, DR-8, and §15's versioning needs are relational/transactional in nature; market data has different access patterns (range queries over time) that a general relational store handles adequately at this project's scale without requiring a specialized time-series database yet | Data volume/query-latency needs that a general relational store genuinely cannot serve — not established at this stage; avoid pre-optimizing |
| Experiment tracking / versioning (§15) | A structured, file-based versioning discipline (content-addressed or explicitly incrementing artifact IDs, stored alongside their config/data-version metadata) rather than a heavyweight MLOps platform initially | Matches DOC-7's Markdown/Obsidian-portability philosophy already established for documentation; avoids a dependency whose main value (team-scale experiment coordination) doesn't apply to a personal, single-operator project | If experiment volume grows large enough that manual/file-based tracking becomes error-prone — a scale threshold, not a principle, and can be revisited without re-architecting |
| Backtesting/evaluation harness (§11) | Purpose-built, not an off-the-shelf backtesting library used as-is | No off-the-shelf tool surfaced anywhere in Stage 0's research does walk-forward + PBO/CSCV correction + LLM-contamination checking + regime segmentation + cost modeling together (ER-1–ER-8); an off-the-shelf engine may still be used underneath for basic historical replay mechanics, but the evaluation discipline layer must be custom | A specific off-the-shelf tool found during Stage 3 (Detailed Design) that genuinely implements ER-1–ER-8's full discipline — not currently known to exist |
| Broker integration | Abstracted interface now; specific broker (Zerodha/Upstox/Fyers) selection deferred to Stage 3, pending REG-6 (ToS review) closure for whichever candidate(s) are considered | TR-6 explicitly requires this separability; Stage 1's REG-6 gate means selecting a broker before its ToS is reviewed for AI-specific restrictions would be premature | REG-6's findings once that backlog item (Priority 2, "stage0 3.0") is closed |
| Deployment environment | Containerized, environment-separated (§14) — specific cloud/local choice deferred | REG-3's static-IP requirement is a real constraint on whatever hosting is chosen (dynamic-IP platforms like Heroku/Railway were reported broken by this exact requirement, 00 §M.3) and must be checked against any candidate before selection, not after | Any candidate hosting environment's static-IP support, checked in Stage 3 |
| Monitoring/alerting | Structured logs (§12) feeding a simple operator-facing dashboard/alert channel; no heavyweight observability platform selected yet | Matches Principle 1; the personal, single-operator scale doesn't yet justify more | Multi-environment (§14) or multi-strategy scale that makes manual log review impractical |
| Secrets management | Environment-isolated secret storage (not committed to any versioned artifact in §15), broker credentials confined to the Plane 3 execution adapter only (§16) | Directly required by the security boundary in §16 | — |
| Scheduling | Deferred — depends on TR-5's intraday/delivery decision (still open) and PR-3's latency requirement (still TBD) | Premature to select before those are resolved | TR-5/PR-3 resolution |
| Messaging/event infrastructure | Not adopted for v1 — direct function-call/pipeline structure across Planes 1–3 within a single deployable unit is sufficient at this scale and evidence base | Principle 1; no requirement currently demands independently-scalable, asynchronously-decoupled planes | A specific throughput/latency finding in Stage 3 that direct calls cannot satisfy |

---

## 19. Build philosophy — incremental construction

Adopting the closeout's proposed sequence, refined against the plane architecture above:

```
Research environment (§11) — including its Cost Model and evaluation harness
        ↓
Data pipeline (Plane 1) — ingestion, validation, normalization, decision-log schema
        ↓
Deterministic baseline strategies (Plane 2 v1) — the ER-1 baseline comparators themselves
        ↓
Evaluation harness proven against the baseline (ER-1–ER-8 exercised end-to-end)
        ↓
Trading intelligence (Plane 2 v2+) — single LLM-assisted component, evaluated against v1
        ↓
Risk engine (Plane 3) — built and adversarially tested against RR-1–RR-9 independent of whichever Plane 2 exists
        ↓
Paper execution (Plane 3 in paper-trading environment, §14)
        ↓
End-to-end paper trading (Level 0/1 per AR-1, FR-6)
        ↓
Autonomy progression (Levels 1→2, per AR-2's explicit-operator-decision requirement)
        ↓
Live execution gate (blocked on REG-1/4/5/6/7 per §10)
        ↓
Controlled live deployment (Level 2, minimal capital, staging environment if chosen)
        ↓
Fully autonomous operation (Level 3, per AR-4's bounded-autonomy definition)
```

**Deviation from the closeout's suggested order, and why:** the Research environment and evaluation harness are moved to *before* the data pipeline's "production" hardening, because the harness needs realistic historical data to exist and be validated against almost immediately (it's what proves the deterministic baseline is a fair comparator at all) — building it last would mean the deterministic-baseline milestone couldn't actually be *evaluated* when it's reached, only asserted.

---

## 20. Architecture risks

| Risk | Why it matters | Mitigation in this architecture |
|---|---|---|
| Plane 2/Plane 3 interface becomes a de facto backdoor (Plane 2 encodes risk logic implicitly to influence Plane 3's sizing) | Would silently reintroduce the "black-box size decision" problem TR-3 exists to prevent | Plane 3's sizing rule must remain independently specified and auditable regardless of what confidence values Plane 2 sends; periodic review of whether Plane 2's confidence outputs are being gamed (a Goodhart-style risk, 01 §12) should be part of promotion review (§M) |
| Research-environment findings feel more validated than they are, because "our own harness said so" | Same overconfidence failure mode Stage 0 found across the published literature (01 §7) could simply relocate to our own results if the harness isn't itself periodically audited | ER-8's pre-registered negative-result criteria and DOC-6-style versioning of experiments (§15) are the check; the harness's own assumptions should be revisited, not assumed correct forever |
| REG-4/5/6/7 gates create schedule pressure to route around them ("just paper trade forever, doesn't need the gate") | Paper trading has real value but must not quietly become the permanent destination, mirroring the exact failure mode named in Stage 0 (00 §L Q5) for autonomy levels | The gate is architectural (live execution path is technically inert without gate closure, §10), not merely procedural, so it cannot be "forgotten past" |
| Cost Model drift between Research and Live use (§7) | If they diverge, ER-5's "no gross numbers presented as net" guarantee breaks silently | Shared Cost Model component (§7, §11) by construction, not two independent implementations |
| Complexity creep in Plane 2 without corresponding evidence (violating Principle 1) | The single most consistent Stage 0 finding is that added sophistication tends to underperform once rigorously evaluated (02 §8) | ADR-1's evidence-gated promotion requirement; every Plane 2 change must clear ER-1 comparison before promotion, not just "seem better" |

---

## 21. Open architectural questions

These are genuine gaps this document does not resolve, consistent with the instruction not to invent answers:

1. **Exact Plane 2 v1 deterministic baseline strategy design** — "a well-tuned classical/deterministic strategy" (ER-1) is a requirement, not yet a specification; Stage 3 (Detailed Design) needs to pick a concrete, defensible classical strategy (e.g., a documented momentum or mean-reversion factor with NSE/BSE-specific literature support, per 02 §12) rather than an arbitrary one.
2. **Latency requirements (PR-3) and their effect on scheduling/hosting choices (§18)** — genuinely blocked on TR-5's intraday-vs-delivery decision, which is itself blocked on REG-7 (tax classification) closure.
3. **Whether a staging environment (§14) is worth building given personal-project scale**, or whether paper trading directly to a minimal live-capital Level 2 is preferable — this is a risk-tolerance/operator judgment call, not a research question.
4. **The precise contamination-check procedure for ER-3** — FactFin/FinLake-Bench were noted in Stage 0 (01 §7) as a candidate methodology, not confirmed as directly reusable; Stage 3 needs to determine whether to adopt, adapt, or build this checking mechanism from scratch.
5. **Numeric risk thresholds (RR-1–RR-3)** — explicitly an operator decision, not an architectural one; architecture only requires that these be operator-writable, system-read-only configuration values (§9), which is satisfied regardless of their eventual values.

---

## 22. Requirements → architecture traceability (summary)

| Stage 1 requirement group | Primary architectural home |
|---|---|
| FR-1–FR-8 (Functional) | Planes 1–4 overall; FR-6/FR-8 specifically via the Plane 2 swap boundary and versioning (§15) |
| TR-1–TR-7 (Trading) | Plane 0 (universe config) + Plane 3 (cost, sizing, hold-as-decision, intraday/delivery distinction) |
| AR-1–AR-5 (Autonomy) | Plane 0 (governance) + Plane 3's autonomy-level gate (§9) |
| RR-1–RR-9 (Risk) | Plane 3, architecturally isolated from Plane 2 and from self-improvement (§9, §6) |
| SF-1–SF-10 (Safety/failure) | §13, mapped mechanism-by-mechanism |
| PR-1–PR-9 (Performance) | Plane 4 / Research harness (§11), with thresholds remaining operator/TBD per Stage 1 |
| DR-1–DR-8 (Data) | Plane 1 (§7) |
| ER-1–ER-8 (Evaluation) | Research & Backtesting environment (§11) |
| REG-1–REG-8 (Regulatory) | Execution gate (§10), Plane 0 configuration, DR-6 monitoring |
| DOC-1–DOC-7 (Documentation) | §15 versioning discipline; this document itself follows DOC-1–DOC-5's format |

No requirement was found to lack an architectural home; no architectural component was introduced without a requirement or Stage 0 finding justifying it (Principle 1 self-check).

---

## 23. Build readiness

**Are we ready to enter Stage 3 — Detailed Technical Design?**

**Yes, with five specific, narrow gaps carried forward as inputs to Stage 3 rather than blockers to starting it** (listed in §21). None of these gaps prevent Stage 3 from beginning: Stage 3's own work (concrete component design, interface schemas, the deterministic baseline strategy's specific rules, provider/broker shortlist evaluation) is precisely where §21's items 1, 2, and 4 get resolved through design work, not further Stage-0-style research. Items 3 and 5 are operator decisions that can be made in parallel with Stage 3 rather than sequentially before it.

The architecture is deliberately conservative relative to the project's north-star ambition (fully autonomous, self-improving, capital-deploying system) — this is intentional, not a hedge: Stage 0's evidence base supports building the boring, auditable, evidence-gated core first and earning additional sophistication through the Research environment's own results, not assuming that sophistication upfront. Nothing in this architecture forecloses eventually reaching the north-star system; it defines the path there as a series of evidence-gated promotions rather than a single upfront design leap.

---

*This document proposes an architecture. It does not write implementation code, select a final broker, finalize numeric thresholds, or commit to a specific Plane 2 v2+ design beyond what's justified by current evidence. Those belong to Stage 3 — Detailed Technical Design.*
