# Project Understanding Report — Stage 0
**AI Trading Agent Research & Engineering Project**
Status: Draft for discussion · Not a Requirements document · Not an architecture proposal

---

## Preliminary note: what I checked and how

Per your instruction, I spent this session verifying the most "load-bearing" claims in the attached research document (the one citing Qwen-style deep research) before writing this report, rather than repeating them uncritically. I did **not** verify every citation — that would take many more sessions — but I checked the claims that were either (a) central to the report's conclusions, or (b) specific enough to be falsifiable (dollar figures, paper titles, repo names). Findings are woven into Section C and flagged explicitly in Section E.

I also confirmed a live Notion connection is available in this session (workspace user: Rishit Babbar). I have **not** created any pages yet — see Section K.

---

## A. My understanding of the project

You want to investigate — not yet build — whether there is a legitimate, evidence-based case for an AI/LLM-driven trading system, and if so, what it should actually consist of. The trigger was a cluster of social-media demos and a few specific open-source repos (TradingAgents, Paperclip, Alex2Learn) that made the idea feel tangible. You are explicitly guarding against the failure mode where an exciting demo becomes a locked-in requirement before anyone has checked whether it's real.

The process you've specified (Waterfall, Stage 0 = Research/Understanding) means my job right now is narrower than "help me design a trading bot." It's: **build an accurate, source-checked picture of the field, so that later requirements are built on verified ground rather than on vibes borrowed from Instagram reels or from another AI's uncorroborated research.**

I think this is a sound instinct given what I found: this field has an unusually high ratio of confident-sounding claims to independently verifiable ones, and it intersects with real financial and security risk if that ratio isn't respected.

## B. My understanding of the field

The attached research report's taxonomy is broadly reasonable. My own synthesis, after checking it:

- **LLM-assisted financial analysis** — using an LLM to summarize/interpret data, no autonomy over decisions or capital. Lowest risk, least controversial, least differentiated from "using ChatGPT to read a 10-K."
- **Single-agent trading systems** — one LLM (or one LLM + tools) makes buy/sell/hold decisions directly, usually against a broker or exchange API.
- **Multi-agent trading systems** — the task is decomposed into role-specialized agents (fundamental/sentiment/news/technical analysts, bull/bear researchers, a trader, a risk manager, a portfolio manager) that pass structured outputs between each other, usually via a graph/orchestration framework (LangGraph is the dominant example in the wild). TradingAgents is the canonical public example.
- **Agent orchestration / "agent company" frameworks** — general-purpose infrastructure for running teams of agents with roles, budgets, approvals, and persistent state (Paperclip). These are **not finance-specific** — I want to be direct about this, see Section E.
- **Self-improving / recursive agents** — a spectrum from "the agent writes down what happened" (logging) through "the agent critiques its own past decisions" (reflection) through "the agent tweaks its own prompts or parameters" through "the agent rewrites its own code or weights." These are extremely different in risk profile and current maturity, and the field's marketing routinely blurs them into one glamorous word: "self-improving."

Asset-class concentration: prediction markets (Polymarket, Kalshi) and crypto dominate the public/open-source ecosystem, for the mundane reason that both have permissive, cheap, well-documented APIs and no KYC-gated brokerage friction. Equities/forex activity is real but happens mostly inside institutions and is far less visible or independently checkable. This matters for you: **if you build anything and want to evaluate it cheaply and legally, crypto and prediction markets are the paths of least resistance — that's a logistical fact, not evidence that they're where the real edge is.**

## C. What the existing research actually establishes

I'll use the evidence tiers from your framework (A = independently verified live performance, B = reproducible public experiment, C = public demo without verified performance, D = creator/project claim, E = marketing/speculation), and note where my own checking upgraded, downgraded, or complicated the supplied document's tier assignment.

**Confirmed and essentially as described:**
- **TradingAgents** (arXiv 2412.20138, Xiao et al., TauricResearch) — real paper, real actively-maintained repo, multi-agent structure as described (fundamental/sentiment/news/technical analysts, bull/bear researchers, trader, risk management, LangGraph-based). The repo is genuinely popular (tens of thousands of GitHub stars) and has continued development into 2026 (v0.2.0, multi-provider support). **This is Tier B**: the paper reports backtested outperformance over baselines, not independently verified live trading. I could not verify the specific "Polymarket data, FRED data" claim in the supplied document as core to the framework — the current repo's own description centers on equities via Yahoo Finance-covered tickers.
- **Paperclip** (github.com/paperclipai/paperclip) — real, active, open-source. Confirmed as a general-purpose "control plane for AI-agent companies" with org charts, budgets, governance, approval gates, and persistent agent state, exactly as described. **Important correction to the supplied document's framing**: Paperclip has no financial or trading-specific functionality at all. It's a generic multi-agent-team orchestration tool most commonly used for coding/dev-agent teams. Its relevance to this project is purely as a pattern reference for governance/budgeting/approval mechanics, not as a finance tool.
- **FinMem** (arXiv 2311.13743, Yu et al., 2023, published at AAAI Symposium Series 2024) — real paper, real repo. Layered memory + character-design architecture as described. **Tier B**: backtested comparison against algorithmic baselines on historical data, not live/real-money performance, despite language in some secondary write-ups implying otherwise.
- **SEC "AI washing" enforcement** — confirmed and well-documented. The SEC's first AI-washing actions were against Delphia (USA) Inc. and Global Predictions Inc. in March 2024, for false/misleading AI claims (Advisers Act and Marketing Rule violations), and the SEC has continued this enforcement pattern since. This is **Tier A** as a regulatory fact, and it directly validates your project's instinct to distinguish claims from evidence — it's not hypothetical caution, it's an active enforcement priority.
- **"When Agents Trade: Live Multi-Market Trading Benchmark for LLM Agents"** (arXiv 2510.11695) — real paper, introducing "Agent Market Arena" (AMA), a live two-month (Aug–Sep 2025) multi-market benchmark across four agent architectures and five LLM backbones. This is genuinely one of the stronger pieces of evidence in the field: it's live, multi-asset, and methodologically aimed at fixing backtesting's flaws. **However**, I need to correct the supplied document's framing: the paper's own results are **mixed, not uniform**, per the abstract and available excerpts — some agent/LLM combinations outperformed Buy & Hold on some assets with elevated volatility from aggressive risk-taking, one memory-based agent showed better risk-adjusted (Sharpe-like) performance on BTC, and the paper's own stated takeaway is that **agent architecture matters more than LLM backbone choice** — not "LLM agents reliably beat the market." I'd call this Tier B (reproducible, disclosed methodology) rather than a clean Tier A "proof of profitability," and I would not characterize it as showing agents "often outperforming" Buy & Hold without qualification.
- **The "Lobstar Wilde" $441K incident** — confirmed real and well-corroborated across many independent outlets (Cointelegraph, CoinCentral, Coin360, local news wire pickups), dated February 21–22, 2026. An OpenAI employee's autonomous Solana trading agent, after losing conversational state and misjudging its own wallet balance, sent ~52.4M of its own memecoin holdings (paper value $250K–$441K depending on valuation moment) to a stranger who had asked for ~$310 worth of SOL. **One correction that matters for your risk thinking**: this was not $441K of "real" capital evaporating — it was the bot's own token that it had presumably minted/accumulated, illiquid enough that the recipient could only realize ~$40–50K by selling it. The headline dollar figure is real but is a mark-to-market/paper-value number, not a cash loss. This is a good illustration of exactly the kind of "impressive-sounding number, less impressive on inspection" pattern your initialization document warns about — and it's a genuine, serious failure mode (state loss + no transaction limits + no human-in-the-loop) worth taking seriously regardless of the exact dollar amount.

**Could not verify as stated / likely inaccurate or conflated:**
- **"A $450,000 loss attributed to an AI agent" on the Base blockchain** — I could not find a source matching this specific claim. What I did find in the same topical space: (1) a widely reported story of a crypto whale losing ~$20.4M trading a basket of "AI agent" *tokens* (a portfolio-allocation loss by a human, not an autonomous agent's own trading failure) with a sub-component loss of $381K on one token (MAICRO) and other sub-losses in the ~$500–900K range on individual tokens within that portfolio; and (2) a separate widely-cited (but different) figure of "$450 million" in Q1 2026 on-chain fees attributable to AI agents generally. It's plausible the source research conflated one of these, or that there's a genuine $450K incident I simply didn't surface in a few searches. **I'm flagging this as unverified rather than asserting it's false** — but I would not cite it as a discrete, confirmed incident without a direct primary source.
- **The r/algotrading "24,000+ live crypto trades, deterministic beat every LLM configuration" post** — I ran multiple targeted searches and could not locate this specific thread or a matching write-up. This doesn't mean it doesn't exist (Reddit content is poorly indexed and often gets deleted/removed), but I cannot currently corroborate it, and the four "failure modes" attributed to it (protection-rule overrides, latency-induced stale decisions, inconsistency on identical inputs, uncalibrated confidence) are individually plausible and consistent with other literature I *did* find (e.g., "TrustTrade," arXiv 2603.22567, which independently documents LLM trading agents showing "pronounced heterogeneity" and instability even under identical market conditions), but the specific 24,000-trade case study should be treated as **Tier D at best (unverified anecdote) until we locate the primary source**, not as established evidence, however useful its narrative is.

**Not independently checked this session (time-boxed), flagged for later verification:** Kronos, TradeFM, AlphaAgents, FLAG-TRADER, the Huxley-Gödel Machine paper, AgentTrading, the specific arXiv IDs in the reference list at the end of the PDF (several — e.g., 2605.19337, 2601.04583 — use identifiers I have not confirmed resolve to real papers; arXiv's YYMM numbering makes these *plausible* given the current date, but plausible ≠ verified).

## D. My independent conclusions

1. **The core architectural pattern (multi-agent, role-specialized, LLM-driven analysis feeding a trading/risk layer) is real, actively researched, and not vaporware.** TradingAgents and the AMA benchmark are genuine, serious work. This is a legitimate field of study, not pure hype.
2. **"Does this reliably make money" and "does this architecture exist" are two completely different questions, and only the second has a solid yes.** The best available live evidence (AMA/"When Agents Trade") shows mixed, architecture-and-asset-dependent results over a two-month window — not a demonstrated, robust, repeatable edge. Two months is also, frankly, a very short evaluation horizon for a claim about "profitability."
3. **The weight of practical/adversarial evidence (documented instability, hallucination, inconsistency on identical inputs, and the Lobstar Wilde incident) suggests LLMs are currently more trustworthy as an analysis/reasoning layer than as an unsupervised execution layer.** This matches a pattern I'd have predicted independently from how LLMs behave generally (non-determinism, confident wrongness, sensitivity to framing) — it's not just this document's spin.
4. **Self-improvement, as currently implemented anywhere I found, means "memory + reflection + prompt/parameter tuning," full stop.** Genuine code-modifying or weight-modifying self-improvement in a live trading agent is theoretical/aspirational (Huxley-Gödel Machine is a general meta-learning concept paper, not a trading system) and I found zero credible evidence of a safe, production-grade self-modifying trading agent. If your original vision assumed something closer to "the system rewrites its own strategy code," that assumption is currently unsupported by anything real in the field.
5. **The security and regulatory picture is not exaggerated — if anything it deserves more weight than the marketing side of this space gives it.** Prompt injection, credential exfiltration, and the "lethal trifecta" (excessive agency + untrusted input + ability to exfiltrate) are active, documented attack classes against exactly this kind of system, and the SEC is actively enforcing against overstated AI claims in finance specifically. Any eventual system that touches real capital needs this treated as a first-class design constraint, not an afterthought.
6. **Paperclip is a useful pattern reference, not a finance tool.** If org-chart/budget/governance/approval concepts end up in your eventual architecture, that will come from *learning from* Paperclip's design, not from *depending on* Paperclip's codebase.
7. **The strongest, most defensible starting hypothesis I can currently support is narrower than "self-improving autonomous trader":** something like *"LLM-based multi-agent analysis can plausibly assist human or semi-autonomous decision-making in narrow, well-instrumented markets, but current evidence does not support unsupervised, self-modifying, capital-at-risk autonomy as a near-term goal."* That's a conclusion the Requirements stage should test against, not something to accept uncritically either — it's my read of the evidence as of today, and it could be wrong.

## E. Where I disagree with the supplied research

- It presents the AMA/"When Agents Trade" results with more confidence and uniformity ("often outperforming Buy & Hold") than the paper itself claims (mixed, architecture-dependent, elevated-volatility-in-some-cases results).
- It states the Base-blockchain "$450,000 loss" as an established fact; I could not confirm this specific claim and suspect possible conflation with a different, larger, and structurally different story (a whale's $20.4M loss trading a *portfolio* of AI-branded tokens).
- It presents the r/algotrading 24,000-trade case study as a documented, citable data point; I could not locate it and would downgrade it to "unverified anecdote consistent with other documented instability findings" until we find the primary source.
- It frames Paperclip as if it sits alongside TradingAgents as a finance-adjacent reference; in reality Paperclip is domain-agnostic and has no special relevance to trading beyond generic multi-agent orchestration patterns.
- It doesn't flag its own citation list's oddities — several reference-list arXiv IDs are things I have not verified resolve to real papers, and a research document that hasn't itself audited its bibliography shouldn't be treated as pre-vetted.
- More generally: the document is well-organized and mostly well-sourced on its central claims (TradingAgents, FinMem, SEC enforcement, the Lobstar Wilde incident all check out), but it has a mild but consistent bias toward stating things more definitively than the underlying sources do — which is exactly the failure mode your initialization document told me to watch for.

## F. What you may be misunderstanding (being direct, as instructed)

- I don't see evidence that you're currently over-anchored on any single architecture — your initialization document explicitly and repeatedly guards against this, which is good practice, not a symptom.
- The one place I'd gently push back: the phrase "self-improving trading agent" as an initial framing may be doing more conceptual work than the evidence supports. It's worth entering the Requirements stage having explicitly separated "I want a system that gets better over time through disciplined evaluation and iteration by us" (very achievable, standard MLOps/quant-research practice) from "I want a system that improves itself with no human in the loop" (essentially unsupported by anything verified in this field today). These sound similar but imply very different architectures, risk profiles, and engineering effort.
- Worth naming explicitly: nothing in the verified evidence suggests that *multi-agent* architectures outperform *simpler* single-agent or even purely deterministic/quantitative systems. The field's enthusiasm for multi-agent "trading firm" mimicry is largely aesthetic/intuitive, not evidence-driven — the TradingAgents paper itself doesn't benchmark against a simpler analyst+executor baseline. This is a real gap you should hold onto going into Requirements: don't assume "more agents, more roles" is inherently better just because it's what's fashionable right now.

## G. What remains unknown

- Whether the "24,000 trades" deterministic-vs-LLM comparison exists as described, and if so, what its actual methodology was.
- What Kronos, TradeFM, AlphaAgents, and FLAG-TRADER actually are and whether they're as significant as the supplied document suggests (not yet checked).
- Whether there is *any* Tier A evidence (independently verified, real-capital, live, audited) anywhere in this field — I have not found one in this session, and I suspect the honest answer may be "no," but I haven't exhausted the search.
- What "prediction markets" (Polymarket/Kalshi) specifically offer as an evaluation environment that traditional markets don't, beyond API accessibility — is there something structurally different about how LLMs handle discrete, resolvable, binary-outcome markets vs. continuous price series?
- Whether your intended target (if any) is closer to "research/analysis assistant for a human trader" vs. "autonomous capital-deploying system" — this is currently unresolved and matters enormously for everything downstream.
- What data/capital/regulatory constraints you're actually operating under (personal account? entity? jurisdiction? risk tolerance?) — none of this has been stated yet and it's foundational to Requirements.

## H. What needs further research before Requirements

- A dedicated pass on Kronos, TradeFM, AlphaAgents, FLAG-TRADER, AgentTrading, and the Huxley-Gödel Machine paper, with the same verify-before-repeat standard applied here.
- A search specifically for *any* Tier A (independently audited, live, real-capital) evidence in this space, including outside the sources already supplied (this is the single most important open question for deciding whether this project is worth pursuing as anything beyond a research/analysis tool).
- A deeper look at the security literature (prompt injection against agentic finance tools specifically, the "lethal trifecta" framing, and how existing frameworks like MCP handle or fail to handle this).
- A look at what deterministic/classical quant approaches already achieve in the same problem space, so any LLM-based approach has a real baseline to be measured against (this connects to the gap noted in Section F — nobody in the literature seems to benchmark multi-agent LLM systems against boring, well-tuned deterministic systems).
- Regulatory research specific to your actual likely jurisdiction and structure (personal trading account vs. anything more formal), since MiFID II / DORA-style obligations mentioned in the supplied document are EU-specific and may not be what applies to you.

## I. Existing projects worth understanding (not recommendations)

- **TradingAgents** (TauricResearch) — the most substantive, actively-maintained, peer-reviewed-adjacent open reference implementation of the "specialist team" pattern. Worth studying in depth regardless of whether it's ever used.
- **FinMem** — smaller and older, but a clean, well-cited reference for a *specific* subproblem (layered memory + agent "character") that's cited by nearly everything else in this space.
- **Agent Market Arena / "When Agents Trade"** — not a project to build on top of, but the most methodologically serious *evaluation framework* I found; worth understanding closely because it defines what a credible evaluation of a system like this would need to look like.
- **Paperclip** — worth understanding as a generic orchestration/governance pattern (budgets, approvals, persistent state, org structure), explicitly *not* as a finance tool.
- **TrustTrade** (arXiv 2603.22567) — newly surfaced during my verification pass, not in your original list; directly relevant because it's an independent study of exactly the instability problem your supplied document raises, with a proposed (partial) mitigation via selective consensus and deterministic temporal signals. Worth adding to the research trail.

## J. Current project assumptions (as I currently read them)

| Assumption | Status |
|---|---|
| LLM-based multi-agent systems can generate real trading alpha | **Weakly supported** — one live benchmark shows mixed, non-uniform results over a short (2-month) window; no Tier A evidence found |
| Multi-agent (specialist team) architectures outperform simpler architectures | **Unsupported / not tested** — no comparative evidence found anywhere, including in the flagship papers |
| "Self-improvement" implies the system can safely modify its own strategy/code over time | **Weakly supported at best** — real implementations top out at memory/reflection/prompt-parameter tuning; code/weight self-modification is theoretical |
| Prediction markets / crypto are good target environments for early experimentation | **Supported, but for logistical reasons (API access, low friction), not because they're where the strongest evidence of profitability lives** |
| Orchestration frameworks like Paperclip are relevant building blocks for this specific project | **Weakly supported** — relevant as a governance/pattern reference, not as a finance-specific dependency |
| Security/regulatory risk is a real, near-term constraint rather than a distant concern | **Supported** — confirmed active SEC enforcement and a well-documented, serious agentic-security literature |
| The eventual system needs to assume unreliable models/data/APIs/execution ("foolproof" framing) | **Supported by the evidence surveyed** — multiple independently-documented failure classes (hallucination, inconsistency, runaway agents, prompt injection) exist right now, not hypothetically |

## K. Documentation model (Notion now, Obsidian-portable later)

I have a live Notion connection (confirmed this session). Proposed approach, to be confirmed with you before I build anything:

- **Structure**: a small number of top-level databases rather than many freeform pages — e.g. `Research Log`, `Decision Log`, `Assumption Register`, `Open Questions`, `Project Glossary` — each as a Notion database with consistent properties (Date, Source(s)/URL(s), Evidence Tier where relevant, Status, Tags, Linked items).
- **Portability discipline**: every entry written in plain Markdown-compatible formatting (headings, bullet lists, tables, inline links) — no Notion-only blocks (no synced blocks, no databases-as-the-only-copy-of-critical-content, no heavy use of Notion-specific formulas/rollups for anything load-bearing). Anything structurally important should be reconstructable as flat Markdown files with YAML-style frontmatter if exported later — which maps cleanly onto an Obsidian vault.
- **Provenance**: every research/decision entry carries an explicit source, access date, and evidence tier, consistent with Sections 12 and 18 of your initialization document.
- **What I have *not* done**: created any pages or databases yet. This report itself is intentionally staying in this session as a Markdown file until you confirm you want it (and the structure above) instantiated in Notion.

## L. Understanding-gate questions (before entering Requirements) — ANSWERED 2026-08-29

1. **Target system:** Fully autonomous, capital-deploying system is the *ultimate* target. Human-in-the-loop / paper-trading stages are acceptable as *intermediate validation*, not as a quiet permanent substitute for autonomy.
2. **Capital, account, jurisdiction:** India. Indian equities. Personal trading account, personal capital. Broker, exact capital, and execution infrastructure not yet decided.
3. **Definition of success:** Sustainable profitability over an appropriately defined evaluation period, under realistic conditions and after costs. Exact quantitative definition (transaction costs, taxes, slippage, drawdown, benchmark comparison, out-of-sample performance, regime robustness) explicitly deferred to Requirements — not to be prematurely finalized.
4. **Current evidence gap:** Accepted and understood. No Tier-A evidence exists. Project continues anyway, as a research bet, with the explicit understanding that a negative-evidence outcome should change direction rather than be ignored.
5. **Human-in-the-loop vs. autonomous:** Ultimate target remains full autonomy. Human-loop stages are allowed as research/validation waypoints but must not be allowed to quietly become the permanent destination just because autonomy is hard.
6. **Documentation:** Start immediately, continuously, not gated on Requirements starting. (Status: Notion write access is currently blocked — see Session 2 log below. Documentation is being kept in this file in the interim.)
7. **Qwen material:** The attached PDF is the initial research corpus, not the complete truth. More material may arrive later and will be independently evaluated on the same terms — not summarized uncritically.
8. **Verification depth:** No time/effort box. Stage 0 ends when there is a sufficiently deep *shared* understanding to write meaningful requirements — not when a large volume of material has simply been collected. Priority research areas specified: what's been built, what works/doesn't, evidence for/against LLM trading alpha, autonomous trading architectures, multi-agent systems, self-improvement mechanisms, failure modes, realistic evaluation methodology, **Indian equity-market constraints**, autonomous execution risk, security risk, existing systems, and research gaps.

**North-star objective (as stated 2026-08-29):** Build, eventually, a fully autonomous trading system whose ultimate purpose is to generate sustainable profit using personal capital in Indian equities. How that is accomplished — architecture, models, agent structure, strategies, data sources, infrastructure, self-improvement mechanisms, execution system, technology stack — remains fully open.

---

## M. Research thread: Indian regulatory environment for retail algorithmic/AI trading (opened 2026-08-29)

This thread did not exist in the original research corpus (which was written as if for a generic/US-centric market) and became first-priority the moment jurisdiction was fixed to India. Findings below are from **primary sources** (SEBI circular text, NSE FAQ/circulars) fetched directly, not secondary summaries, except where noted.

### M.1 The governing framework

- **SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013** ("Safer participation of retail investors in Algorithmic trading"), issued **February 4, 2025**. Original effective date August 1, 2025; extended twice (to October 1, 2025, then to **April 1, 2026**, per SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/132) with a phased broker-compliance glide path. **As of today (2026-08-29), the framework is fully live and mandatory** — this is current operating reality, not a future consideration.
- Full circular text retrieved and read directly (source: sebi.gov.in, mirrored at ricago.com/assets/front/base/file/file_management/3191.pdf).

### M.2 The critical distinction: "Algo Provider" vs. "Tech-savvy retail investor"

The circular creates two structurally different actors:

**Algo Provider** (Section I(a), III): any third-party fintech/vendor providing the algo-trading *facility* to *other* clients via a broker's API, acting as the broker's agent. Subject to: exchange empanelment, broker due diligence, mandatory monthly mock trading sessions, hosting on the broker's own servers, and — critically — if the algo is **black-box** (Section V(ii): "logic is not known to the user and is not replicable") — **mandatory SEBI Research Analyst (RA) registration** plus a maintained, exchange-confirmed research report per algo, re-registered on any logic change.

**Tech-savvy retail investor** (Section I(c)): a retail investor who builds their *own* algo using their *own* programming knowledge and runs it for themselves and, per the circular's explicit text, immediate family only (self, spouse, dependent children, dependent parents) — *not* other investors. Confirmed directly from the **NSE FAQ** (nsearchives.nseindia.com, FAQ_Retail Algo_03112025_NSE.pdf, fetched directly): this actor —
- is **not** required to become an Algo Provider or hold an RA license,
- is **not** required to host on the broker's servers (self-hosts instead, using their own static IP),
- is **not** required to join mandatory monthly mock trading sessions,
- bears the P&L outcome themselves, since — per the FAQ verbatim — "the responsibility of the outcome (Profit/Loss) is with the Tech-savvy client itself... and the RMS is the responsibility of the Trading Member [broker]."
- is only required to register the algo with the Exchange (via broker) if order rate crosses an exchange-specified threshold (commonly cited across secondary sources as **10 orders/second**, though the precise number is set by a *separate* NSE/Broker Industry Standards Forum circular under the SEBI circular's authority — I have not yet pulled that specific circular to confirm the number at the primary-source level).

**Working interpretation (mine, not a legal ruling):** A self-built, self-hosted LLM-driven trading system, used solely for personal (and optionally immediate-family) capital, placed via a broker's direct API under the order-rate threshold, structurally reads as "tech-savvy investor," not "Algo Provider" — and on this reading would likely **not** require an RA license, even though an LLM's decision process is arguably the most "black-box" thing there is.

**Explicit caveats — do not treat this as settled:**
- This is a reading of text written with fixed/proprietary rule-based products in mind, before LLM-based agents were a regulatory consideration. Nobody has tested whether a regulator would apply "black box" language to a non-deterministic LLM agent the same way as to an undisclosed static ruleset.
- The specific 10-OPS threshold number needs primary-source confirmation (traced to an NSE/ISF circular, not yet fetched).
- Practical implementation requirements apply regardless of Algo Provider/tech-savvy status: **static IP whitelisting, OAuth-based auth, and 2FA are now mandatory for all API order placement** (confirmed via Zerodha's own Kite Connect developer forum; went live ~April 1, 2026 and reportedly broke bots running on dynamic-IP cloud platforms like Heroku/Railway that hadn't set up a static egress IP).
- Market orders and IOC orders are disallowed via algo in at least the commodity segment (per NSE circular NSE/MSD/67753) — equities-segment specifics not yet separately confirmed.

### M.3 Broker implementation, confirmed from primary broker documentation (2026-08-29, Session 3)

Pulled directly from Upstox's own developer documentation and developer community, corroborated by the Zerodha Kite Connect developer forum:

- **The 10-orders-per-second (OPS) threshold is confirmed at the primary-source level** (Upstox's own docs state it explicitly as the trigger for mandatory SEBI/Exchange algo registration) — this closes the gap flagged in the previous session.
- **Static IP is now mandatory for all order-placement API calls** (place/modify/cancel/GTT/exit) as of April 1, 2026, across brokers; read-only endpoints (holdings, positions, quotes) remain exempt. A registered static IP can only be changed once per calendar week, and doing so invalidates the current access token.
- Multiple brokers (Zerodha, Fyers, and others on certain OMS platforms) were reported by their own developer communities as still catching up on enforcement during the rollout window, causing real, reported disruption for retail bots running on dynamic-IP cloud hosts that hadn't set up a static egress IP in time.
- Fyers' own primary documentation not yet pulled directly (still open).

### M.4 Not yet researched (carried into backlog, Section H)

- The exact NSE/ISF circular setting the numeric OPS threshold.
- Tax treatment of frequent/automated trading in India (business income vs. capital gains classification, and how that classification itself can depend on trading frequency/intent — this could materially affect the "success/profitability" definition from Section L Q3).
- Whether individual broker terms of service (Zerodha, Upstox, Fyers, etc.) impose restrictions on AI/LLM-driven order generation *beyond* SEBI's floor, given brokers carry legal exposure as "principal" under this framework.
- Margin, leverage, and intraday-vs-delivery rules as they interact with an autonomous system's risk controls.
- Whether SEBI or any Indian regulator has issued *any* guidance specifically addressing generative-AI/LLM-based (as opposed to classical rule-based) trading systems.
- Fyers-specific primary documentation, and a direct read of broker Terms of Service (as opposed to API technical docs) for AI-specific restrictions.
- Indian taxation treatment of frequent/automated trading (business income vs. capital gains classification).

---

## N. Session 3 (2026-08-29): Research Question A revisited — LLM trading alpha, deepened

The original Stage 0 report's conclusion ("no Tier-A evidence, mixed Tier-B results from AMA") holds up, and now has much stronger methodological backing from a source not previously known to this project.

**Core new source: "The Alpha Illusion: Reported Alpha from LLM Trading Agents Should Not Be Treated as Deployment Evidence"** (arXiv 2605.16895, May 2026). This is a methodological critique paper arguing that reported LLM-trading alpha must rule out three confounders before being treated as meaningful: **(1) temporal contamination** — backtest windows overlapping a model's training/knowledge-cutoff data, letting memorized tickers/prices/narratives substitute for genuine reasoning; **(2) real-world execution friction** — commission, spread, market impact, and token cost, often excluded from "gross" backtest numbers; **(3) researcher degrees of freedom** — post-hoc choices of asset, window, and metric that inflate apparent performance. It cites a contamination-free evaluation (Chen et al. 2025) finding that most LLM agents struggle to consistently beat buy-and-hold once these are controlled. A second, independent source — **KTD-Fin** (arXiv 2605.28359) — raises the identical knowledge-cutoff contamination concern and proposes a data-masking evaluation protocol specifically to address it.

**Countervailing evidence found, held in tension rather than resolved:** Several backtest-based papers report substantial outperformance — e.g. a PeerJ multi-agent framework claiming 53.87% annualized return vs. a 26.08% buy-and-hold benchmark with statistically significant tests, and AlphaQuanter's RL-trained single-agent reporting similar outperformance. **Applying the Alpha Illusion paper's own framework, none of these should be read as deployment-grade evidence** unless independently shown to be contamination-free and friction-adjusted — which, on the information available, they have not been shown to be.

**Updated conclusion:** This strengthens rather than weakens the project's founding skepticism. The field is now producing its own internal methodological critique of exactly the failure mode this project was already worried about (impressive backtest numbers that don't survive contact with contamination/friction checks). The Alpha Illusion paper should be treated as a core reference for how *any* future internal backtest of our own eventual system must be evaluated — not just as a critique of other people's papers.

## O. Session 3 (2026-08-29): Research Question B revisited — does multi-agent complexity help? (contradictory controlled evidence found)

The original Stage 0 report flagged this as an "evidence gap — no controlled comparison found." That needs to be revised: **controlled comparisons now exist, and they contradict each other.**

- **AlphaQuanter** (arXiv 2510.14264) ran an explicit ablation ("RQ1: Single or multi-agent, which is better?") holding data sources and 7 different LLM backbones constant, comparing a single-agent scaffold against the TradingAgents multi-agent architecture. **Result: except for GPT-4o, the single-agent framework consistently outperformed the multi-agent framework**, particularly on annualized return — the authors attribute this to multi-agent debate injecting noise/amplifying hallucination in smaller models. A companion efficiency table found the multi-agent baseline cost ~6.7x more tokens per decision than the single-agent approach, for *worse* performance — a rare directly-quantified example of a "complexity tax."
- **"LLM-Powered Multi-Agent System for Automated Crypto Portfolio Management"** (arXiv 2501.00826) found the *opposite* in a controlled ablation across three backbones (GPT-4o, GPT-5, Claude Sonnet 4.5) in a 52-week crypto backtest: multi-agent consistently beat single-agent under all three backbones.
- **"Single-agent or Multi-agent Systems? Why Not Both?"** (arXiv 2505.18286, general-purpose, not finance-specific) found that the benefit of multi-agent systems over single-agent systems *diminishes as the underlying LLM's own capability improves* — a plausible reconciling hypothesis for the two contradictory finance results above (different backbone strength → different winner), but this reconciliation has not itself been tested in the trading domain and should not be treated as confirmed.
- **"Toward Expert Investment Teams"** (arXiv 2602.23330) independently states that "agent-level ablation studies remain relatively underexplored" in this literature, corroborating the original evidence-gap framing even as the picture gets more granular.

**Updated conclusion:** Do not adopt either "multi-agent is better" or "single-agent is better" as a working assumption. The honest state of evidence is: *controlled comparisons exist, they disagree, and the disagreement may be backbone-capability-dependent* — which, if true, means the right answer for this project depends on which LLM(s) end up being used, not on architecture in the abstract. This should be tested empirically against our own eventual candidate backbones during Requirements/Design, not assumed from any single paper.

## P. Session 3 (2026-08-29): Research Question D — grounding the autonomy-level taxonomy

Rather than inventing a taxonomy from scratch, a finance-specific framework was located: **"SoK: Security of Autonomous LLM Agents in Agentic Commerce"** (arXiv 2604.15367) proposes four levels specifically for financial agents:

- **Level 0 (Advisory):** agent analyzes and recommends; all actions taken by humans.
- **Level 1 (Supervised):** agent proposes and executes pre-approved transaction types within strict limits; humans approve exceptions.
- **Level 2 (Delegated):** agent independently executes a broad range of transactions within policy constraints; humans review periodically (not per-transaction).
- **Level 3 (Fully Autonomous):** agent independently manages the portfolio/operation with no per-transaction human oversight; humans set only high-level goals/constraints.

This is a cleaner, domain-relevant alternative to a generic 6-level SAE-driving-style taxonomy (several generic versions of which were also found, e.g. arXiv 2512.11893, arXiv 2605.12105) — those exist and are reasonable, but were written for coding agents, cybersecurity agents, or general business agents, not finance specifically. **Recommendation (not a decision):** adopt the SoK paper's 4-level finance-specific framework as the working vocabulary for this project's autonomy-related discussions going forward, reserving the option to add a "Level 4 — self-modifying" tier on top given this project's specific interest in self-improvement (the SoK framework, like most agent-autonomy taxonomies found, treats "autonomous execution" and "self-modifying strategy" as the same top level, which this project's own Section 13 terminology explicitly wants kept separate).

**Note on your original target:** per your answer to gate question 1/5, the ultimate target is Level 3 (Fully Autonomous) in this framework, reached via staged validation through Levels 0–2. This maps cleanly onto what you already described; it's now grounded in a citable source rather than an internally-invented scale.
