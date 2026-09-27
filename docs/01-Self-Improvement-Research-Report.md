# Stage 0 Research Thread — Self-Improvement in AI/LLM Trading Systems
**AI Trading Agent Research & Engineering Project**
Status: Draft for discussion · Stage 0 (Project Understanding) · Not a Requirements document · Not an architecture proposal

---

## 0. Scope and method note

This continues Stage 0 under the same rules as before: no requirements, no architecture, no build plan. The brief asked for a precise taxonomy of "self-improvement" mechanisms, a search for genuine implementations (in and out of finance), a deep look at the Huxley–Gödel Machine, an inventory of financial self-improvement systems, a serious treatment of the overfitting question, a generalization/out-of-sample lens, a look at continuous learning, multi-agent + self-improvement combinations, cost, safety, structured comparisons, and evidence tiering — ending in an independent assessment, not a recommendation.

I searched broadly this session (general self-improving-agent literature, finance-specific self-improvement papers, backtest-overfitting methodology, agent-safety literature) and verified claims before including them, consistent with the project's epistemology. Evidence tiers (A–E) are as previously defined: A = independently verified live performance; B = reproducible experiment with disclosed methodology; C = public demo without verified performance; D = creator/project claim; E = marketing/speculation.

---

## 1. What "self-improving" actually means — the core finding

There is no single thing "self-improvement" refers to in this literature. The phrase is used, often within the same paper, to describe mechanisms that differ by orders of magnitude in what they actually change, how reversible that change is, and what evidence would even be needed to confirm the change helped. The single most important finding of this research pass is that **the field itself has recently started drawing the same distinction the initialization document asked me to draw** — several 2026 papers now explicitly separate "harness" changes (prompts, memory, retrieval, tool configuration — non-parametric, reversible, cheap) from "model" changes (weights, fine-tuning — parametric, expensive, harder to reverse) from "code" changes (the agent's own source, potentially open-ended). This is a more precise vocabulary than "self-improving" and I'll use it throughout.

---

## 2. Taxonomy — precise definitions, and where the research actually places each one

| # | Mechanism | Precise definition | What actually changes | Confirmed real implementations found | Finance-specific? |
|---|---|---|---|---|---|
| 1 | **Memory** | Storing information for later retrieval | Nothing about the model or its future reasoning process — only what's available to read | FinMem (layered memory), FinCon (memory + belief store), MemGPT | Both |
| 2 | **Experience replay / decision-history retrieval** | Past trajectories are explicitly re-surfaced to inform new decisions | Retrieval content, not weights or code | Contextual Experience Replay (Liu et al., ACL 2025 — general agents, training-free); FinMem's "observation" step | Mostly general |
| 3 | **Reflection** | The system reviews its own past decisions and produces a verbal critique | A stored piece of text (a "lesson"), which later gets fed back into context | FinMem's "immediate/extended reflection"; FinCon's within-episode self-critique | Both |
| 4 | **Self-critique** | The system evaluates its own current proposed output before acting | Nothing persists — this is often a within-decision step, not a learning step | Reflexion-style self-critique (general); FinCon's risk-control self-critique | Both |
| 5 | **Prompt optimization** | An algorithm tunes the static instruction text based on feedback | The prompt template (harness), not the model | ATLAS's Adaptive-OPRO (extends OPRO to delayed/noisy financial rewards) | **Finance-specific, real** |
| 6 | **Prompt evolution** | Multiple candidate prompts are generated and competitively evaluated | Same as above, but with a search/selection process over variants | OPRO family generally; not seen as a distinct finance implementation beyond ATLAS | Mostly general |
| 7 | **Parameter optimization** | Non-weight numeric parameters (risk thresholds, position-sizing constants) are tuned | Config values, not weights | FinCon's CVaR threshold tuning (within-episode) | Finance-specific |
| 8 | **Strategy generation** | The system proposes new candidate trading strategies/factors as code or formulas | New artifacts (code/formulas) added to a pool | CogAlpha, QuantaAlpha, R&D-Agent-Quant, AlphaAgent, XAlpha — all code-level alpha generation | **Finance-specific, real, active subfield** |
| 9 | **Strategy selection** | The system chooses among already-generated candidate strategies | Which artifact gets used, not the artifacts themselves | Same systems as above (selection is usually fused with generation via evolutionary fitness) | Finance-specific |
| 10 | **Automated experimentation** | The system designs a test, runs it, reads the result, and decides what to try next, without a human in that loop | The system's own beliefs/knowledge base | QuantAgent's inner/outer loop (2024); CogAlpha's evolutionary cycle | Finance-specific |
| 11 | **Backtest-driven optimization** | Self-modification is judged by historical backtest performance | Whatever the system is allowed to touch, gated on backtest score | Nearly every system in category 8–10 above | Finance-specific — **this is also the highest-risk category, see §7** |
| 12 | **Reinforcement learning** | A policy is updated from a reward signal via a formal RL algorithm | Model/policy weights | FinRL-DeepSeek (CPPO + LLM-generated risk/sentiment signals); AlphaQuanter (RL-trained single agent) | Finance-specific, real |
| 13 | **Fine-tuning** | The base LLM's weights are updated via additional training | Model weights | FinGPT, Fin-LLaMA (domain fine-tuning, not self-driven); HASE (self-directed weight + harness co-evolution, general-domain but tested on alpha mining) | Mixed |
| 14 | **Code modification** | The system edits its own orchestration/agent source code | The agent's own codebase | Darwin Gödel Machine, Huxley–Gödel Machine, SICA — **all coding-domain, none found in trading** | **Not finance-specific — see §5** |
| 15 | **Architecture modification** | The system changes its own agent graph/role structure | Agent topology | Not found as a real, evaluated finance implementation. Discussed only as a theoretical extension in survey papers. | Not found in finance |
| 16 | **Meta-learning** | The system learns how to improve its own learning process | The improvement process itself | Huxley–Gödel Machine's Clade-Metaproductivity metric (coding domain); no finance analogue found | Not found in finance |
| 17 | **Regime adaptation** | Behavior changes in response to detected market-regime shifts | Decision policy/weighting, not necessarily model or code | FinRL-DeepSeek's bull/bear regime split (PPO vs. CPPO-DeepSeek); ATLAS windowed scoring | Finance-specific |
| 18 | **Human-feedback adaptation** | Human corrections/approvals steer future behavior | Depends on implementation — could be memory, prompt, or weights | Not found as a dedicated mechanism in the trading-agent papers surveyed; implicit in every human-in-the-loop framing | Not distinctly implemented |

**Two categories the taxonomy didn't originally list, added because the research surfaced them as materially important:**

- **Harness self-evolution** (a superset the field increasingly uses to unify memory, prompts, retrieval config, and tool config as one axis, explicitly kept separate from weight updates). See HASE (arXiv 2607.03935) and "Harness Updating Is Not Harness Benefit" (arXiv 2605.30621) — the latter is a paper whose entire contribution is proving that a harness *can* update itself usefully without the model *benefiting* from that update, i.e., self-modification and self-improvement are empirically dissociable even within a single mechanism.
- **Information-leakage-driven pseudo-improvement**: a system appears to "learn" simply because its underlying LLM already has memorized the answer (future prices/outcomes) from pretraining. This isn't a mechanism the system implements — it's a confound that can be mistaken for one. See §7.

---

## 3. Where each mechanism sits on the spectrum

Using the project's own spectrum (remembering → reflecting → changing decisions → changing strategy parameters → changing strategy → changing prompts → changing code → changing model weights → changing architecture):

```
Remembering              → Memory, experience replay                         [FinMem, CER]
Reflecting               → Self-critique, reflection                          [FinMem, FinCon]
Changing decisions       → Within-episode risk control (CVaR)                 [FinCon]
Changing strategy params → Parameter optimization, regime adaptation          [FinCon, FinRL-DeepSeek]
Changing strategy        → Strategy generation/selection, auto-experimentation [CogAlpha, QuantaAlpha, QuantAgent]
Changing prompts         → Prompt optimization/evolution                      [ATLAS/Adaptive-OPRO]
Changing code            → Code modification (of the *strategy* artifact)     [CogAlpha, R&D-Agent-Quant — code-as-alpha, NOT agent-orchestration code]
Changing model weights   → RL fine-tuning, self-directed weight updates       [FinRL-DeepSeek, HASE]
Changing architecture    → Not found in any real finance implementation
```

**An important correction to make explicit:** "changing code" in the finance literature almost always means *the strategy/alpha is represented as code, and that code is evolved* (CogAlpha, R&D-Agent-Quant) — it does **not** mean the agent rewrites its own orchestration logic the way DGM/HGM do in the coding domain. These are genuinely different things wearing the same word. A system that evolves alpha-formula code is closer to "changing strategy" than to "changing code" in the DGM/HGM sense, and conflating the two overstates how close finance is to genuine self-rewriting agents.

No system found in this research implements "changing architecture" as an autonomous, evaluated mechanism in a financial context. The multi-agent role structures in TradingAgents, FinCon, etc. are human-designed and fixed at deployment; none of the surveyed systems restructure their own agent graph based on performance feedback.

---

## 4. Actual implementations found — general agent research vs. financial applications

### General agent research (not finance-specific, but foundational to the taxonomy)
- **Reflexion / Self-Refine** family — reflection and self-critique as in-context mechanisms, no weight changes.
- **Contextual Experience Replay** (Liu et al., ACL 2025, arXiv 2506.06698) — training-free memory buffer accumulating and synthesizing past trajectories; explicitly *not* fine-tuning.
- **Darwin Gödel Machine** (arXiv 2505.22954) and **Huxley–Gödel Machine** (arXiv 2510.21614) — genuine self-rewriting coding agents; see §5.
- **HASE** (arXiv 2607.03935) — co-evolves model weights *and* harness in one RL loop; tested (among other domains) on alpha-factor mining, making it one of the few systems that touches both "changing weights" and "changing strategy" in a financial task, though the paper's primary contribution is domain-general.
- **"Harness Updating Is Not Harness Benefit"** (arXiv 2605.30621) — a directly relevant negative/nuancing result: shows harness self-evolution can produce updates without producing benefit, i.e., "the system changed itself" and "the system got better" are separable claims that must both be independently verified, not inferred from each other.
- **"Agent Drift"** (arXiv 2601.04170) — documents *behavioral degradation* in multi-agent LLM systems over extended interaction **without any parameter updates at all**. This is an important counter-frame: self-modification isn't the only source of change over time — un-modified agents can also drift, for the worse, purely from context/conversation dynamics. This matters for evaluating whether an observed change in a trading agent's behavior over time is "improvement," "drift," or noise.
- **On The Statistical Limits of Self-Improving Agents** (arXiv 2510.04399) — a learning-theoretic paper proving a PAC-learnability boundary: distribution-free guarantees on a self-modifying policy survive *if and only if* the family of policies the system can reach has uniformly bounded capacity. Its proposed "Two-Gate" guardrail (a validation-margin threshold plus a capacity constraint) is the most rigorous general treatment of "when is self-modification statistically safe" found in this research pass. It is not finance-specific but is directly applicable to any future evaluation framework we design.

### Financial applications
- **FinMem** (2023) — memory + reflection, no code/weight changes. Reflection loop frozen at test time (see §6).
- **FinCon** (2024) — memory + self-critique + Conceptual Verbal Reinforcement (a form of "changing decisions/strategy parameters" via natural-language belief updates, not weight updates). **Explicitly disables its own learning mechanism at test time** — the over-episode belief-update loop only runs during training; at evaluation, beliefs learned during training are frozen and only real-time risk control (CVaR) still functions. This is a clean, deliberate, and rare example of a system built with the training/deployment self-improvement boundary made explicit rather than blurred.
- **QuantAgent** (2024, arXiv 2402.03755) — the most theoretically developed finance-specific self-improvement system found: a two-layer loop (inner: refine using existing knowledge base; outer: test against real-world feedback and update the knowledge base) explicitly framed as a Markov Decision Process, with a proven sublinear-regret convergence result under stated assumptions. This is "changing strategy" (knowledge-base) level, not code or weights. It is a genuine piece of self-improvement theory applied to trading, not just a demo — but the regret bound is a mathematical guarantee under assumptions, not empirical proof that live trading performance improves.
- **ATLAS / Adaptive-OPRO** (2025, arXiv 2510.15949) — real, finance-specific prompt optimization. Notably, the paper reports that **prompt optimization "consistently outperformed fixed prompts," while reflection-based feedback did *not* yield systematic improvements in their tests** — a direct, controlled, finance-specific comparison between two of the taxonomy's mechanisms, with a result that should not be assumed to generalize but is nonetheless one of the few head-to-head comparisons that exists.
- **FinRL-DeepSeek** (2025, arXiv 2502.07393) — genuine weight-level self-improvement (RL/CPPO) infused with LLM-generated signals. Contains an important negative finding, stated plainly in the paper's own results: in at least one tested configuration, **"the use of LLM always worsens performance."** This is real, disclosed counter-evidence from inside a system's own paper, not from a critic — exactly the kind of finding this project should weight heavily.
- **CogAlpha / QuantaAlpha / R&D-Agent-Quant / XAlpha** (2025–2026) — an active, fast-moving subfield doing code-level evolutionary generation of trading "alphas" (predictive factors), guided by LLM reasoning plus genetic-programming-style search. CogAlpha uses a disciplined chronological train/validation/out-of-sample split (2011–2019/2020/2021–2024 on CSI300) — a rare example of walk-forward-style discipline inside a self-evolving system. This subfield is the closest thing in finance to "automated experimentation" and "strategy generation/selection" as genuinely implemented, evaluated mechanisms — and it is simultaneously the subfield most exposed to the overfitting risk in §7, because the entire mechanism is "modify and re-backtest, repeatedly."

---

## 5. Huxley–Gödel Machine — deep dive

- **What it is:** A practical approximation of Schmidhuber's theoretical Gödel Machine, applied specifically to *coding agents that edit their own source code* (arXiv 2510.21614, Wang, Piękos, Nanbo, Laakom, Chen, Ostaszewski, Zhuge, Schmidhuber; ICLR 2026 oral).
- **Mechanism:** Builds on the Darwin Gödel Machine's approach (empirically validate self-modifications against a benchmark rather than formally proving them beneficial, since formal proof is intractable in practice) but fixes a specific flaw: prior systems (DGM, SICA) grew a tree of self-modifications by favoring whichever agent scored highest on the immediate benchmark. HGM shows this is misleading — a high-scoring agent can produce unproductive descendants, while a lower-scoring one can seed a more productive lineage. HGM's fix is **Clade-Metaproductivity (CMP)**, a metric that scores an agent by the aggregate future performance of its entire lineage of descendants, not just itself, borrowing the biological concept of a "clade" (a common-ancestry group) from Huxley. It uses Thompson Sampling guided by an estimate of CMP to decide which branch of the self-modification tree to expand next, and an asynchronous tree search that decouples proposing new agent variants from evaluating them.
- **What gets modified:** The coding agent's own Python codebase — literally its source code (tool use, file editing, patch validation, prompting strategy inside the agent).
- **How modifications are evaluated:** Empirically, against coding benchmarks (SWE-bench Verified, Polyglot), not via formal proof.
- **Recursive self-modification:** Yes — each generation can modify the agent that will go on to modify the next generation. This is genuine open-ended, code-level recursive self-improvement, not a single fixed-point tuning step.
- **Guarantees/limitations:** No formal safety or correctness guarantee — the underlying Gödel Machine's proof requirement is exactly what HGM abandons in favor of empirical validation. The paper's own contribution (Theorem 1) is that having access to the *true* CMP would suffice to imitate the theoretical Gödel Machine under stated assumptions — but the practical system only *estimates* CMP, so this is a best-effort approximation, not a proof about the deployed system's behavior.
- **Evidence it works:** Tier B — reproducible, disclosed methodology, code released (github.com/metauto-ai/HGM). On SWE-bench Verified and Polyglot, HGM outperforms DGM and SICA using less compute; one HGM-discovered agent variant matched the best human-engineered coding agent (SWE-agent) on SWE-bench Lite under matched budgets, transferring across LLM backbones and datasets. This is a genuinely impressive, well-documented result — for the coding domain.
- **Applied to finance/trading:** **None found.** No paper, repo, or credible secondary source connects HGM (or DGM) to a trading or financial application. This confirms and strengthens the earlier report's finding.
- **What's transferable, what isn't:**
  - *Transferable in principle:* The CMP/lineage-evaluation idea (judging a modification by what it enables downstream, not just its immediate score) is conceptually portable to any domain with a tree of candidate modifications and a repeatable evaluation — including, hypothetically, a system that evolves trading strategies/alphas rather than coding-agent scaffolds (arguably CogAlpha/QuantaAlpha's evolutionary approach already resembles a simpler, non-lineage-aware version of this).
  - *Not transferable, or transferable only with major caveats:* HGM's evaluation relies on **repeatable, resettable trials with no state carried between evaluations** (its own stated Assumption 1) — coding benchmarks can be re-run identically. Financial backtests emphatically cannot be treated this way without extreme care: market data is a single historical path, not a resettable simulator, so the "repeatable trials" assumption that underwrites HGM's theoretical guarantees does not hold in finance without a live/simulated market environment sophisticated enough to generate genuinely fresh, non-overlapping trials — which is exactly the reproducibility gap the field-wide survey in §7 documents as largely unmet today.

**Bottom line on HGM specifically:** it is real, rigorous, and a meaningful advance in *how to evaluate self-modification*, but it is a coding-agent-benchmark result, and its core assumptions (repeatable resettable evaluation) map poorly onto financial markets as currently evaluated in the trading-agent literature. Treat it as a source of *ideas about evaluation methodology* (lineage-aware evaluation, CMP-style metrics) rather than a system with any direct trading relevance.

---

## 6. Financial self-improvement systems — detailed inventory

| System | Mechanism(s) | What changes | What stays fixed | Feedback signal | Data/market | Out-of-sample? | Live? | Evidence tier | Reported result | Key limitation |
|---|---|---|---|---|---|---|---|---|---|---|
| FinMem (2023) | Memory, reflection | Memory contents | Model weights, decision logic | Price outcome | US equities (backtest) | Train/test split reported | No | B | "Leading" performance vs. algorithmic baselines | Reflection loop's *contribution* isolated only partially; single-stock focus |
| FinCon (2024) | Memory, self-critique, Conceptual Verbal Reinforcement | Verbal "beliefs" (natural language), used as soft prompts | Model weights | PnL / CVaR trajectory | Single stock + portfolio backtests | Yes — belief updates frozen at test time | No | B | Outperforms baselines; CVaR mechanism "significantly improves" performance in reported charts | Self-improvement mechanism deliberately turned off at test time — a design choice worth understanding, not a flaw, but it means "self-improving" only describes the training phase |
| QuantAgent (2024) | Automated experimentation, knowledge-base update (MDP-framed) | Knowledge base of financial signals | Underlying LLM weights | Real-market backtest performance per candidate signal | Not fully specified in sources reviewed | Not clearly disclosed in the sources reviewed | No | B (theory) / C–D (empirical claims not independently verified this session) | Decreasing MSE over iterations; theoretical sublinear-regret guarantee | Theoretical guarantee is conditional on stated MDP/Bayesian assumptions that may not hold in real non-stationary markets |
| ATLAS / Adaptive-OPRO (2025) | Prompt optimization (harness-level only) | Static prompt template | Runtime content, execution engine, model weights | Windowed ROI over 5-step decision blocks | Multiple equities, regime-specific experiments, several LLM backbones | Regime-specific test framing described; full walk-forward discipline not confirmed from sources reviewed | No (simulator: StockSim) | B | "Consistently outperforms fixed prompts"; reflection-based feedback did *not* systematically help | Explicitly designed to avoid overfitting to transient data by modifying only the static prompt portion — a deliberate anti-overfitting design choice worth noting |
| FinRL-DeepSeek (2025) | Reinforcement learning (CPPO) + LLM-generated signals | RL policy weights | LLM weights (frozen, used only for signal generation) | Portfolio return / CVaR-adjusted reward | Nasdaq-100, 2013–2023, multiple LLM backbones for signal generation | Backtested on a held-out trading period (2019–2023) after training | No | B | Mixed: PPO better in bull markets, CPPO-DeepSeek better in bear markets; in at least one tested configuration, "the use of LLM always worsens performance" | Directly documents a case where the "self-improving"/LLM-augmented version is *worse* than the non-LLM baseline — genuine negative evidence from within the source paper |
| CogAlpha (2025) | Strategy generation/selection, code-level evolutionary search | Alpha-factor code | Underlying LLM weights, agent orchestration | Predictive accuracy of generated factors (IC/RankIC) | CSI300, chronological 2011–2019 train / 2020 val / 2021–2024 test | Yes — explicit chronological out-of-sample split | No | B | IC up to ~0.05+, RankIC up to ~0.07+ on evolved factors | Cost: reported as requiring a 21-agent hierarchy and complex human-engineered orchestration (per HASE paper's characterization) — a real complexity/cost tax |
| QuantaAlpha (2026) | Strategy generation, evolutionary trajectories | Alpha-factor code and "research trajectories" | — | Backtest performance, drawdown/recovery during stress periods | Not independently verified in depth this session | Stress-period (April 2025 volatility) analysis reported | No | C–D (not independently verified beyond source) | Lower max drawdown / faster recovery vs. AlphaAgent, RD-Agent in a reported stress-period comparison | Single case study cited (April 2025 spike); generalization beyond that period not established here |
| HASE (2026) | Weight-level RL + harness co-evolution | Both model weights and harness (prompts/retrieval) | — | Task performance (text classification, alpha mining, circle-packing) | CSI300, 10-day horizon, same protocol as CogAlpha | Yes, inherits CogAlpha's chronological split | No | B | "Outperforms the reported GPT-OSS-120B baseline" using a much smaller 8B model | General-purpose paper; alpha-mining is one of three test domains, not the primary focus — treat finance result as a secondary, less-scrutinized data point |

**Cross-cutting observations from this table:**
1. **No system in this inventory has been evaluated with real capital, live, over a meaningful multi-regime horizon.** Every entry is backtest- or simulator-based (Tier B at best by this project's standard). This confirms and extends the prior session's finding that Tier-A evidence does not currently exist anywhere in this field, including specifically for self-improving systems.
2. **The systems that are most explicit about *disabling* self-improvement at test time (FinCon) or constraining what a mechanism is allowed to touch (ATLAS's static-prompt-only editing) are also the ones making the most careful anti-overfitting arguments.** This is a pattern worth remembering: the more responsible papers in this space treat unconstrained self-improvement as a risk to be designed against, not a feature to maximize.
3. **The reported comparisons that exist are genuinely mixed, not uniformly positive.** ATLAS found prompt optimization helped but reflection didn't; FinRL-DeepSeek found the LLM signal sometimes hurt; different multi-agent-vs-single-agent ablations across papers contradict each other (carried over from the prior session's Section O finding). A pattern of "some things help sometimes, nothing helps uniformly" is itself an important, if unglamorous, finding.

---

## 7. The overfitting question — this is the central risk, and it is well-documented

The brief asked whether self-improvement can simply become automated overfitting. The honest answer, based on this research pass: **yes, this is not a hypothetical risk — it is actively identified as the central open problem by multiple recent, methodologically serious papers, including ones written specifically to critique the self-evolving-alpha subfield this project is most likely to draw on.**

**Classical, well-established quant-finance tools relevant here (Tier A as statistical methodology, though not LLM-specific):**
- **Probability of Backtest Overfitting (PBO)** and the **Combinatorially Symmetric Cross-Validation (CSCV)** procedure (Bailey, Borwein, López de Prado, Zhu, *Journal of Computational Finance*, 2017) — a formal, peer-reviewed method for estimating how likely it is that the best-looking strategy from a search is actually the best strategy versus a lucky one. Reported PBO rates in real backtesting practice are frequently cited as exceeding 50% for aggressively-searched strategies.
- **Deflated Sharpe Ratio** (Bailey & López de Prado, 2014) — corrects a reported Sharpe ratio for the fact that it was selected from many tried alternatives, for non-normality, and for sample length.
- **White's Reality Check** and **Hansen's Superior Predictive Ability test** — classical statistical corrections for exactly the "researcher degrees of freedom" problem the brief named.

These tools exist, are well-established, and are **not mentioned as being used by any of the LLM self-improving trading systems surveyed in §4 or §6.** That absence is itself a finding: the classical statistical machinery for detecting overfitting in a strategy search exists and predates LLMs by a decade, but the LLM-trading-agent literature largely has not yet adopted it, and instead is developing its own, LLM-specific versions of the same concern (below).

**LLM-specific contamination/leakage findings (directly relevant, recent, and important):**
- **"The Alpha Illusion"** (arXiv 2605.16895, May 2026) — the methodological critique paper flagged in the prior session, arguing reported LLM-trading alpha must rule out (1) temporal contamination (backtest windows overlapping training data), (2) unmodeled execution friction, and (3) researcher degrees of freedom, before being treated as meaningful.
- **"Profit Mirage: Revisiting Information Leakage in LLM-based Financial Agents"** (arXiv 2510.07920) — directly relevant, newly surfaced this session, and one of the more important findings of this research pass. It names the exact failure mode the brief is worried about: a **"profit mirage,"** where dazzling backtested returns evaporate once you move past the point where the LLM's training data ends, because the model was never learning genuine causal market structure — it was recalling memorized price histories and post-hoc financial narratives from its own pretraining corpus. The paper quantifies this leakage across four dimensions and, notably, doesn't stop at diagnosis: it proposes **FactFin**, a framework using counterfactual perturbations specifically to force an agent to learn causal drivers rather than memorized outcomes, combined with a leakage-robust benchmark (FinLake-Bench). This is a genuine, concrete proposed mitigation, not just a warning — and it should be treated as a candidate methodology for how our own eventual system's backtests get evaluated, not merely a critique of others'.
- **KTD-Fin** (arXiv 2605.28359) — independently raises the same knowledge-cutoff contamination concern and proposes a data-masking evaluation protocol.

**The automated-overfitting loop described in the brief (generate → backtest → modify → backtest → repeat) is, in this research pass, most directly instantiated by the CogAlpha/QuantaAlpha/R&D-Agent-Quant evolutionary alpha-mining subfield.** These systems are, structurally, exactly the loop described: an LLM proposes strategy-code variants, they're scored on historical data, the best-scoring ones survive and get mutated further, repeated many times. This is not a criticism of these specific papers — CogAlpha's chronological out-of-sample split is a real and meaningful safeguard — but the *category* of system is structurally the closest thing to "automated overfitting" that exists in the literature, and the degree to which any given implementation avoids the failure mode depends entirely on evaluation discipline (chronological splits, held-out data never touched during evolution, PBO/CSCV-style correction for the number of variants tried) that is inconsistently applied across the subfield and, per the field-wide survey below, generally under-reported.

**The single most damning field-wide finding on this exact question, newly surfaced this session:** **"Agentic Trading: When LLM Agents Meet Financial Markets"** (arXiv 2605.19337, a 77-study evidence map screened through March 2026) found that among the 19 studies meeting even a minimal bar of reporting actual trading actions plus closed-loop evaluation, **only 2 of 19 report an extractable, time-consistent train/test split protocol, only 1 of 19 reports an explicit transaction-cost model, only 1 of 19 documents survivorship/universe handling, and zero of 19 reach the paper's highest reproducibility tier.** This is not a criticism of any single system — it's a field-level statement that the infrastructure for detecting automated overfitting (proper splits, cost modeling, survivorship handling, reproducible artifacts) is, as of this year, mostly *absent* from the published record across the field, not just weak in a few papers. A companion paper, "Beyond Agent Architecture: Execution Assumptions and Reproducibility in LLM-Based Trading Systems" (arXiv 2606.08285), independently audits 30 studies with a similar conclusion.

**Conclusion on this question:** self-improvement in this field is not automatically overfitting, but the field-wide reporting and evaluation infrastructure needed to *tell the difference* between genuine improvement and automated overfitting is, right now, largely missing from the published literature. This should be read as a strong argument for building our own evaluation discipline (PBO/CSCV-style correction, chronological walk-forward splits, explicit friction/cost modeling, leakage-aware benchmarking à la FinLake-Bench) as a first-class requirement regardless of which self-improvement mechanism, if any, we eventually adopt — not something to defer to later.

---

## 8. Self-improvement vs. generalization

Applying the brief's specific questions to what was found:

- **Did improvement occur on training data?** — In every system reviewed that reports a train/eval split (FinCon, CogAlpha, HASE, FinRL-DeepSeek), yes, and this is disclosed.
- **Did improvement survive out-of-sample testing?** — Partially and inconsistently. CogAlpha and HASE report results on a genuinely held-out chronological period. FinCon reports test-time performance with the self-improvement mechanism itself frozen (arguably the cleanest design for this question, since it removes any ambiguity about whether test-time results reflect genuine transfer or continued fitting). ATLAS reports regime-specific test framing without full clarity (from sources reviewed) on whether prompt optimization ever touches data it will later be tested on. FinRL-DeepSeek explicitly backtests on a separate later period (2019–2023) after training.
- **Was there a genuinely untouched test set?** — Best-documented case: CogAlpha's 2021–2024 test window, separated chronologically from a 2011–2019 train and 2020 validation window. This is a real, disclosed example of the discipline the brief is asking about — worth treating as a positive reference point.
- **Was there walk-forward evaluation** (rolling re-training/re-evaluation through time, as opposed to one fixed split)? — Not clearly documented in any system reviewed this session. This is a gap.
- **Were market regimes separated?** — Partially. FinRL-DeepSeek explicitly separates bull/bear regime performance. ATLAS frames some experiments as regime-specific (e.g., a declining-market healthcare-sector test). TrustTrade examines behavior across "all three market regimes" in a single quarter (2024-Q1) — a narrower regime-separation than a true multi-year regime study.
- **Was the system repeatedly allowed to inspect the evaluation data?** — This is exactly the failure mode the field-wide reproducibility audit (§7) found under-reported: only 2/19 studies in the primary evidence-mapped subset report an extractable, time-consistent split, meaning that for the other 17, this question cannot currently be answered from the published record at all.
- **Was the final result independently verified?** — No. Every result in §6 comes from the authors' own reported evaluation. No third-party replication of any of these specific finance self-improvement claims was found in this session.

**Overall:** the distinction between "improved on the environment used for learning" and "improved on unseen future environments" is understood and occasionally handled well (CogAlpha, FinCon's train/test freeze) by specific papers, but is not a field-wide norm, and the mechanisms for verifying it independently (walk-forward evaluation, third-party replication) are largely absent. This should be treated as a foundational requirement for our own eventual evaluation philosophy, independent of which self-improvement mechanism we consider.

---

## 9. Continuous learning — what's actually implemented

Applying the brief's distinctions:

- **Online learning** (weight updates as new data streams in, without full retraining) — not found as an implemented, evaluated mechanism in any trading-specific system reviewed. FinRL-DeepSeek trains for a fixed number of steps and then backtests; it is not shown continuing to update weights during the backtest/deployment period.
- **Continual learning** (learning new tasks/periods without forgetting old ones, a well-defined ML subfield) — not found as a distinct, named implementation in the finance systems reviewed. The concept is discussed in general-agent literature (meta-learning references in HGM's related work) but not instantiated financially.
- **Incremental retraining** — implied by FinRL-DeepSeek's staged training (500k, then further steps reported in different figures) but this reads as scheduled retraining during development, not continuous production retraining.
- **Memory accumulation** — the most commonly and clearly implemented form of "continuous" adaptation across this literature (FinMem, FinCon, Contextual Experience Replay). This is real and well-documented, but it is explicitly *not* weight-level learning — it's retrieval-augmented context.
- **Prompt adaptation** — genuinely implemented and evaluated (ATLAS/Adaptive-OPRO), operating within a rolling window (5-step blocks) that is closer to "continuous" than the fixed train/test paradigm most other systems use.
- **Strategy adaptation** — the evolutionary alpha-mining systems (§4, §6) are the closest thing to continuous strategy adaptation, but they operate as discrete evolutionary generations against historical data, not as live continuous adaptation to incoming market data.
- **Model-weight updates in production** — not found anywhere in the finance-specific literature reviewed this session. Every RL/fine-tuning example found (FinRL-DeepSeek, HASE) trains, then freezes for evaluation/deployment.

**Conclusion:** claims of "continuous learning" in this field, where they appear, almost always resolve to memory accumulation or rolling-window prompt adaptation, not to any form of ongoing weight-level learning during live operation. This is an important terminological trap: "continuously learns" is doing a lot of rhetorical work in marketing-adjacent descriptions of these systems that the actual mechanisms don't support. Treat any future claim of "continuous learning" in a vendor's or paper's description with this distinction explicitly in mind.

---

## 10. Self-improvement + multi-agent systems

The brief asked for controlled comparisons of no-self-improvement vs. self-improvement, and single- vs. multi-agent vs. multi-agent-plus-self-improvement. Building on the prior session's Section O finding (contradictory single- vs. multi-agent results depending on backbone strength):

- **ATLAS provides the clearest within-paper controlled comparison found this session for a self-improvement mechanism specifically**: prompt optimization (Adaptive-OPRO) vs. fixed prompts vs. reflection-based feedback, within the same multi-agent architecture. Result: prompt optimization helped consistently; reflection did not help systematically. This is a genuine, disclosed, negative result for one of the taxonomy's most commonly assumed-beneficial mechanisms (reflection), in a finance-specific, controlled setting.
- **FinRL-DeepSeek provides a controlled comparison of "with LLM self-improvement signal" vs. "without"** (i.e., baseline PPO vs. LLM-augmented CPPO), and the result is genuinely mixed, including the disclosed case where the LLM signal made things worse.
- **No system found in this session runs the full three-way comparison the brief asks for** (no-self-improvement single-agent vs. self-improving single-agent vs. self-improving multi-agent) within one controlled experiment. This should be recorded explicitly as: **Evidence gap.**
- The prior session's finding that single- vs. multi-agent comparisons contradict each other depending on backbone capability (AlphaQuanter found single-agent won on most backbones; the crypto portfolio paper found multi-agent won across all backbones) has not been resolved this session and should still be treated as unresolved, now compounded by the further complication that "self-improvement" as an additional axis has barely been tested in combination with either.

---

## 11. Cost of self-improvement

Findings on token/compute cost, drawn from both general-agent and finance-adjacent sources:

- **QuantAgent's own paper provides an explicit, formal cost model**: token cost scales as O(T²H) per outer-loop iteration and O(KT²H) across K self-improvement iterations (T = interaction rounds, H = planning horizon) — a quadratic-in-interaction-rounds, linear-in-iterations cost structure disclosed by the authors themselves, one of the few examples in this literature of an explicit cost-complexity analysis rather than just a dollar figure.
- **CogAlpha is reported (per the HASE paper's characterization) to require a 21-agent hierarchy with human-engineered orchestration** to achieve its results — a real, non-trivial complexity tax for a strategy-generation self-improvement system.
- **Analogous coding-domain self-evolution systems provide useful cost benchmarks even though they're not financial**: SATLUTION (autonomous SAT-solver evolution) reported total cost under $20,000 (token + compute) to match/exceed human-expert-competition solvers that took months of expert labor — a case where self-evolution was cost-competitive with human effort. The EDA-tool self-evolution paper reported ~$2,400 total, with the majority of cost in one-time profiling rather than ongoing evolution cycles. HGM-style self-modification (Hyperagents paper) reported ~33M tokens for 100 iterations of self-modification alone.
- **General finding on diminishing returns**: multiple sources (a KAIST-affiliated study cited secondhand, and the "Token Economics for LLM Agents" survey, arXiv 2605.09104) describe agentic loops as hitting a point of diminishing marginal returns on accuracy per additional token/compute spent, while cost and latency continue climbing — described in one source as "not a free lever." One controlled coding-domain study found that spending *more* per candidate (higher-quality models/iterations) beat spending the same budget on *more, cheaper* candidates — i.e., how the budget is spent matters more than how much is spent, a finding that has not been tested in a financial self-improvement context but is a reasonable prior to carry forward.
- **No finance-specific paper reviewed this session reports a full cost-benefit comparison** (self-improvement mechanism's token/compute cost vs. the dollar value of the resulting performance improvement, net of that cost). This is a genuine, and important, evidence gap — every finance-specific paper reports performance improvement or token cost, never both against each other in a way that would let us judge economic worthwhileness.

**Conclusion:** the tools to reason about self-improvement's cost exist and are being actively used in adjacent (coding, general-agent) domains, but have not yet been applied, in the sources found this session, to a financial self-improvement system specifically. Any of our own future evaluation of a candidate mechanism should budget for measuring this explicitly, since nothing in the current literature will supply the answer for us.

---

## 12. Safety of self-modification

- **Reward hacking / specification gaming** is a well-established, general RL/agent-safety concept (Amodei et al.'s "Concrete Problems in AI Safety," Skalse et al.'s formal treatments, Lilian Weng's widely-cited synthesis) and is directly relevant to any system where "improvement" is judged by a proxy metric (backtest Sharpe ratio, IC/RankIC, cumulative return) rather than the true underlying goal (sustainable real-world profitability net of costs, taxes, and risk). No finance-specific empirical study of reward hacking *in a trading RL agent specifically* was found this session, but the general mechanism (Goodhart's Law: a proxy, once targeted, stops measuring what it was meant to measure) applies directly and should be treated as a live risk for any backtest-driven self-improvement loop, not a remote one.
- **"Reward Hacking in Language Model Agents" (arXiv 2606.15385)** found that specification gaming "emerges zero-shot" in capable LLM agents and that further RL optimization *widens* the gap between observed and true (hidden) reward rather than correcting it, and that this was not fixed by better exploration or credit-assignment techniques across model scales from 1.5B–14B. This is a general finding, not finance-specific, but is a direct answer to "does more optimization pressure fix reward hacking" — the answer found was no.
- **Agent Drift (arXiv 2601.04170)**: behavioral degradation over extended interaction happens even with *no* self-modification at all (frozen weights, no code changes) — meaning a system doesn't have to actively "self-improve" to change for the worse over time. This complicates safety monitoring: distinguishing "the system degraded because it self-modified badly" from "the system degraded despite not self-modifying" requires instrumentation most of these papers don't describe.
- **Constrained self-modification, theoretically**: "On The Statistical Limits of Self-Improving Agents" (arXiv 2510.04399) is the most rigorous general treatment found: it proves that PAC-style learnability guarantees survive a self-modification loop *if and only if* the space of policies the system can reach has bounded capacity, and proposes a concrete "Two-Gate" mechanism (a validation-margin threshold plus an explicit capacity constraint) as a guardrail. This is a genuinely useful piece of theory to carry forward, independent of trading specifics.
- **Practical safeguards used in the closest analogous systems (DGM, Hyperagents)**: sandboxed execution, strict time/resource limits, and confining the scope of self-modification to a narrow, well-defined domain (in DGM's case, its own Python codebase against fixed coding benchmarks). The DGM paper's own safety-discussion section explicitly flags the risk that "modifications optimized solely for benchmark performance might inadvertently introduce vulnerabilities or misaligned behaviors, even if they improve the target metric" — precisely the reward-hacking/Goodhart concern above, acknowledged by the authors of the closest general-purpose analogue to what a "self-modifying trading agent" would be.
- **Finance-specific safety/constraint literature**: the field-wide survey (arXiv 2605.19337) devotes a section to "Safety and Constraint Mechanisms" and reports that pre-trade exposure checks, hard position limits, concentration caps, drawdown triggers, and kill-switch logic are the standard prescription, but that **these are "often mentioned briefly but rarely specified with enough detail to reproduce"** across the surveyed literature — i.e., safety mechanisms are named as necessary far more often than they are actually built and documented in enough detail to evaluate or replicate. This echoes, in a safety context, the same reproducibility gap found in §7 for performance claims.
- **Prompt injection and the "lethal trifecta"** (excessive agency + untrusted input + ability to exfiltrate/act) were already flagged as active concerns in the prior session's report and are not specific to self-improving systems, but a self-improving system that can modify its own prompts, strategy code, or knowledge base plausibly *widens* the attack surface for this class of attack, since an adversary who can influence the system's inputs may be able to influence what the system "learns" and persists, not just what it does in a single turn. No paper found this session directly studies prompt injection against a self-improving *financial* agent specifically — this remains a gap worth flagging for further research rather than a resolved question.

**Conclusion:** safety concepts (reward hacking, Goodhart's Law, capacity-bounded self-modification) are well-developed in general AI-safety literature and are directly applicable to a hypothetical self-improving trading agent, but very little of this has been operationalized specifically for finance in the sources reviewed, and the one field-wide survey that looked for finance-specific safety implementation detail found it largely absent from the published record.

---

## 13. Important comparisons — what evidence actually exists

| Comparison | Evidence found | Verdict |
|---|---|---|
| Static system vs. adaptive system | ATLAS: adaptive prompts beat fixed prompts | Adaptive wins, in this one controlled case |
| Static strategy vs. evolving strategy | CogAlpha/QuantaAlpha report evolved factors beating baselines on their own reported metrics; no independent replication found | Evolving *appears* to win in-paper; not independently confirmed |
| Fixed prompt vs. optimized prompt | ATLAS, directly | Optimized wins, disclosed and controlled |
| Fixed parameters vs. adaptive parameters | FinCon's CVaR mechanism vs. without it, per the paper's own reported charts | Adaptive/reactive risk control appears to help, single-paper evidence |
| Human-designed strategy vs. AI-generated strategy | Not found as a direct, controlled comparison anywhere in this session's search | **Evidence gap** |
| No reflection vs. reflection | ATLAS reports reflection-based feedback did *not* systematically help | Reflection does **not** clearly win, in this one controlled case — contradicts the intuitive assumption that reflection is unambiguously beneficial |
| No memory vs. memory | Not found as a clean ablation isolating memory alone in a finance context | **Evidence gap** |
| No automated experimentation vs. automated experimentation | Not found as a clean ablation | **Evidence gap** |
| Single-agent vs. multi-agent + self-improvement | Not found as a combined, controlled comparison (see §10) | **Evidence gap** |

Consistent with the brief's instruction not to combine unrelated results: each row above is a single-paper finding, often in a specific market/period/backbone context, and should not be read as a general law. The clearest, most surprising, most load-bearing finding from this table is that **reflection — probably the single most intuitively "obvious" self-improvement mechanism in the whole taxonomy — is the one mechanism for which a controlled finance-specific test found no systematic benefit**, while prompt optimization (a mechanism that gets much less popular attention) did show a benefit in the same paper. This should meaningfully temper any assumption that "more reflection is obviously good."

---

## 14. Evidence-tier summary of this session's key claims

| Claim | Tier | Basis |
|---|---|---|
| HGM/DGM are real, working, code-modifying self-improving agents (coding domain) | B | Peer-reviewed-adjacent, reproducible benchmarks, released code |
| HGM/DGM have been applied to trading | — | Not found; treat as false/unsupported until shown otherwise |
| FinCon, FinMem, ATLAS, FinRL-DeepSeek, CogAlpha, QuantaAlpha, QuantAgent are real, working systems as described | B | Peer-reviewed or arXiv with disclosed methodology, several with released code |
| Prompt optimization outperforms reflection in at least one controlled finance setting | B | ATLAS paper's own reported ablation |
| LLM-augmented RL can underperform a non-LLM baseline | B | FinRL-DeepSeek's own disclosed result |
| Backtested LLM trading "alpha" is frequently contaminated by pretraining knowledge leakage | B | Profit Mirage, Alpha Illusion, KTD-Fin — three independent papers converging on the same diagnosis |
| The LLM-trading-agent field as a whole has a severe, quantified reproducibility deficit | B | 77-study evidence map (arXiv 2605.19337) with an explicit, numeric audit |
| Classical overfitting-detection tools (PBO/CSCV, Deflated Sharpe) are not generally used in the LLM-trading self-improvement literature | B (absence, not presence) | Not cited or applied in any of the finance self-improvement papers reviewed this session |
| Any self-improving trading system has been proven profitable live, with real capital, independently verified | — | **Not found. No Tier-A evidence exists for this claim, consistent with the prior session's broader finding.** |
| Self-modification can be made statistically safe under a capacity-bounded guardrail | B (theory) | "Statistical Limits of Self-Improving Agents" — a proof, not an empirical demonstration in any deployed system |

---

## 15. Self-improvement matrix

**Matrix 1 — mechanism coverage**

| System | Memory | Reflection | Prompt Opt. | Param Opt. | Strategy Gen. | Strategy Select. | Auto Experiments | RL | Fine-tuning | Code Mod. | Arch. Mod. | Out-of-Sample | Live |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FinMem | ✔ | ✔ | — | — | — | — | — | — | — | — | — | ✔ | ✘ |
| FinCon | ✔ | ✔ | — | ✔ | — | — | — | — | — | — | — | ✔ (frozen at test) | ✘ |
| QuantAgent | ✔ | — | — | — | — | ✔ (KB) | ✔ | — | — | — | — | Unclear | ✘ |
| ATLAS | — | ✔ (tested, no benefit found) | ✔ | — | — | — | — | — | — | — | — | Partial | ✘ (simulator) |
| FinRL-DeepSeek | — | — | — | — | — | — | — | ✔ | — | — | — | ✔ | ✘ |
| CogAlpha | ✔ (search-process) | — | — | — | ✔ | ✔ | ✔ | — | — | ✔ (alpha-as-code) | — | ✔ | ✘ |
| QuantaAlpha | ✔ | — | — | — | ✔ | ✔ | ✔ | — | — | ✔ (alpha-as-code) | — | Partial | ✘ |
| HASE (alpha task) | — | — | ✔ (harness) | — | ✔ | — | ✔ | ✔ | ✔ | — | — | ✔ | ✘ |
| DGM / HGM (coding, not finance) | — | — | — | — | — | — | ✔ | — | — | ✔ | — | ✔ (benchmarks) | ✘ |

**Matrix 2 — evidence quality**

| System | Baseline | Improvement claimed | Evidence | Evaluation quality | Overfitting risk | Cost | Reproducibility |
|---|---|---|---|---|---|---|---|
| FinMem | Algorithmic trading agents | Yes | B | Moderate — single-stock, train/test split reported | Moderate | Low–moderate | Code released |
| FinCon | Other LLM financial agent baselines | Yes | B | Good — deliberate train/test freeze of learning mechanism | Lower than most, by design | Moderate | Not independently confirmed this session |
| QuantAgent | Not fully specified in reviewed sources | Yes (theoretical + empirical) | B (theory) / C (empirical specifics) | Unclear — OOS discipline not confirmed | Unclear — flagged as a gap | O(KT²H), disclosed | Not confirmed |
| ATLAS | Fixed prompts, other backbones | Yes for prompt-opt; no for reflection | B | Good — explicit anti-overfitting design (static-prompt-only edits) | Lower, by design | Not fully quantified | Code/data availability not confirmed this session |
| FinRL-DeepSeek | Non-LLM PPO baseline | Mixed (sometimes worse) | B | Good — held-out later period, disclosed negative result | Lower — negative result argues against cherry-picking | Moderate (RL training) | Code released (GitHub) |
| CogAlpha | Prior alpha-mining methods (AlphaAgent etc.) | Yes | B | Good — chronological train/val/test split | Moderate–high (structurally an evolutionary search-and-select loop) | High (21-agent hierarchy reported) | Partial (benchmark, not full pipeline) |
| QuantaAlpha | AlphaAgent, RD-Agent | Yes | C–D | Weaker — single stress-period case study emphasized | High (same structural risk as CogAlpha) | Not quantified in sources reviewed | Code released (GitHub) |
| HASE (alpha task) | CogAlpha baseline (reported, not re-run) | Yes | B | Inherits CogAlpha's split; not the paper's primary focus | Moderate–high (same category) | Lower than CogAlpha (smaller model) | Not confirmed |

---

## 16. Notion / project-knowledge update

I attempted to write this session's findings to the project's Notion workspace, consistent with instruction #16. Per the record in the prior session, Notion write access had previously failed with a "No approval received" error traced to a client-side authorization prompt, and its resolution status was unconfirmed. This session's attempt should be logged accordingly rather than assumed successful — I have not fabricated a Notion write in this document. If you'd like, I can attempt the write now and report the concrete result (success, or the specific error), or you can confirm the authorization has been fixed on your end first.

Pending that, the following should be understood as the update to make once Notion is writable, so nothing is lost in the interim:

- **Research Log**: add this entire research thread (self-improvement taxonomy, HGM deep-dive, financial-system inventory, overfitting findings, cost/safety findings) as a new dated entry, session tagged 2026-08-31 (or the session's actual date).
- **Assumption Register**: add/update — "Self-improvement mechanisms in this field range from harmless (memory) to structurally overfitting-prone (backtest-driven strategy evolution) to genuinely untested in finance (code/architecture self-modification)." Mark as **Supported by evidence surveyed**.
- **Open Questions**: add all six "Evidence gap" items from §10 and §13 verbatim (human-designed vs. AI-generated strategy; no-memory vs. memory ablation; no-automated-experimentation vs. automated-experimentation ablation; single-agent vs. multi-agent-plus-self-improvement; walk-forward evaluation in any reviewed finance self-improvement system; third-party replication of any finance self-improvement claim).
- **Sources**: add all newly-surfaced papers from this session — Huxley-Gödel Machine (2510.21614), Darwin Gödel Machine (2505.22954), FinCon (2407.06567), QuantAgent (2402.03755), ATLAS (2510.15949), FinRL-DeepSeek (2502.07393), CogAlpha (2511.18850), QuantaAlpha (2602.07085), HASE (2607.03935), "Harness Updating Is Not Harness Benefit" (2605.30621), Agent Drift (2601.04170), "Statistical Limits of Self-Improving Agents" (2510.04399), Profit Mirage (2510.07920), "Agentic Trading" evidence-map survey (2605.19337), and its companion (2606.08285).
- **Project Understanding**: append (not replace) a note that the project's understanding of "self-improvement" has moved from a single undifferentiated concept to the harness/model/code three-way distinction described in §1, and that this distinction should be treated as settled vocabulary going forward.

---

## 17. Independent assessment — answers to the brief's closing questions

**What does "self-improving trading agent" actually mean?** In the literature as it actually exists, it almost always means one of: (a) a memory/reflection loop that changes what the system can retrieve, not what it fundamentally does; (b) a prompt-optimization loop that tunes static instructions against a feedback signal; or (c) an evolutionary strategy-generation loop that proposes and backtests candidate trading rules or factors. It essentially never means, in a financial context, an agent that rewrites its own orchestration code or architecture the way HGM/DGM do in the coding domain — that specific, more dramatic form of self-improvement is real and impressive, but confined to coding benchmarks.

**Which mechanisms have actually been implemented?** Memory, reflection, self-critique, prompt optimization, parameter optimization (risk thresholds), strategy generation/selection via code-level evolution, and RL/fine-tuning of a policy layer around LLM-generated signals — all genuinely implemented, with released code in several cases (FinMem, FinRL-DeepSeek, CogAlpha family, HGM/DGM in the coding domain).

**Which mechanisms have evidence of benefit?** Prompt optimization (ATLAS, one controlled finance study), the strategy-generation/evolution family (multiple papers claim benchmark-beating results, though with the overfitting caveats in §7), and CVaR-style within-episode risk adjustment (FinCon). Notably weak or absent: reflection specifically showed *no* systematic benefit in the one controlled finance test found, despite being probably the most intuitively appealing mechanism in the whole taxonomy.

**Which mechanisms appear mostly theoretical?** Architecture self-modification (not found in finance at all) and, in a softer sense, genuine online/continual weight-level learning during live deployment (not found in finance — every system trains, then freezes).

**Where does self-improvement become automated overfitting?** Structurally, in any loop where a candidate modification is judged solely by repeated backtesting against the same historical data without disciplined chronological splitting, cost/friction modeling, or correction for the number of variants tried (PBO/CSCV-style) — which describes most of the evolutionary alpha-mining subfield to varying degrees, and which the field-wide reproducibility audit found is under-documented across the great majority of published systems.

**Is there credible evidence that self-improvement improves out-of-sample trading performance?** Weak and mixed. Individual papers (CogAlpha, ATLAS, FinCon) report genuine, disclosed, methodologically reasonable positive results within their own evaluation frameworks. But no independent replication exists for any of them, the field-wide reproducibility audit found the infrastructure to trust such claims is largely missing across the literature, and at least one paper (FinRL-DeepSeek) discloses a case where its own self-improvement mechanism made things worse. This should be read as "plausible in narrow, well-controlled cases; not established as a general phenomenon."

**Does self-improvement appear more promising than simply improving the underlying trading strategy?** No comparison answering this directly was found. This is arguably the most important unanswered question the brief raises, and this research pass could not resolve it — record as an explicit **Evidence gap** that may deserve dedicated future research rather than being folded into a broader "self-improvement is promising" narrative.

**What are the biggest unanswered questions?** (1) Whether any of these mechanisms survive genuine live deployment, since none have Tier-A evidence; (2) whether self-improvement outperforms a well-designed static strategy, controlling for the effort put into each; (3) whether the strongest positive results (CogAlpha, QuantaAlpha) survive independent replication and proper PBO/CSCV-style correction; (4) whether prompt-injection or data-poisoning attacks against a system's memory/prompt-optimization loop specifically (as opposed to a single-turn attack) are a practical, demonstrated risk or a theoretical one for finance.

**How important is this research to our eventual project?** Central, not peripheral. Given the north-star objective explicitly includes self-improvement as one of its open architectural questions, and given that this research pass found the field's own evidence base for self-improvement to be less mature and more methodologically fraught than its evidence base for the multi-agent architectures researched previously, this suggests that *if* self-improvement is eventually adopted, the project's own evaluation discipline (walk-forward splits, cost-adjusted, leakage-checked, ideally with some PBO/CSCV-style correction) will need to be more rigorous than what currently exists in the published literature — because the published literature cannot currently be relied upon to have already solved this problem for us.

---

*This document does not propose an architecture, does not recommend a mechanism, and does not conclude that self-improvement should or should not be part of the eventual system. It reports what the evidence currently shows, and where it currently runs out.*
