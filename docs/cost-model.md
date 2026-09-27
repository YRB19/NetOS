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

The default schedule, `INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED`
(`shared/costs/schedule.py`), reflects the **commonly-published structure**
of Indian equity transaction costs — the same component set and roughly the
same rates that appear across multiple discount-broker charges pages
(Zerodha/Upstox/FYERS-style rate cards) — but:

- **It has not been independently verified this session against a primary
  regulatory source** (a SEBI circular, an NSE/BSE exchange circular, or
  the Finance Act provisions governing STT/stamp duty). No prior Stage 0–3
  document in this project established a verified, cited rate table for
  these specific components — Stage 0/1's research focused on the
  algo-trading regulatory framework (SEBI's Feb 2025 circular, order-rate
  thresholds, static-IP/2FA rules), not on the STT/GST/stamp-duty rate
  table itself.
- The schedule's `verified` field is `False` and its `version_id` carries
  an explicit `-unverified` suffix, precisely so a future verified schedule
  cannot be confused with this one — per this project's own standing rule
  against treating a plausible number as a confirmed one (see
  `decisions-and-learnings.md`'s evidence-tiering discipline, applied here
  to a regulatory rate table rather than a research claim).
- This is **not** a claim that the rates are wrong — they are the
  standard, widely-reproduced structure — only that this session did not
  perform the primary-source verification the project's epistemology
  requires before treating a number as authoritative.

**What this means practically:** the Cost Model is fully usable, testable,
and buildable-against today. It must **not** be relied upon as the true
cost basis for TR-2 (pre-trade cost estimation influencing sizing), PR-6
(cost reconciliation), or PR-9 (net-of-costs profitability) until either
(a) a primary-source review confirms these rates, or (b) a new, explicitly
verified schedule version is issued to replace it. This is tracked as an
open item (see `slice-status.md`).

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

- Rate table is unverified against a primary source (see Provenance above)
  — the single most important open item.
- Brokerage is modeled generically (a configurable flat/percentage
  structure), not against any specific broker's actual, current published
  rate card — broker-specific schedules are explicitly deferred to a
  future integration/configuration layer (Stage 3 §8, unchanged).
- Slippage / market-impact estimation (Stage 1 DR-5, PR-7) is out of scope
  for this component entirely — the Cost Model computes statutory and
  brokerage charges only, not price-impact cost.
- Stamp duty and STT rates modeled here reflect the commonly-cited
  post-2020/post-2023 structure; if the operator's actual trading period
  predates or postdates a rate change not reflected here, this schedule
  would need a new version rather than a correction to v1 (per the
  no-silent-edit rule).
