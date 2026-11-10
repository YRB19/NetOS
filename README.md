# NetOS — Autonomous Indian-Equities Trading System (Research & Engineering)

NetOS is a personal, single-operator project: a staged build towards a fully autonomous,
capital-deploying trading system for Indian equities, under strict Waterfall discipline
(Stage 0 research → 1 requirements → 2 architecture → 3 detailed design → slice-by-slice build).
It is not a product, a signal service, or financial advice.

> **Nothing here has been shown to be profitable, broker-compatible, or ready for live capital.**
> All results are simulation/backtest on synthetic or offline data. Passing tests proves engineering
> correctness, not trading skill.

## Status

| Area | State |
|---|---|
| Stages 0–3 (research, requirements, architecture, design) | Complete (`docs/00`–`05`) |
| Implementation | Slices 0–12 complete; Slice 13+ not started |
| Execution | Simulated broker only. No live broker adapter, no credentials, no real capital |
| AI component | Bounded confidence-only overlay on deterministic Tier-2; stub provider; Slice 12 synthetic evaluation = Inconclusive |
| Operator console | Local-only (127.0.0.1), read-only, no trading authority |
| Verification | 1121 backend tests + 43 frontend tests pass; import-isolation lint: 0 violations |

## How to run it

See **README-DEV.md**. Short version:

```bash
cd ~/Developer/NetOS && source .venv/bin/activate
python tools/build_ui_demo_fixtures.py --out ./.demo-artifacts
python -m console_api --root ./.demo-artifacts
# open http://127.0.0.1:8765/   (Ctrl-C to stop)
python -m unittest discover -s tests -t .      # run the test suite
```

## Architecture in brief

Five planes plus an isolated research environment:

0. Governance — operator-owned limits, autonomy level, kill switch
1. Data — ingestion, validation, staleness, normalization, feature snapshots
2. Intelligence — replaceable brain (Tier-1 buy-and-hold, Tier-2 12-1 momentum, AI overlay); emits `CandidateTrade`, never orders
3. Risk & Execution — deterministic, non-LLM; risk engine RR-1..9, sizing, order lifecycle, reconciliation, broker abstraction
4. Observability — hash-chained decision journal, audit trail
5. Research — walk-forward harness, contamination guards, experiments; no path to live execution

Principles: baseline rigor before AI; self-improvement confined to research and unable to touch risk
rules or the kill switch; plane isolation enforced by an import-graph lint in CI; fail closed.

## Not done / open gates before any live use

- Indian tax classification of frequent/automated trading.
- Broker Terms of Service: Zerodha, Upstox and FYERS restrict fully automated trading contractually.
- Confirmation of the NSE/ISF order-rate circular and equities order-type rules.
- Operator decisions: numeric exposure/drawdown limits, latency bounds, profitability definition.
- No Tier-A (independently verified live) evidence exists in the field for LLM trading agents.

## Repository layout

```
governance/ data/ domain/ intelligence/ risk_execution/ observability/ research/ shared/
simulation/ model_providers/    code planes and leaf packages
console_api/ frontend/          read-only operator console (stdlib server + no-build UI)
tools/ scripts/ tests/ docs/    fixtures & evaluations, lint/smoke, test suites, documentation
```

Docs: `docs/00`–`05` stage series (historical, versioned, never silently edited);
`docs/slice-status.md` and `docs/implementation-log.md` for build history;
`docs/operator-console.md` for the console.

## Disclaimer

Research software for a single operator. Not investment advice.
