# NetOS — AI Trading Agent Research & Engineering Project

**⚠️ Work in progress.** This is an active research project, not a finished product. Nothing here is financial advice, no trading edge has been demonstrated, and no real capital is being traded. Live execution is intentionally gated and not yet built. Treat every result as infrastructure verification only.

---

## What this project is

NetOS is a research-first effort to build an **autonomous AI trading agent** for **Indian equities using personal capital**, starting from the question raised by social-media demos (Instagram reels about "self-improving AI trading agents" / Grok-powered Polymarket agents) and validated against actual research rather than hype.

The original ideation and reverse-engineering work that shaped this project is documented in:

> `/Users/yoboxo/Developer/Developer/Claude Data/NetOS/Reverse Engineer Trading Agent.md`  
> ChatGPT conversation analyzing four Instagram reels about autonomous AI trading agents, TradingAgents (TauricResearch), Paperclip, and Alex2Learn — consolidated into the architecture that NetOS implements today.

Key principles carried over from that ideation:

* **The LLM should not have unrestricted control over a broker account.** A deterministic risk/execution layer sits between the intelligence layer and any order placement.
* **Research before build.** Stage 0 verified the field's claims (TradingAgents, FinMem, Agent Market Arena, SEC "AI washing" enforcement, the Lobstar Wilde failure incident, etc.) before writing architecture. The field has more confident-sounding claims than independently verified ones; NetOS is built with that skepticism baked in.
* **Self-improvement, if any, happens offline first.** Any self-improvement mechanism is confined to an isolated research/backtesting environment and can never touch live capital directly.

## What it will be able to do (phased)

| Phase | Capability | Status |
|-------|-----------|--------|
| Slices 0–8 (done) | Deterministic historical data ingestion, validation, normalization, versioning; Tier-1 equal-weight baseline; Tier-2 momentum baseline; offline research harness with split/contamination guards; decision journal & observability; order state machine & reconciliation; simulated broker; deterministic risk engine & sizing | **Complete** |
| Slice 9+ (planned) | Statistical hardening of the evaluation harness | In progress |
| Slice 10+ (planned) | Console / dashboard for decision review | Not started |
| Future | LLM-assisted trade proposal (Plane 2), evaluated deterministically against baselines before promotion | Planned |
| Future | Self-improvement loop confined to offline research; candidate artifacts promoted only through human-gated review | Planned |
| Future | Staged autonomy progression (Level 0 advisory → Level 3 fully autonomous) per operator decision | Planned |
| Future | Live execution path, technically designed but gated closed until regulatory conditions (SEBI algo framework, static IP, 10 OPS threshold, broker ToS review, etc.) are satisfied | Not started; gated |

**Not built and not claimed:** live broker connection, real-money trading, LLM-driven execution, demonstrated alpha, or any self-modifying code in production.

## Architecture at a glance

The system is five architecturally separated planes plus an isolated research environment:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ PLANE 0 — GOVERNANCE (operator-owned)                                   │
│ Autonomy level · Risk constraints · Instrument universe · Kill switch   │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │ read-only to planes below
┌────────────────────────────────▼─────────────────────────────────────────┐
│ PLANE 1 — DATA                                                          │
│ Ingestion → Validation/staleness → Normalization → Feature formation    │
│ → Decision-log store (every decision's inputs recorded by version)      │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────────────┐
│ PLANE 2 — INTELLIGENCE (replaceable "brain")                             │
│ Analysis → Candidate trade + confidence signal. Versioned. Swappable.    │
│ Never has execution authority. Starts deterministic; LLM-assisted later. │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │ candidate trade + rationale (NOT an order)
┌────────────────────────────────▼─────────────────────────────────────────┐
│ PLANE 3 — RISK & EXECUTION (deterministic, non-LLM)                      │
│ Cost estimation → Risk validation → Position sizing → Sanity checks      │
│ → Order generation → Broker interface → Confirmation → Reconciliation    │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────────────┐
│ PLANE 4 — OBSERVABILITY & EVALUATION                                     │
│ Outcome logging → Reconciliation vs. broker truth → Evaluation harness   │
│ (offline, regime-segmented, contamination-checked) → Reporting           │
└─────────────────────────────────────────────────────────────────────────┘
```

A sixth, fully separate **Research & Backtesting environment** consumes the same Plane 1 data contracts, produces candidate Plane 2 artifacts, and has **no write access to Plane 3, Plane 0, or any live broker**. Self-improvement experiments live only here.

## Risk & safety posture

* Plane 3 (risk & execution) is deterministic, non-LLM, and has hard veto power over Plane 2. It cannot be overridden by the intelligence layer.
* Fail-closed by default: missing/stale data, malformed model output, broker failure, connectivity loss, and abnormal markets all route to "no new action."
* Every decision is reconstructable after the fact: data version, code version, config, rationale, risk checks, broker confirmation, and realized cost are all logged.
* Live execution is gated behind regulatory closure (SEBI retail algo framework, static IP, OAuth/2FA, broker ToS review for AI-driven order generation) — not merely a technical decision.

## Current status

Slices 0–8 are complete:

* **Data pipeline** — CSV ingestion (Bhavcopy), validation, split adjustment, deterministic versioning, JSONL persistence
* **Tier-1 baseline** — equal-weight BUY/HOLD/SELL advisory candidates
* **Tier-2 momentum** — 12-1 momentum strategy
* **Slice 5 research harness** — offline deterministic replay, simulated research accounting, cost integration, contamination guards
* **Slice 6** — deterministic Risk Engine (RR-1..RR-9, fail-closed), sizing, simulated broker
* **Slice 7** — order state machine, reconciliation hardening, crash recovery
* **Slice 8** — durable hash-chained decision journal & observability

Test coverage: ~787 unittest tests passing, 0 architecture-lint violations.

**Explicitly not yet present:** LLM integration, live broker, credentials, live execution path, demonstrated profitability. A passing run is infrastructure verification, not evidence of alpha.

## Setup & validation

Python 3.11 or newer; no runtime third-party dependencies.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ruff check .
ruff format --check .
mypy domain shared
python -m shared.arch_lint.cli .
```

`python run_tests.py` also runs the full pytest suite. The CI workflow runs these checks.

## Project structure

- `domain/models/`: validated domain objects, serialization and order transitions
- `data/adapters/`, `validation/`, `normalization/`: CSV ingestion, validation, split adjustment, deterministic versioning and JSONL persistence
- `data/features/`: permitted universe and immutable, attributable feature snapshots
- `intelligence/baseline/`: Tier-1 equal-weight BUY/HOLD/SELL advisory candidates
- `intelligence/tier2/`: Tier-2 momentum strategy
- `shared/costs/`: Decimal cost inputs, versioned schedules and pure calculations
- `shared/time/`, `versioning/`, `arch_lint/`: common utilities and architecture checks
- `simulation/`: research/simulation orchestrator (strategy → risk → sizing → broker → portfolio)
- `tests/`: cumulative regression coverage and cross-slice integration tests
- `docs/`: design records, component contracts, source history and merge audit
- `scripts/`: utility scripts

The primary historical path is:
`load_bhavcopy_csv` → `normalize_bhavcopy_batch` → JSONL persistence (optional) → `build_feature_snapshots` → `Tier1EqualWeightBuyHold.generate_candidate_trades`.

All consumers use the same canonical domain objects. `CostModel.estimate` accepts an explicit hypothetical quantity and price; advisory strategy weights never become executable quantities automatically.

See `docs/data-ingestion.md`, `docs/feature-context.md`, `docs/baseline-tier1.md`, `docs/cost-model.md`, `docs/risk-engine.md`, `docs/sizing.md`, `docs/simulated-broker.md`, `docs/research-harness.md`, `docs/research-protocol.md`, `docs/decision-journal-observability.md`, and `docs/slice-1-4-reconciliation.md`.

## References

* Original ideation chat (source of the project vision): `Reverse Engineer Trading Agent.md`
* `docs/00-Project-Understanding-Report.md` — Stage 0 research verification report
* `docs/04-Stage2-System-Architecture-v0_1.md` — system architecture (Planes 0–4, ADRs, build philosophy)
* `docs/slice-status.md` — cumulative slice status and test counts

---

**Bottom line:** NetOS is a serious, research-grounded attempt to answer whether an LLM-based multi-agent system can generate real trading alpha in Indian equities. It starts boring and deterministic, keeps the LLM out of the execution path, and only adds complexity when a rigorous, contamination-controlled evaluation justifies it. It is a work in progress — expect the scope, architecture, and conclusions to change as evidence accumulates.