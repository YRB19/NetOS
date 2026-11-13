# Slice 13 — Multi-Market Live-Data Shadow & Dual Paper-Execution Harness

**Status: ENGINEERING INFRASTRUCTURE COMPLETE; NO LANE IS OPERATIONAL.** Every readiness gate defaults to
`ENGINEERING_ONLY` or `BLOCKED` because no market-data source, external paper platform or complete cost
schedule was verified against a primary source in this slice (the build sandbox has no network access).
Nothing here is evidence of alpha or profitability. Slice 12's **Outcome B (inconclusive)** is unchanged.

Roadmap revision 10 November 2026. Governance & Promotion (`docs/slice-13-governance-adjustment.md`) is
**not part of this brief** and was not implemented; see "Not done".

## 1. The three rules this slice is built around

1. **US and India are separate experiments.** `markets/` defines two `LaneSpec`s with their own currency,
   timezone, calendar, benchmark, cost schedule id, strategy-config ids, universe version and storage
   directory (`<root>/US_EQUITIES/…`, `<root>/IN_EQUITIES/…`). `compute_lane_readiness` accepts *one* lane's
   verification records and raises if given another lane's. There is no aggregate status and no combined
   performance field: `combined_index` only links lane reports and `build_lane_report` rejects keys such as
   `combined_pnl`. Tested: a fully verified US source leaves India at its own status.
2. **External execution is a comparison, not the truth.** The internal simulated broker and the external
   paper path keep separate ids, lifecycles, fills, cash, positions, costs and ledgers
   (`risk_execution/external_paper`). `compare_execution` places both outcomes side by side and sets
   `reconciled_by_overwrite: False`. A rejection, timeout or outage on the external side is contained in the
   mirror and provably leaves the internal result byte-identical (tested with deep copies).
3. **AI predictions are not paper trades.** Predictions go to their own hash-chained ledger and are scored
   by a separate read-only evaluator against independently captured observations. Tier-1/Tier-2 remain the
   only components that produce paper orders. No import path exists from `intelligence`/`model_providers`
   to the ledger, observations, markets or external paper (rules + tests), and recording predictions is
   tested not to change deterministic orders.

## 2. Components

| Package | Role | Key guarantees |
| --- | --- | --- |
| `markets/` | Lane specs, `LaneMoney`, readiness gating, standalone US cost schedule | pure leaf; mixed currencies raise; nothing OPERATIONAL without a verified record citing a primary source + access date |
| `data/live/` | `LiveObservation` (event / available / ingestion time kept separate), `QualityEngine`, append-only hash-chained `ObservationStore`, read-only `ObservationReader`, replay adapters | rejected/late/invalid observations are stored with their verdict; prices are never zeroed or filled; replay/synthetic adapters cannot emit `LIVE` provenance; tamper/deletion detected |
| `prediction_ledger/` | Record models + verifying reader (neutral leaf) | no writer here, so `research` can import it |
| `observability/prediction_ledger/ledger.py` | Append-only writer | commit must be ≤ `valid_from` else `REJECTED_LATE` (kept); corrections only before `valid_from`; later changes are invalidations; `NO_SIGNAL`/invalid/failed predictions preserved |
| `research/prediction_eval/` | Read-only outcome evaluator, metrics, coverage, fact-check separation | point-in-time (availability time) reads; unscoreable → explicit reason; optional second source with independence label; `INSUFFICIENT_SAMPLE` below declared minimum; probabilistic metrics only for predictions that *claim* calibrated semantics |
| `research/confirmatory/` | Per-market protocol freeze, variant ledger, holdout exposure, Holm on supplied p-values | protocol hash + freeze time; drift rejected; exposed holdout blocks later confirmatory windows in that market only; no p-values manufactured |
| `risk_execution/external_paper/` | Contract, paper-endpoint allowlist, credential redaction, `MockExternalPaperAdapter`, `ExternalMirror` | frozen `ApprovedIntent`; deterministic platform-scoped client order id; unknown outcome → status read-back, never blind resubmit |
| `simulation/multi_market/` | 8-session matrix, `LaneShadowSession`, comparison, reports | reuses the existing `PipelineHarness`; internal path `BLOCKED` raises before any broker call |

## 3. Session matrix (2 lanes × 2 tiers × 2 branches)

Each session has its own `session_id` and `experiment_id` derived from lane, tier, branch, strategy config
id and lane-spec identity. Current statuses with shipped defaults:

| Lane | Internal simulator | External paper |
| --- | --- | --- |
| IN_EQUITIES | `ENGINEERING_ONLY` (cost schedule not fully verified: brokerage/BSE/GST-base gaps remain) | `BLOCKED` (no eligible platform established) |
| US_EQUITIES | `BLOCKED` (see ADR-25) | `MOCK_ONLY` (Alpaca Paper is an unverified candidate; mock ≠ integration) |

Data: IN `BLOCKED` (no source established); US `ENGINEERING_ONLY` (candidate unverified).

## 4. Evidence classes

`evidence_class()` returns `LIVE_DATA_SHADOW` only when **every scored outcome used `LIVE` provenance and the
source verification is `VERIFIED`**. Otherwise `SYNTHETIC_ENGINEERING` or
`ENGINEERING_REPLAY_OR_UNVERIFIED_SOURCE`. Synthetic/replay data cannot satisfy live-data-shadow acceptance.

## 5. Known limitations and open items (read before relying on anything)

* **US internal execution is BLOCKED.** `shared.costs.CostEstimate` carries India-only components
  (STT, SEBI fee, GST, stamp duty). Reusing it for US would relabel fields; a second execution path would be
  a competing implementation. A jurisdiction-neutral cost breakdown is required first (follow-up slice).
  `markets/us_costs.py` exists as a standalone, **unverified** schedule (rates are placeholders from
  recollection, `verified=False`) and is not wired to any broker.
* **No provider, platform or rights verification was performed** (no network). See
  `docs/market-source-feasibility.md`. Alpaca's IEX-entitled paper data must not be treated as the whole US
  market. No real network adapter ships: `UnverifiedSourceAdapter` fails closed.
* **No real external integration.** The only external adapter is a mock. Alpaca Paper is `NOT CONFIGURED`.
  Its documented simulation limits (no market impact, latency slippage, queue position, regulatory fees or
  dividends; displayed liquidity not a strict fill cap; simulated partial fills) must be reproduced in any
  external report; those statements are from the brief and were not re-verified here.
* **Universe, benchmark and instrument-master ids are declared placeholders** (`*-UNSOURCED-v0`).
* **No real AI predictions are generated.** The ledger and evaluator are provider-agnostic; wiring the
  Slice 11 provider into a prediction source was not done (no verified data to evaluate against).
* **Ledger/store are tamper-evident, not tamper-proof**, single-writer, no locking.
* India lane scoring of market-truth needs a second independent source where licensed; none configured.
* Operator Console: no Slice 13 panel added (read-only data contract not extended).
* Ruff/mypy/pytest/browser checks unavailable; stdlib `unittest` only.

## 6. Running the engineering demo

`python3 tools/multi_market_synthetic_demo.py --out /tmp/netos_mm` writes `US_EQUITIES/lane_report.json`,
`IN_EQUITIES/lane_report.json` and `combined_index.json` (links + status, no combined performance), all
labelled `SYNTHETIC_ENGINEERING`.

## 7. Not done (explicit)

Governance/Promotion prerequisites; real data-source adapters; real external paper integration; US cost
integration into the simulated broker; real AI prediction generation; second-source cross-check wiring to a
licensed feed; confirmatory protocol *values* (windows, horizons, minimum sample) — only the machinery;
Operator Console panel; any live data-shadow session; any claim about AI or strategy performance.
