# Stage 0 Research Thread — Self-Improvement vs. Strong Static Strategy
**AI Trading Agent Research & Engineering Project**
Status: Draft for discussion · Stage 0 (Project Understanding) · Not a Requirements document · Not an architecture proposal

---

## 0. Scope note

This is a dedicated pass on one question left explicitly unresolved by the prior self-improvement research: **if we already have a competent, properly validated static system, does adding self-improvement produce enough additional value to justify its complexity, cost, and risk?** Per the brief, this is kept distinct from "does self-improvement beat a weak baseline" (already partly answered — yes, sometimes, against weak baselines) and from architecture/build decisions (out of scope for Stage 0). I searched both the LLM-trading literature and the older, larger body of classical quantitative-finance literature on adaptive vs. static strategies, since the brief specifically asked me not to restrict to LLMs. All evidence tiers (A–E) carry over from prior sessions.

---

## 1. Defining the comparison

Before weighing evidence, it's worth being precise about what "static" and "adaptive" mean here, because sloppiness on this point is exactly what makes much of the literature hard to compare.

- **Static system**: strategy, prompts, model configuration, parameters, and agent structure are all fixed for the duration of the evaluation window. It can still consume new market data as input (a static momentum strategy still looks at today's prices) — "static" describes the *decision logic*, not the *data feed*.
- **Adaptive system**: at least one of prompts, memory, parameters, strategy, strategy selection, weights, code, or architecture is allowed to change based on feedback during the evaluation window.

The brief is right that these are not one axis. A system that only accumulates memory (FinMem) is a different kind of "adaptive" than one that retrains RL weights (FinRL-DeepSeek) or evolves strategy code (CogAlpha). Comparisons that lump all of these under "self-improving vs. static" without saying which mechanism is doing the adapting are lower-value evidence than ones that isolate a single mechanism — this distinction is carried through the rest of this report.

---

## 2. Controlling for human effort — the discovery vs. adaptation distinction

The brief's request to separate "better strategy discovery" from "better strategy adaptation after deployment" turns out to be the single most useful lens this research pass found, because almost everything in the literature falls cleanly on one side or the other once you look for it:

- **Strategy discovery** (finding a good strategy in the first place): CogAlpha, QuantaAlpha, R&D-Agent-Quant, AlphaAgent, XAlpha, Alpha-GPT — all of these are, functionally, **automated research assistants that search a large space of candidate strategies faster than a human team could**, then hand off a (typically static, or slowly-updated) result. This is a genuine, demonstrated form of value, but it is a claim about *research productivity*, not about *live adaptive trading*. See §5 and §11.
- **Strategy adaptation post-deployment** (a live system changing itself while trading): ATLAS (prompt optimization), FinCon (belief updates — though explicitly frozen at test time), FinRL-DeepSeek (RL retraining), continuous online learning generally. This is a much smaller, much less mature body of work, and — per the previous session's finding — the *closest* thing to a controlled test of this specific claim (ATLAS) found that one of the two adaptive mechanisms tested (reflection) didn't help, while the other (prompt optimization) did.

**No study found in this session directly and rigorously separates these two effects while holding total human/compute effort constant**, i.e., nobody has run "give a human team X hours to hand-design a strategy" against "give an LLM system X hours of compute to discover a strategy" against "give an LLM system X hours of compute to discover a strategy, then let it keep adapting after deployment," with everything else controlled. This is an important, clean **Evidence gap**, and it means the brief's central question does not currently have a study that answers it directly. What follows is the best available circumstantial evidence bearing on it.

---

## 3. Classical (pre-LLM) evidence on static vs. adaptive — this is where the strongest evidence lives

The brief was right to suspect that older quantitative literature might have stronger evidence than the LLM-specific literature, and this turned out to be the single most important finding of this research pass.

### 3.1 The most directly relevant classical result: naive (static) beats sophisticated (adaptive) far more often than intuition suggests

**DeMiguel, Garlappi, and Uppal, "Optimal Versus Naive Diversification: How Inefficient Is the 1/N Portfolio Strategy?"** (*Review of Financial Studies*, 2009) — one of the most-cited papers in empirical asset management, and directly on point. They tested 14 "optimal" (sophisticated, estimated, adaptive-to-data) portfolio allocation models against the simplest possible static baseline — an equally-weighted (1/N) portfolio that requires no estimation at all — across 7 real-world datasets. **Result: none of the 14 sophisticated models was consistently better than the naive static baseline** in Sharpe ratio, certainty-equivalent return, or turnover. Their analytical explanation is exactly the mechanism this project should care about: **estimation error from fitting a more complex model to finite, noisy data outweighs the theoretical benefit of that complexity**, and they calculate that for a 25-asset portfolio, the estimation window needed for a sophisticated model to reliably beat the naive one is *around 3,000 months* — i.e., not achievable within any realistic dataset. This is **Tier A** by any reasonable standard: peer-reviewed in a top journal, replicated and debated for over 15 years, analytically grounded, not just an empirical curiosity.

This finding has been contested (Kritzman, Page, and Turkington's 2010 "In Defense of Optimization: The Fallacy of 1/N" argues the comparison understates optimization's value under certain conditions), and later work found that **with 3 or more genuinely distinct factors, sophisticated approaches can meaningfully outperform** naive diversification. **This is itself informative**: the debate isn't "sophistication never helps," it's "sophistication needs enough genuine, distinct structure in the data to overcome the estimation-error cost it introduces" — a conditional, not a universal, finding. This maps directly onto the self-improvement question: a self-improving mechanism is, structurally, adding estimated complexity (whether that's a learned prompt, a learned weight, or a learned strategy parameter), and the DeMiguel et al. result says that complexity is a cost that has to be earned back by genuine signal, not assumed to pay for itself.

### 3.2 Walk-forward optimization and adaptive parameter-tuning: helps against regime lag, doesn't eliminate overfitting

Walk-forward optimization (Pardo, 1992/2008) — periodically re-optimizing strategy parameters on a rolling window rather than fixing them once — is the classical, pre-LLM analogue of "parameter adaptation" in the taxonomy. The literature here is genuinely useful and underused by the LLM-trading field:

- It exists specifically because **non-stationarity is real**: "the optimal parameter set for the quantitative easing era of low volatility is highly unlikely to be the optimal set for a period of geopolitical turmoil" — a fixed strategy really can go stale.
- But it has known, documented limits: it **responds to regime changes with a lag**, since it can only detect a regime shift after living through its negative impact for a while — i.e., adaptation is reactive, not predictive, and the cost of that lag is real.
- **Bailey and López de Prado (2014)**, cited across multiple sources this session, provide a rigorous general finding directly relevant to "does more searching over more parameter configurations help": they prove that high in-sample performance is easy to achieve after testing relatively few configurations, and — this is the important part — **memory effects in financial time series cause over-fit strategies to *systematically underperform*, not merely fail to outperform, out-of-sample.** This is a stronger and more specific claim than generic "overfitting is bad": it says the direction of the error is predictable (overfit strategies don't just regress to the mean, they tend to actively lose relative to a well-chosen benchmark once deployed).

### 3.3 Regime-switching models: real, but modest, and sensitive to implementation detail

Multiple academic asset-allocation papers on regime-switching (Markov regime-switching, statistical jump models) were reviewed. The pattern across them:
- Regime-aware approaches **can** improve risk-adjusted metrics (several papers report improved Sharpe/drawdown vs. a static benchmark).
- But the improvement is frequently modest and sometimes vanishes under mild changes to implementation: one paper found a more complex regime-based *linear* weighting scheme delivered "similar out-of-sample performance" to a much simpler binary (0/1) regime switch, and another found the long-short version of a similar strategy "enhances returns" but the short leg "fails to effectively mitigate risk," producing high volatility rather than the intended risk reduction.
- Performance also degrades with realistic **trading delay** (the time between detecting a regime and being able to act on it) — a point directly relevant to any live system, since inference/decision latency is a real-world tax on any adaptive mechanism that isn't instantaneous.

**Overall classical-literature verdict:** adaptation (whether parameter re-optimization, regime-switching, or portfolio-model sophistication) shows real but *conditional and modest* benefit in the best-designed, most rigorous pre-LLM studies, is frequently matched or beaten by much simpler static approaches once estimation error and implementation-detail sensitivity are accounted for, and the field's own most famous, most-replicated result (DeMiguel et al.) argues for real skepticism about assuming added adaptive sophistication pays for itself.

---

## 4. LLM-specific evidence: does self-improvement beat a genuinely strong static baseline?

This is where the brief's "good static strategy" problem (§8 of the brief) becomes sharp, because the honest answer is that **most of the LLM-trading literature has not used a strong baseline, and the small number of papers that deliberately used a strong, broad, long-horizon baseline found the LLM/adaptive advantage weakens or disappears.**

### 4.1 The most damning and most methodologically serious finding this session: FINSABER

**"Can LLM-based Financial Investing Strategies Outperform the Market in Long Run?"** (arXiv 2505.07078) is, by design, exactly the experiment the brief is asking for. The authors built **FINSABER**, a backtesting framework specifically constructed to correct for the narrow-timeframe, narrow-universe, survivorship/data-snooping biases that plague most LLM-trading papers, and re-ran evaluations **over two decades and 100+ symbols** rather than the few-month, few-stock windows typical of the field.

**Result: "previously reported LLM advantages deteriorate significantly under broader cross-section and over a longer-term evaluation."** More specifically and more usefully, they found a *directional* failure pattern, not just a magnitude reduction: LLM strategies were **overly conservative in bull markets** (underperforming a passive benchmark by sitting out gains) and **overly aggressive in bear markets** (incurring heavy losses) — i.e., the LLM-driven adaptivity was systematically miscalibrated to regime in a way that hurt rather than helped, in both directions. This is a genuinely rare, high-quality piece of evidence: Tier B, methodologically deliberate about fixing exactly the evaluation weaknesses this project's prior sessions flagged, and its conclusion is a real, specific negative result rather than a vague "more research needed."

### 4.2 StockBench: a strong, contamination-free baseline comparison

**StockBench** (arXiv 2510.02209) is a contamination-free, multi-month, real-market benchmark testing frontier LLMs (GPT-5, Claude-4, Qwen3, Kimi-K2, GLM-4.5) as trading agents against the simplest possible static baseline: buy-and-hold. **Result: "most models struggle to outperform the simple buy-and-hold baseline,"** though a subset showed potential for higher returns and better risk management. The authors' own framing is directly relevant to the discovery-vs-adaptation distinction in §2: they explicitly note that **strong performance on static financial knowledge tasks does not translate into effective trading behavior** — i.e., being a capable, well-informed LLM is not the same as being a good adaptive trader, a distinction that should temper optimism about any self-improvement mechanism that assumes "a smarter/more-optimized agent will trade better."

### 4.3 The alpha-decay literature independently confirms the overfitting-adaptation tradeoff

**AlphaAgent** (arXiv 2502.16789) is nominally a positive result for LLM-driven adaptation, but its own framing is more useful as evidence *for* the brief's concern than against it: the paper's entire premise is that **both classical genetic-programming-based alpha discovery *and* naive LLM-driven alpha discovery decay rapidly** — GP from overfitting to historical noise, LLM approaches from over-reliance on existing/memorized knowledge producing crowded, homogeneous, quickly-arbitraged factors. AlphaAgent's contribution is a set of *regularizers* (originality-enforcement, complexity penalties) specifically designed to fight this decay. This is useful evidence in two ways: (1) it independently corroborates, from a different research group, that unconstrained strategy-generation self-improvement decays fast by default — consistent with the overfitting findings from the prior session — and (2) it shows that the field's own response to this problem is to constrain/regularize the adaptive mechanism, not to let it run freely, which is itself informative about how much raw, unconstrained self-improvement is actually trusted by researchers working closest to the problem.

### 4.4 The field-wide reproducibility survey's own framing

Returning to the 77-study evidence-map survey (arXiv 2605.19337) referenced in the prior session: its section on reinforcement-learning-style adaptation states plainly that **"reinforcement-learning-style adaptation... dominates the section's primary evidence, but its reported gains remain sensitive to split discipline, simulator fidelity, and reward-hacking risk"** — i.e., the one class of mechanism that is genuinely adaptive (not just memory/prompt-level) shows gains that the survey's own authors flag as fragile to exactly the evaluation-discipline factors this project has been tracking since the first self-improvement session.

---

## 5. Static vs. self-evolving alpha generation — research automation, not proven trading superiority

Applying the brief's specific framing directly: **are CogAlpha/QuantaAlpha/AlphaAgent/R&D-Agent-Quant/XAlpha/QuantAgent demonstrating that evolution/self-improvement is valuable, or that LLMs can automate a quantitative research workflow?**

Based on everything found this session and last: **overwhelmingly the second, not clearly the first.** Every one of these systems' own evaluation methodology is: generate many candidate strategies with an LLM-driven process, backtest them, select survivors — which is structurally identical to what a team of human quant researchers already does, just automated. None of them include a controlled comparison against "a team of human researchers given equivalent time/compute-cost budget," which is the comparison that would actually distinguish "the automation is valuable because it's faster/cheaper" from "the automation discovers genuinely better strategies than humans would." **This is the clean evidence gap the brief anticipated, and it remains unresolved.**

What the literature *does* support, from industry-practitioner sources rather than academic papers (Man Group's AlphaGPT writeup, the Zerve/Quantfish commentary found this session): the emerging consensus among practitioners actually building these systems is closer to **"AI changes how quant research is performed, not what ultimately creates investment edge"** (direct quote, Zerve) and that as research productivity increases industry-wide, **the competitive advantage from that productivity may not increase at all, because alpha is a relative, not absolute, resource** — if every fund gets the same research-automation tools, the playing field re-levels rather than any one fund gaining a durable edge (Quantfish). This is speculative commentary, not a controlled study (Tier D-E), but it's a coherent and economically sound argument that should be weighed: **even if self-evolving alpha discovery genuinely finds real signal faster than humans, that speed advantage may be competed away industry-wide rather than being a durable source of edge for any single practitioner** — a consideration a personal, single-account project should take especially seriously, since it cannot rely on scale or proprietary infrastructure to protect a research-speed advantage the way an institutional fund might.

---

## 6. Cost-benefit

Combining this session's findings with the prior session's cost data (§11 of the previous report):

- **QuantaAlpha, CogAlpha, R&D-Agent-Quant class systems** are reported (per HASE's characterization of CogAlpha) to require complex, multi-agent orchestration (a 21-agent hierarchy in CogAlpha's case) — a real, non-trivial cost, and this is *before* accounting for the compute cost of the backtesting cycles themselves.
- **Alpha-GPT 2.0**'s own stated motivation for moving to a *human-in-the-loop* paradigm, rather than a fully autonomous one, is explicitly cost-driven: **"as research advances, computational power tends to yield diminishing returns in terms of strategy performance improvement, making the approach increasingly cost-inefficient."** This is a direct, first-party admission from a team building exactly this kind of system that unconstrained automated research hits diminishing returns, and that hybridizing with human judgment was their answer — not a criticism from outside the field, but a design decision made by practitioners closest to the tradeoff.
- No study found this session or last quantifies the dollar-for-dollar tradeoff the brief asks about directly (X% Sharpe improvement for Y× operating cost). This remains an evidence gap, but the qualitative direction from every cost-aware source found (Alpha-GPT 2.0, the general token-economics literature from the prior session) points the same way: **diminishing returns to additional automated search/adaptation compute, past a point that is reached faster than intuition suggests.**

---

## 7. Adaptation vs. overfitting — is there evidence of an optimal middle ground?

The clearest single framing found, again from the walk-forward literature: adaptation exists on a spectrum where **too static** fails to track genuine regime change (documented cost: lagged, sometimes large drawdowns when a strategy tuned for one regime meets another) and **too adaptive** overfits noise (documented cost: PBO rates frequently cited above 50% in aggressively-searched strategies; Bailey & López de Prado's finding that overfit strategies systematically underperform, not just fail to outperform).

Is there evidence of a good middle ground? Partially:
- **Walk-forward optimization with disciplined out-of-sample testing** is the field's long-standing practical answer, and it works better than either extreme *when done with genuine chronological discipline* — but as documented in the previous session, this discipline (proper chronological splits, held-out data, correction for the number of configurations tried) is exactly what's missing from most of the LLM-trading literature (2/19 studies with an extractable split protocol).
- **CogAlpha's chronological train/validation/test split** and **ATLAS's deliberately narrow, static-portion-only prompt editing** (explicitly designed, per the paper, "to ensure compatibility... and prevent overfitting to transient data") are the two clearest examples found across both sessions of a system explicitly engineered to sit in this middle ground rather than maximizing adaptivity. Both are worth treating as positive design patterns regardless of whether their specific performance claims replicate.
- **AlphaAgent's regularization mechanisms** (originality enforcement, complexity penalties) are a third example of the same instinct: constrain the adaptive/generative process explicitly, don't let it run freely and hope backtesting catches the overfitting after the fact.

**No paper found in this session establishes a general, transferable "optimal adaptation rate" for financial strategies** — the closest thing (walk-forward window-length tuning) is itself an empirical, dataset-specific exercise, not a general law. This should be recorded as: **evidence of the tradeoff's existence and shape, no evidence of a universal optimum.**

---

## 8. The "good static strategy" problem, addressed directly

**How much of the apparent benefit of self-improvement disappears when the baseline is genuinely strong?** Based on the evidence gathered:

- Against the **weakest** static baselines (a single fixed prompt, in ATLAS's ablation), adaptation (prompt optimization specifically) showed a real, disclosed benefit.
- Against a **moderately strong** baseline (buy-and-hold, in StockBench), most LLM agents — despite being allowed to reason, use tools, and adapt turn-to-turn — **failed to beat it**.
- Against a **genuinely strong, broad, long-horizon evaluation design** (FINSABER's 100+ symbols, two decades), previously reported LLM advantages **deteriorated significantly**, with a specific, systematic directional failure (wrong-way regime miscalibration).
- Against the **strongest classical static benchmark in the asset-management literature** (naive 1/N diversification, per DeMiguel et al.), the finding — for *sophisticated portfolio optimization generally*, not LLMs specifically, but structurally the same "add complexity, hope it pays for itself" bet — is that **sophistication consistently fails to reliably beat the simplest possible static approach**, for a specific, quantifiable reason (estimation error).

**The pattern across all four is consistent and should be stated plainly: the strength of the apparent case for adaptation/self-improvement is inversely related to the rigor and breadth of the baseline it's tested against.** This is close to the brief's own hypothesis in §8, and the evidence gathered this session supports it more strongly than it contradicts it.

---

## 9. What would a convincing experiment need to show?

Synthesizing the brief's own list with the specific tools surfaced across both sessions, a convincing static-vs-adaptive (or self-improving-vs-strong-static) comparison would need, at minimum:

1. **A genuinely strong static baseline** — not a fixed prompt or buy-and-hold alone, but something like a well-tuned classical factor strategy, a properly-fit walk-forward-optimized rule system, or (per DeMiguel et al.'s own standard) naive diversification, since the evidence above suggests weak baselines are where most of the illusory "adaptation helps" signal comes from.
2. **Identical data, backbone, environment, and cost budget** across both arms, so any performance difference is attributable to the presence/absence of adaptation rather than to a confound (a bigger model, more data, more compute spent on one arm).
3. **Chronological, walk-forward, genuinely held-out test data**, not a single fixed split — and ideally the CSCV/PBO-style correction (Bailey et al.) for however many configurations were tried during "discovery," on both the static and adaptive sides, since a static strategy chosen after trying 500 variants is not meaningfully different in overfitting risk from a self-improving one.
4. **Explicit transaction-cost, slippage, and execution-friction modeling** on both arms — the field-wide survey found only 1/19 studies in its primary subset report this at all, and its absence tends to favor whichever strategy trades more (often the adaptive one), which biases the comparison in adaptation's favor by default if left unmodeled.
5. **Multiple market regimes and multiple assets**, given FINSABER's finding that the direction of LLM miscalibration (over-conservative in bull, over-aggressive in bear) only became visible once evaluation was extended across regimes.
6. **Multiple random seeds and a stated significance/multiple-testing correction** — not found as standard practice in any finance self-improvement paper reviewed across either session.
7. **Independent replication by a group not invested in the result** — not found for any claim in this literature, in either session.
8. **Separate reporting of "did the adaptive system discover a better strategy" vs. "did the adaptive system's ongoing post-deployment adaptation add value beyond the strategy it started with"** — per §2's distinction, since conflating these two claims is, in this research pass's judgment, the single most common source of overstated "self-improvement works" claims in the literature.

No single study found across either research session satisfies more than 2–3 of these eight conditions simultaneously. This is itself a finding, and it is consistent with (and sharpens) the prior session's field-wide reproducibility critique.

---

## 10. Negative results — actively sought, not filtered

Per the brief's explicit instruction, negative results were prioritized in this search rather than treated as an afterthought. Collected across this session and carried forward from the last:

- **FINSABER**: previously-reported LLM trading advantages deteriorate significantly under a broader, longer, less-biased evaluation; LLM strategies show a specific systematic miscalibration (wrong-way regime behavior) rather than merely "less impressive" performance.
- **StockBench**: most frontier LLM agents fail to beat simple buy-and-hold.
- **FinRL-DeepSeek** (carried forward): in at least one tested configuration, "the use of LLM always worsens performance" versus the non-LLM RL baseline.
- **ATLAS** (carried forward): reflection-based feedback did not yield systematic improvement, contrary to the intuitive expectation that reflection should help.
- **DeMiguel, Garlappi, Uppal (classical)**: none of 14 sophisticated/adaptive portfolio models consistently beat the naive static 1/N baseline; the estimation-error cost of added sophistication is large and quantifiable.
- **Bailey & López de Prado (classical)**: overfit/over-adapted strategies don't just fail to outperform out-of-sample — they systematically underperform.
- **AlphaAgent's own framing** (used here as negative evidence about the *default* behavior of the mechanism class it improves on): unconstrained alpha-generation self-improvement (both classical genetic programming and naive LLM-driven approaches) decays rapidly without deliberate regularization.
- **Regime-switching asset-allocation literature**: some regime-adaptive schemes deliver performance "similar" to much simpler binary switches; a long-short regime strategy in one study enhanced returns but failed at its actual stated goal of risk mitigation, instead increasing volatility.
- **Walk-forward optimization's own documented limitation**: adaptation to regime change is lagged, not predictive — the system still experiences the downside of a regime shift before it can adjust.

This is a genuinely substantial body of negative and cautionary evidence, comparable in seriousness to the positive evidence found across both sessions, and in this research pass's judgment **somewhat more methodologically rigorous on average** than the positive claims (FINSABER and DeMiguel et al. in particular are unusually careful, deliberately-designed-to-avoid-bias studies, more so than most of the positive self-improvement papers reviewed in the prior session).

---

## 11. Automated research vs. autonomous trading — where does the value actually seem to concentrate?

Directly addressing the brief's §11: **the evidence gathered across both sessions points toward research-process value being the more defensible, better-evidenced claim, and live trading-adaptation value being the weaker, less-evidenced one.**

Supporting this:
- The strongest positive evidence for any self-improvement mechanism (CogAlpha's disciplined chronological split, AlphaAgent's decay-resistance results, ATLAS's prompt-optimization result) is evidence about **improving the process of finding/tuning a strategy**, not about a live system successfully continuing to adapt itself while trading.
- The strongest negative evidence (FINSABER, StockBench, FinRL-DeepSeek's disclosed negative result) is specifically about **live/backtested trading performance**, not about the research/discovery process.
- Practitioner-side commentary (Man Group's AlphaGPT, the Alpha-GPT 2.0 academic paper's own design choice) converges on **human-in-the-loop as the pragmatic answer**, explicitly because pure automation hits cost/diminishing-returns limits — i.e., the industry's own revealed preference, where real money is at stake, is not to trust full autonomous self-improvement in either the research or the trading role, but to use AI to accelerate the human-directed research process while keeping a human in the loop for judgment calls.
- QuantAgent's own two-layer framing (inner loop for refinement, outer loop for real-world-feedback-based knowledge-base updates) is arguably itself evidence for this same conclusion: its formal contribution is a research/knowledge-acquisition loop, not a claim about continuously self-modifying live trading logic.

**This does not resolve to "self-improvement in live trading definitely doesn't work"** — the evidence is not strong enough in either direction to say that — but it does suggest that **if this project wants to capture value from AI self-improvement with the best-supported evidence behind it, that value is more plausibly located in accelerating and broadening the research/strategy-discovery process (with human review before anything reaches live capital) than in a system that continues to autonomously adapt itself while capital is at risk.** This is an observation about where the evidence currently points, not a design recommendation.

---

## 12. Indian equity relevance

Directly relevant Indian-market evidence found:
- **Hiremath and Kumari (2014), "Stock returns predictability and the adaptive market hypothesis in emerging markets: evidence from India"** — found that the Indian market has historically **cycled between periods of relative efficiency and inefficiency** rather than being uniformly one or the other, with a documented trend *toward* increasing efficiency over the sample period, and linked periods of inefficiency partly to financial crises and foreign portfolio investment flows. This is directly relevant background: if efficiency is genuinely increasing over time, that argues for *less* durable edge available to any strategy (static or adaptive) as time passes, and for whatever edge exists being more regime/crisis-dependent than a stable, permanently exploitable pattern — which would favor a system that can detect and respond to those specific windows (an argument *for* some form of adaptation) but also raises the stakes on avoiding the overfitting failure mode this report has otherwise emphasized (since a system chasing "inefficiency windows" in a shrinking inefficiency budget is exactly the kind of environment where automated overfitting is easiest and most costly).
- **Momentum-factor studies specific to NSE/BSE** (large, liquid F&O-eligible stocks) confirm momentum effects have historically existed in Indian equities, consistent with global findings, but these are classical factor-existence studies, not comparisons of static-vs-adaptive implementation of momentum specifically.
- **No paper found in this session or the prior one applies any LLM-based self-improvement mechanism to Indian equities specifically**, and no paper compares adaptive vs. static strategy performance within the Indian market specifically using anything resembling the self-improvement mechanisms surveyed in the taxonomy. This should be recorded plainly as an **open, unaddressed gap**: everything in §3, §4, §7, §8, §10 above is evidence from US, Chinese (CSI300/CSI500), or general/crypto markets, and **should not be assumed to transfer directly to Indian equities** — a caution the project's own initialization document already anticipated but which this session's research reinforces rather than resolves.

---

## 13. Evidence tables

**Table 1 — Study/system-level evidence**

| Study/System | Static Baseline | Adaptive System | What Changes | Same Backbone? | Same Data? | OOS? | Costs Included? | Multiple Testing? | Result | Evidence Tier |
|---|---|---|---|---|---|---|---|---|---|---|
| DeMiguel, Garlappi, Uppal (2009) | Naive 1/N portfolio | 14 sample-based mean-variance models | Portfolio weights | N/A (not LLM) | Yes, 7 real datasets | Yes | Turnover reported | N/A | None of 14 consistently beats naive static baseline | A |
| Bailey & López de Prado (2014) | N/A — general result | Any strategy selected via search | Whatever's searched | N/A | N/A (theoretical + general) | By construction | Yes (Deflated Sharpe accounts for it) | Yes, core contribution | Overfit strategies systematically underperform OOS, not just fail to outperform | A |
| Walk-forward optimization literature (Pardo; various) | Fixed-parameter backtest | Rolling-window re-optimized parameters | Strategy parameters | N/A | Varies | Yes, by design | Rarely fully modeled | Rarely | Helps vs. naive static backtest; still lags regime shifts; computationally costly | B |
| FINSABER (2505.07078) | Buy-and-hold, passive benchmarks | Various published LLM timing strategies | LLM-driven timing decisions | Multiple, re-tested | Yes — 100+ symbols, 2 decades | Yes, explicit rolling windows | Not fully confirmed from sources reviewed | Explicit correction for survivorship/data-snooping | LLM advantages deteriorate significantly at scale/length; systematic regime miscalibration | B |
| StockBench (2510.02209) | Buy-and-hold | Frontier LLM agents (GPT-5, Claude-4, Qwen3, etc.) | LLM trading decisions | Multiple, compared | Yes, multi-month real market | Contamination-free by design | Not fully confirmed | Not confirmed | Most models fail to beat buy-and-hold | B |
| AlphaAgent (2502.16789) | Traditional GP-based + prior LLM-based alpha mining | AlphaAgent's regularized LLM mining | Alpha-factor code | Multiple LLMs tested | CSI 500, S&P 500, 2021–2024 | Yes | Not confirmed | Not confirmed | Outperforms baselines and resists decay, per authors — but implicitly confirms both classical and naive-LLM alpha generation decay fast by default | B (self-reported; not independently replicated) |
| CogAlpha (carried forward) | Prior alpha-mining methods | Evolutionary code-level alpha generation | Alpha-factor code | Yes, ablations reported | CSI300, chronological split | Yes, explicit | Not confirmed | Not confirmed | Outperforms on IC/RankIC | B |
| ATLAS (carried forward) | Fixed prompts | Adaptive-OPRO (prompt) vs. reflection | Prompt template only | Multiple backbones | Regime-specific experiments | Partial | Not fully confirmed | Not confirmed | Prompt-opt helps; reflection doesn't | B |
| FinRL-DeepSeek (carried forward) | Non-LLM PPO | LLM-augmented CPPO | RL policy weights | Multiple LLM signal sources | Nasdaq-100, 2013–2023 | Yes, held-out period | Not fully specified | Not confirmed | Mixed; LLM sometimes worsens performance | B |
| Regime-switching asset allocation (various, §3.3) | Static allocation | Markov/jump-model regime switching | Portfolio weights by regime | N/A | Varies | Yes | Transaction costs addressed in some (e.g., LoT/MaxLev paper) | Not typically | Modest, condition-dependent improvement; sometimes no better than simplest regime scheme | B |
| Hiremath & Kumari (2014) | N/A — market-efficiency study | N/A | N/A | N/A | Indian equities, multi-decade | N/A | N/A | N/A | Indian market cycles between efficiency/inefficiency, trending toward efficiency | B |

**Table 2 — Evidence-question summary**

| Evidence Question | Current Answer | Confidence | Best Supporting Evidence | Main Counterevidence |
|---|---|---|---|---|
| Does adaptation improve returns? | Sometimes, mechanism- and baseline-dependent | Low-moderate | ATLAS (prompt-opt); some regime-switching studies | FINSABER; StockBench; DeMiguel et al. |
| Does adaptation improve risk-adjusted returns? | Weak/mixed evidence | Low | FinCon's CVaR mechanism (single paper); some regime-switching studies | FINSABER's regime-miscalibration finding; long-short regime paper's volatility increase |
| Does adaptation improve robustness? | Not clearly supported | Low | Walk-forward's stated rationale (design intent, not proven outcome) | Bailey & López de Prado; PBO rates >50% commonly cited |
| Does adaptation survive OOS evaluation? | Partially, inconsistently | Low-moderate | CogAlpha's chronological split; FinRL-DeepSeek's held-out test | Field survey: only 2/19 studies report an extractable split at all |
| Does adaptation justify its complexity? | Not established | Low | — (no study directly answers this with cost accounted for) | Alpha-GPT 2.0's own diminishing-returns admission; DeMiguel et al.'s estimation-error argument |
| Does self-improvement beat strong static strategies? | Evidence points toward "no, or not clearly" as baselines strengthen | Moderate | — | FINSABER, StockBench, DeMiguel et al. — three independent lines of evidence, three different methodologies, same directional conclusion |
| Does adaptation work better in certain regimes? | Plausible, some support | Low-moderate | Regime-switching literature generally | FINSABER's finding that LLM adaptation is *miscalibrated* by regime (wrong-way, not just imprecise) |
| Does adaptation provide value mainly through research automation? | Best-supported affirmative claim in this report | Moderate | Every alpha-mining self-improvement system's actual demonstrated use case; practitioner commentary (Man Group, Alpha-GPT 2.0, Zerve) | No controlled human-vs-AI-research comparison exists to confirm this rigorously |

---

## 14. Notion update status

I attempted to determine whether this session's write access issue was resolved before drafting further content for Notion, consistent with the instruction not to claim a write succeeded if it did not. In the immediately preceding session, read access to the workspace worked (I was able to locate the existing "AI Trading Agent — Research Log" and "AI Trading Agent — Project" pages), but a write attempt to append content to the Research Log failed again with the same "No approval received" error seen previously. I have not re-attempted the write in this session pending your input on whether the permission issue has been addressed, since repeating a known-failing action without new information wastes a turn without new evidence either way. If you'd like me to retry now, I will, and will report the exact outcome rather than assume success.

The content that should be appended to the Research Log once write access is confirmed working (preserving, not overwriting, all prior entries):

> **Session — Self-Improvement vs. Strong Static Strategy (dated appropriately).** Core finding: the strength of evidence for adaptation/self-improvement is inversely related to the rigor and breadth of the baseline tested against it. Against weak baselines (fixed prompts, buy-and-hold), some adaptive mechanisms show real benefit (prompt optimization in ATLAS). Against genuinely strong, broad, long-horizon baselines (FINSABER's 100+ symbol two-decade test; the classical DeMiguel-Garlappi-Uppal 1/N result), the adaptive/sophisticated advantage weakens substantially or disappears, with FINSABER documenting a specific systematic miscalibration (LLM strategies too conservative in bull markets, too aggressive in bear markets) rather than a vague underperformance. The best-supported claim for AI self-improvement's value is in the *research/strategy-discovery process* (automating what quant researchers already do, faster/cheaper), not in *live post-deployment trading adaptation* — though no controlled study directly separates these two claims while holding effort/cost constant, which remains the cleanest open evidence gap. Practitioner-side sources (Alpha-GPT 2.0, Man Group) independently converge on human-in-the-loop hybrids as the pragmatic answer, citing diminishing returns to further automation. Indian-market-specific evidence for any of this is essentially absent; the one directly relevant finding (Hiremath & Kumari, 2014) shows the Indian market has historically cycled between efficiency and inefficiency with a trend toward increasing efficiency, which cuts both ways for the adaptation question. New sources: DeMiguel/Garlappi/Uppal (2009, RFS), Bailey & López de Prado (2014), Pardo walk-forward literature, FINSABER (2505.07078), StockBench (2510.02209), AlphaAgent (2502.16789), Alpha-GPT 2.0 (2402.09746), Hiremath & Kumari (2014). Still Stage 0 — no mechanism or architecture selected by this entry.

---

## 15. Final assessment

**What is the strongest evidence that adaptation/self-improvement helps?** ATLAS's controlled, disclosed finding that prompt optimization outperformed fixed prompts in a finance-specific setting, and CogAlpha's chronologically-disciplined evolutionary alpha generation outperforming prior methods on IC/RankIC. Both are Tier B, single-paper, not independently replicated.

**What is the strongest evidence that it does not?** Three independent, methodologically serious lines of evidence converging on the same conclusion: FINSABER's broad/long-horizon LLM-strategy evaluation (advantages deteriorate, systematic regime miscalibration), StockBench's contamination-free finding that most frontier LLM agents can't beat buy-and-hold, and the classical DeMiguel-Garlappi-Uppal result that sophisticated/adaptive portfolio models don't reliably beat naive static diversification because of estimation-error cost. These three are methodologically distinct (different eras, different markets, different mechanisms) and independently reach compatible conclusions, which makes them collectively more persuasive than any single positive result found.

**Is there a convincing static-vs-adaptive comparison in finance?** Yes, in the classical literature — DeMiguel et al. is about as convincing as this kind of comparison gets (peer-reviewed, widely replicated, analytically grounded, 15+ years of scrutiny). For LLM-specific self-improvement mechanisms, no single study is fully convincing on its own terms, but FINSABER comes closest to satisfying the §9 checklist.

**Is there a convincing self-improving-vs-strong-static comparison?** Not one that isolates self-improvement as a variable while holding everything else constant, as would be needed to fully answer the brief's core question. FINSABER and StockBench are the closest approximations, but they compare *finished LLM trading systems* (which may or may not include self-improvement mechanisms) against static baselines, not "the same system with self-improvement on vs. off."

**Is the advantage primarily performance-related, research-productivity-related, or both?** Based on the evidence gathered, more plausibly research-productivity-related than live-performance-related, though this is a judgment based on where the stronger and weaker evidence respectively sit, not a directly-tested claim.

**What happens to the advantage when overfitting is controlled properly?** It shrinks or reverses, consistently across every source that actually controls for it rigorously (Bailey & López de Prado's general result; FINSABER's specific application to LLM trading; the field survey's finding that most published LLM-trading results lack this control at all).

**What happens when the baseline is genuinely strong?** The advantage shrinks or disappears — this is the most consistent single finding of this entire research pass, replicated across the classical portfolio-theory literature and the newest, most careful LLM-trading evaluations, using entirely different methodologies.

**Does the answer appear market-dependent?** Likely, based on the classical asset-pricing point that more distinct factors/structure in the data favor sophistication over naive approaches — but no LLM-specific study tests this across markets rigorously, and Indian equities specifically remain unaddressed.

**Does the answer appear backbone-dependent?** Consistent with the prior session's finding (single- vs. multi-agent results reversing by backbone strength), and StockBench's finding that different frontier models show meaningfully different results against the same static baseline, so yes, plausibly.

**Does the answer appear mechanism-dependent?** Yes, clearly — ATLAS alone shows two different adaptive mechanisms (prompt optimization vs. reflection) producing opposite verdicts within the same paper. Treating "self-improvement" as one mechanism when asking whether it "works" is, at this point across two research sessions, demonstrably the wrong framing.

**What remains genuinely unknown?** Whether a genuinely controlled experiment — same data, same backbone, same cost budget, strong static baseline, proper walk-forward/PBO discipline, self-improvement isolated as the only variable — would show a real, replicable, live-tradeable advantage for any specific self-improvement mechanism. This experiment does not appear to exist yet, in finance, for any mechanism, at any tier of evidence above C.

**How important is this question to our eventual project?** Very. This session's findings sharpen, rather than soften, the caution from the previous self-improvement research: the specific, best-designed comparisons available (not just the general absence of Tier-A evidence, but comparisons that were *deliberately engineered* to be fair and rigorous) point toward strong static baselines being harder to beat than the field's excitement suggests, and toward the more defensible source of AI value being in accelerating research and discovery under human review rather than in continuous autonomous adaptation of live, capital-at-risk decisions. This should be treated as live input to Requirements when that stage begins — not as a decision made now.

---

*This document does not recommend an architecture, a mechanism, or a build decision. It reports the state of the evidence on one specific, previously-unresolved question, including substantial evidence on multiple sides, and records where that evidence runs out.*
