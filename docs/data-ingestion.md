# Data Ingestion — Slice 2

## Source selected: NSE-bhavcopy-format historical CSV

**Why this format:** NSE's daily equity "bhavcopy" report is the closest thing to a canonical,
well-documented historical OHLCV source for Indian equities — stable column layout, ISIN-based
instrument identity, and it is the format most NSE-focused tooling (including several brokers'
own historical-data exports) already resembles.

**Why a real bhavcopy archive was not downloaded this session:** this sandbox has no network
access (confirmed directly: `pip install` fails with "No matching distribution found" for any
package, including stdlib-adjacent tools like `pytest`). Downloading from
`nseindia.com/archives` was therefore not possible. This is stated plainly rather than worked
around by fabricating a "successful download."

**What was actually built and tested instead:**
- The adapter (`data/adapters/nse_bhavcopy_csv.py`) is built against the *documented* bhavcopy
  format (`data/schemas/nse_bhavcopy_schema.py`), not against any specific downloaded file.
- Two small, hand-authored, deterministic fixture CSVs
  (`tests/fixtures/historical_data/valid_sample.csv` and `mixed_quality_sample.csv`) exercise
  the adapter and pipeline in tests. These are clearly labeled fixtures, not production data,
  and this document does not claim real historical ingestion was validated against them beyond
  what a fixture can prove (format-conformance and pipeline-logic correctness).
- **Explicit follow-up required before this pipeline is trusted with real research or a
  backtest:** obtain an actual multi-year NSE bhavcopy archive (or an equivalent, e.g. a
  broker's historical-data API once one is selected per Stage 2 §18) and run it through this
  same adapter/pipeline, in an environment with network access, as a dedicated validation pass.
  This is tracked as an open item, not silently assumed done.

## Source format (documented contract)

Columns (see `data/schemas/nse_bhavcopy_schema.py` for the authoritative list):

| Column | Meaning | Required |
|---|---|---|
| SYMBOL | Trading symbol (e.g. `RELIANCE`) | Yes |
| ISIN | Canonical instrument identifier | Yes |
| SERIES | `EQ` for equity; anything else is out of scope (TR-1) | Yes |
| DATE | Trading date, `DD-MON-YYYY` (e.g. `02-JAN-2024`) | Yes |
| OPEN, HIGH, LOW, CLOSE | As-traded prices, INR | Yes |
| TOTTRDQTY | Total traded quantity (volume) | Yes |
| LAST, PREVCLOSE | Retained in the raw record; not consumed by normalization | No |

**Documented timezone assumption:** a bhavcopy DATE has no intraday time component. This
pipeline assigns each date NSE's fixed regular-market close time, **15:30 IST**, before
converting to UTC (`data/normalization/pipeline.py:_parse_bhavcopy_date`). This assumption is
applied exactly once, in one place, using the shared `shared/time/clock.py` utility — nothing
else in the codebase re-derives or re-guesses a timezone.

## Pipeline flow

```
CSV file (bhavcopy format)
      |
data/adapters/nse_bhavcopy_csv.py     -- reads rows, produces RawMarketObservation
      |                                  (source fields UNTOUCHED, one record per CSV row)
      v
data/validation/raw_validation.py     -- required-field presence + SERIES scope check
      |                                  (SF-1: incomplete records rejected here, never proceed)
      v
data/normalization/pipeline.py        -- timestamp parsing (IST->UTC), numeric parsing,
      |                                  duplicate detection, corporate-action adjustment
      v
data/validation/market_data_validation.py -- numeric sanity + OHLC consistency
      |                                       (accumulates ALL problems, not just the first)
      v
domain/models/market_data.py (MarketData) -- final construction; its own __post_init__ is a
      |                                        defense-in-depth backstop, not the primary check
      v
data/normalization/persistence.py     -- deterministic JSONL output (Slice 2 stopgap; Stage 2
                                          §18's relational store is a later slice's concern)
```

Every raw observation ends in exactly one of two places: `NormalizationResult.accepted`
(a `MarketData` instance) or `NormalizationResult.rejected` (a `RejectedRecord` with a
`reason_code` and a non-empty list of specific reasons). Nothing is silently dropped.

## Validation rules

**Required fields** (raw level): SYMBOL, ISIN, SERIES, DATE, OPEN, HIGH, LOW, CLOSE, TOTTRDQTY
must all be present and non-whitespace. A record failing this check is rejected with
`reason_code=RAW_VALIDATION_FAILED` and never reaches numeric validation.

**Series scope**: only `SERIES=EQ` (case-insensitive) is in scope, per TR-1's restriction of
the permitted universe to equity. Any other series value (e.g. `BE`) is rejected at the raw
level with a specific reason.

**Numeric sanity**: OPEN/HIGH/LOW/CLOSE must be finite (`not NaN`, `not inf`) and strictly
positive; VOLUME must be a non-negative integer. All violations on a single record are
collected and reported together (`data/validation/market_data_validation.py`), not just the
first one found.

**OHLC consistency**: `high >= max(open, close, low)` and `low <= min(open, close, high)`.
This is checked twice — once explicitly in `market_data_validation.py` (to produce a specific,
readable reason before construction) and once again inside `MarketData.__post_init__` itself
(defense-in-depth: the domain type cannot be constructed in a violating state even if a caller
bypasses the pre-check).

**Duplicate observations — explicit policy decision:**
- Two records sharing canonical identity (`instrument_id`, `timestamp`, `source`) with
  **identical** OHLCV values are an **exact duplicate**: the first is kept, the second is
  rejected with `reason_code=DUPLICATE_EXACT`.
- Two records sharing that identity with **different** OHLCV values are treated as a **source
  revision/correction**: both are retained as separate `MarketData` records, distinguished by
  their (differing) `ingestion_time`. This pipeline never edits or discards a prior canonical
  record in place — per Stage 3 §5's explicit rule that "corrections are new records." Which
  record a downstream consumer should treat as "current" is a downstream policy decision, not
  something this pipeline resolves.

This decision is directly exercised by
`tests/integration/test_normalization_pipeline.py::TestRevisionHandling`.

## Corporate-action handling

**What is implemented:** the split/bonus adjustment *math* (`data/normalization/
corporate_actions.py`) — a documented, pure, deterministic function that multiplies prices by
`ratio_from/ratio_to` and volume by the inverse, for every observation strictly before a
split's effective date, compounding correctly across multiple splits. This is independently
unit-tested (`tests/unit/test_corporate_actions.py`) against synthetic data.

**What is NOT implemented:** a live source of actual Indian-equity split/bonus/dividend events
(Stage 1 DR-2 remains open — no such source was researched or integrated this session, and
there was no network access to do so). Consequently, the production adapter/pipeline path
(`normalize_bhavcopy_batch`) calls the adjustment function with an **empty splits list by
default**, so every canonical record this slice's actual pipeline produces has `adjusted=False`
and reflects exactly the as-traded prices the bhavcopy source itself provides. The raw/adjusted
distinction is preserved (`MarketData.adjusted` field; `MarketData.raw_ref` always points back
to the untouched `RawMarketObservation`), but no independent adjustment happens by default —
this is a documented limitation, not a silent gap.

## Instrument identity

`ISIN` is the canonical identifier (`Instrument.canonical_id` / `MarketData.instrument_id`).
`SYMBOL` + the adapter's fixed exchange (`NSE`, since bhavcopy is an NSE-specific report) form
the working identifier. Lot size defaults to `1` for cash-segment equity (bhavcopy carries no
lot-size field, and NSE cash-segment equities are tradable one share at a time). Instrument
identity is deterministic: the same raw row always resolves to the same `Instrument.isin`,
verified in `tests/contract/test_market_data_contract.py`.

## Data snapshot versioning

`data_snapshot_version = hash(raw_source_file_bytes, normalization_code_version)`
(`shared/versioning/content_hash.py::data_snapshot_version`). `NORMALIZATION_CODE_VERSION`
(`data/normalization/pipeline.py`) is a hand-bumped string constant, incremented whenever the
transformation logic changes in a way that could alter output for the same raw input. This is
the "simple, sufficient mechanism" Stage 3 §5 explicitly permits — not a distributed
data-versioning platform.

Determinism is directly tested: normalizing and persisting the same raw batch twice produces
byte-identical JSONL output
(`tests/integration/test_normalization_pipeline.py::TestDeterminism`).

## Known limitations (complete list)

1. No real, network-downloaded historical dataset was validated against this pipeline this
   session — only small, hand-authored fixtures (see "Source selected" above).
2. No live corporate-action data source (DR-2) is integrated; only the adjustment math exists
   and is tested synthetically.
3. Fundamentals (DR-3), order-book/microstructure data for slippage estimation (DR-5), and
   regulatory-update monitoring (DR-6) are not built — consistent with Stage 1/2's own priority
   ("Should"/contingent, populated only when a later slice's strategy needs them).
4. The persistence layer (`data/normalization/persistence.py`) is a deliberate JSONL stopgap,
   not the relational store Stage 2 §18 specifies; it exists only so Slice 3 has something
   concrete to read.
5. Only one broker/exchange convention (NSE bhavcopy) is supported; BSE-listed-only instruments
   are out of scope for this adapter.
6. This session's Slice 0/Slice 1 material is a **minimal reconstruction** scoped to what
   Slice 2 needed (see `docs/slice-status.md`), not the full Stage 3 §2 domain model — the
   remaining ~17 domain objects (CandidateTrade, RiskDecision, Order, DecisionRecord, etc.)
   do not yet exist in this repository.
