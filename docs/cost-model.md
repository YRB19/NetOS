# Cost Model (Slice 4)

## Purpose

A shared, deterministic, versioned India-equity transaction-cost calculator.
Given a proposed transaction (side, trade type, quantity, price, and a
pinned cost-schedule version), it returns a fully itemized cost estimate.

It exists so that Research/backtesting (Stage 3 §11), future Risk/Sizing
(Stage 3 §7/§8), and future paper/live execution can all call the exact
same calculation logic against the exact same versioned rate table — this
is what Stage 2 §7/§20's "Cost Model drift" risk is architecturally
prevented from happening.

## Architecture location

`shared/costs/` — a shared, dependency-safe package per Stage 3 §1.

- `models.py` — `CostInputs`, `CostEstimate`, `TransactionSide`, `TradeType`
- `schedule.py` — `IndiaEquityCostSchedule`, `ScheduleRegistry`, `default_registry()`
- `calculator.py` — `CostModel.estimate()`

It has **no** dependency on broker, intelligence, or research code, and no
network/clock/randomness dependence. This is enforced both structurally
(`scripts/check_import_graph.py`) and by direct tests
(`tests/unit/test_costs.py::TestIndependence`).

## Input contract — `CostInputs`

| Field | Type | Notes |
|---|---|---|
| `side` | `TransactionSide` (`BUY`/`SELL`) | Required |
| `trade_type` | `TradeType` (`DELIVERY`/`INTRADAY`) | Required — several components differ by this (Stage 1 TR-5) |
| `quantity` | `int` | ≥ 0. `0` is a valid, explicitly-defined "zero-value transaction" (see below), not an error |
| `price` | `Decimal` (floats/strings accepted and coerced) | Must be > 0 whenever `quantity` > 0; must be finite (no NaN/Infinity) |
| `schedule_version` | `str` | Must name a schedule registered in the `ScheduleRegistry` used |

`CostInputs` is **not** an `OrderRequest` or any broker/execution object —
this is deliberate, so Research code with no broker context at all can call
the Cost Model identically to how live/paper trading eventually will.

**Zero-value transactions:** `quantity == 0` produces an all-zero
`CostEstimate` (every component `0`, `total_cost == 0`), rather than an
error or a flat fee charged against a null trade.

## Output contract — `CostEstimate`

Every component is always present. A component that doesn't apply to a
given side/trade_type combination (e.g. stamp duty on a `SELL`) is
represented as an **explicit zero**, never omitted.

| Field | Meaning |
|---|---|
| `gross_turnover` | `quantity * price` |
| `brokerage` | Broker's own fee (configurable, see below) |
| `stt` | Securities Transaction Tax |
| `exchange_txn_charges` | Exchange transaction charges |
| `sebi_charges` | SEBI turnover fee |
| `gst` | GST on (brokerage + exchange_txn_charges + sebi_charges) only |
| `stamp_duty` | Stamp duty (buy side only) |
| `total_cost` | Exact sum of the six components above, after each is independently rounded (see Rounding) |

`CostEstimate.component_total()` recomputes the sum from the stored
components; `total_cost == component_total()` always holds by construction
(tested directly).

`CostEstimate.cost_pct_of_turnover()` returns `0` when `gross_turnover == 0`
(never a division error).

## Cost components — calculation rules

| Component | Delivery | Intraday |
|---|---|---|
| Brokerage | Flat fee (schedule default: ₹0) | `min(flat_fee, pct_of_turnover)` — the common "whichever is lower" model |
| STT | Applied on **both** buy and sell, same rate | Applied on **sell only**; buy leg is `0` |
| Exchange transaction charges | `turnover * rate`, both sides | Same |
| SEBI charges | `turnover * rate`, both sides | Same |
| GST | `18% * (brokerage + exchange_txn_charges + sebi_charges)` | Same — never applied to STT or stamp duty |
| Stamp duty | `turnover * rate`, **buy side only** | `turnover * rate`, **buy side only** (different rate than delivery) |

Each rule is implemented as an independently testable static method on
`CostModel` (`_brokerage`, `_stt`, `_stamp_duty`), per the "inspectable, not
opaque" requirement.

## Provenance and assumptions — read this before trusting a number

**Slice 4.5B (2026-09-29) primary-source-verified this against official
sources and issued a second schedule, `india-equity-v2-2026-03-verified`.**
The original `INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED` is preserved unchanged
(never edited in place — DOC-6) so research already run against it stays
reproducible; new work should select V2.

## Rate Verification Status

| Component | Status | Rate | Basis | Effective Date | Source | Notes |
| --- | --- | ---: | --- | --- | --- | --- |
| Brokerage (delivery) | CONFIGURABLE | ₹0 flat | per order | — | none (generic assumption) | Not a statutory or named-broker rate |
| Brokerage (intraday) | CONFIGURABLE | min(₹20, 0.03%) | per order, turnover | — | none (generic assumption) | Common discount-broker structure, not verified |
| STT — delivery (buy & sell) | VERIFIED | 0.1% | turnover, each leg | current | NSE, "SEBI Turnover Fees, STT and Other levies" (updated 17/04/2026) | STATUTORY |
| STT — intraday sell | VERIFIED | 0.025% | turnover, sell leg only | current | same as above | STATUTORY; buy leg is 0 |
| Exchange transaction charge | VERIFIED (NSE-specific) | 0.00307% (₹307/crore) | turnover, each side | 2026-03-01 | NSE circular NSE/FA/73061 (27 Feb 2026) | EXCHANGE; total outflow incl. NSE IPFT contribution; BSE differs |
| SEBI turnover fee | VERIFIED | 0.0001% (₹10/crore) | turnover | current | NSE (updated 17/04/2026) | REGULATORY |
| GST — rate | VERIFIED | 18% | — | current | NSE (updated 17/04/2026) | REGULATORY |
| GST — base | CONFIGURABLE-BUT-STANDARD | brokerage + exchange_txn + sebi_charges | — | — | industry contract-note convention | Not itemised by the primary source itself; STT/stamp duty excluded as non-supply levies |
| Stamp duty — delivery (buy only) | VERIFIED | 0.015% | turnover, buy leg only | current (since 1 Jul 2020) | NSE, "Stamp Duty" (updated 03/10/2023) | STATUTORY |
| Stamp duty — intraday (buy only) | VERIFIED | 0.003% | turnover, buy leg only | current (since 1 Jul 2020) | same as above | STATUTORY |

Full excerpts, URLs, and the verification methodology are in
`docs/cost-rate-verification.md`.

**What "VERIFIED" means here, precisely** (per this project's evidence
discipline): the rate, its calculation base, its effective date, and its
authoritative source were each independently confirmed against an official
NSE or regulatory page/circular on the verification date above — not
inferred from a secondary/broker/blog source. **Brokerage is deliberately
never marked VERIFIED**: it is not a statutory rate, and no single named
broker's dated, official rate card was checked against it, so it remains an
explicit, swappable configuration assumption (Slice 4.5B §6).

**What this means practically:** `india-equity-v2-2026-03-verified` is now
the schedule to use for TR-2/PR-6/PR-9-relevant work going forward. The
GST-base line above is the one place this schedule states an assumption
(standard industry practice) rather than an itemised primary-source rule —
noted so it isn't mistaken for a fully independent verification.

## Rounding policy

- Every individual component is rounded independently to **2 decimal
  places (nearest paisa)** using **`ROUND_HALF_UP`**, at the point it is
  computed.
- `total_cost` is the **exact Decimal sum of the already-rounded
  components** — it is never independently re-rounded. This guarantees
  `total_cost == component_total()` by construction, not by coincidence of
  two separate roundings agreeing.
- All monetary arithmetic uses `decimal.Decimal`. Floats are accepted at
  the `CostInputs` boundary for caller convenience but are converted via
  `Decimal(str(value))`, never `Decimal(float)` directly, to avoid
  importing binary floating-point representation error into a price.

## Versioning

- A schedule is pure configuration (rates), never calculation logic — a new
  rate table is a new `IndiaEquityCostSchedule` with a new `version_id`,
  never an in-place edit of an existing one (consistent with this
  project's DOC-6 versioning discipline).
- A `CostModel` is constructed against an explicit `ScheduleRegistry` (or
  `default_registry()`), so a Research run evaluating a historical period
  can pin a specific schedule and not silently drift if the "current"
  default later changes.
- Every `CostEstimate` carries the `schedule_version` it was computed
  under.

## Determinism and independence

`CostModel.estimate()` is a pure function of its `CostInputs` and the
registered `IndiaEquityCostSchedule` — no network calls, no clock/`now()`
dependence, no randomness, no broker calls. Verified by
`TestDeterminism` and `TestRounding.test_repeated_calculation_is_identical`.

`shared/costs/` has zero imports from broker, intelligence, or research
code. Verified by `scripts/check_import_graph.py` (0 violations) and
directly by `TestIndependence`.

## Limitations (current, explicit)

- Brokerage remains a generic, unverified configuration assumption in both
  schedule versions — broker-specific schedules are explicitly deferred to
  a future integration/configuration layer (Stage 3 §8, unchanged).
- The exchange transaction charge is NSE-specific (NSE/FA/73061); BSE
  publishes its own cash-market rate separately, which this project has
  not verified — a BSE-routed order would need its own schedule or
  exchange-aware CostInputs dimension (a model gap, not fixed here per
  Slice 4.5B §18's "no silent model expansion" instruction).
- The GST *base* (which components GST applies to) follows standard
  industry contract-note practice, not an itemised primary-source rule —
  see the table above.
- Slippage / market-impact estimation (Stage 1 DR-5, PR-7) remains out of
  scope for this component entirely.
- `india-equity-v1-unverified` is preserved, still selectable, and still
  genuinely unverified — it is not "upgraded" by V2's existence.
