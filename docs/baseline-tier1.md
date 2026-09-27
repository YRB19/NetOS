# Tier-1 Baseline — Equal-Weight Buy-and-Hold

**Strategy version:** `tier1_equal_weight_buy_hold_v1`
**Module:** `intelligence/baseline/tier1_equal_weight.py`
**Class:** `Tier1EqualWeightBuyHold`

## Hypothesis / definition

> Naive equal-weight buy-and-hold across the permitted universe,
> rebalanced only when the permitted universe changes.

This is the DeMiguel-Garlappi-Uppal-standard naive-static floor (Stage 0
02 §3.1/§9; Stage 3 §12 Tier 1) — the minimal, zero-parameter comparator
that every later Plane 2 candidate (Tier-2 momentum, the LLM component,
anything else) must clear via ER-1 comparison. It is **not** a claim
that buy-and-hold is expected to be profitable after costs; the Research
harness (a later slice) exists to test that honestly, negative result
included.

## Behavior

| Universe state for instrument X | Action | size_hint |
|---|---|---|
| X newly permitted (first cycle, or just added) | BUY | `1/N` (N = current universe size) |
| X permitted, universe unchanged for X | HOLD | `1/N` (documents continued target allocation) |
| X just removed from permitted universe | SELL | `0.0` (full exit) |
| X permitted but data missing/stale (SF-1/SF-2) | HOLD | `None` (no basis to size a target) |

Where N is the size of the **current** (post-change) permitted universe.
An addition or removal changes N for every remaining instrument's
equal-weight target, but this only shows up in the `size_hint` value —
it never generates a spurious BUY/SELL for an instrument that didn't
change status.

### Initial allocation

Universe `[A, B, C, D]`, all four instruments valid on the first cycle
(`previous_universe=None`): four `BUY` candidates, each with
`size_hint=0.25`.

### No universe change

Same universe on a later cycle (`previous_universe == universe`): four
`HOLD` candidates, each still carrying `size_hint=0.25` (the target
allocation, restated — not a rebalancing instruction).

### Addition

`[A,B,C] → [A,B,C,D]`: A/B/C → HOLD (size_hint recomputed to `0.25`,
reflecting the new N=4), D → BUY (size_hint `0.25`).

### Removal

`[A,B,C] → [A,B]`: A/B → HOLD (size_hint `0.5`, N=2 now), C → SELL
(size_hint `0.0`). C's `CandidateTrade` requires a `FeatureSnapshot`
even though C is no longer permitted — callers must build one via
`build_feature_snapshots(..., instrument_ids=<current ∪ removed>)`
(see `docs/feature-context.md`) so the exit decision remains
attributable (RR-7). The strategy raises `ValueError` rather than
silently skipping a removed instrument if no such snapshot is supplied.

### Missing/stale data

A permitted instrument with an incomplete `FeatureSnapshot`
(`is_complete=False`) always produces `HOLD, confidence=0.0,
size_hint=None`, with a rationale explicitly stating the data gap. This
is never silently treated as "no candidate" — the decision is logged
like any other (TR-4: hold is first-class).

## `size_hint` semantics

`size_hint` is a **normalized allocation-weight hint** in `[0, 1]` — a
fraction of the (eventual) portfolio, e.g. `0.25` for a four-instrument
equal-weight book, `0.0` for a full exit. It is **not**:
- a share count,
- a rupee amount,
- a broker order quantity,
- leverage.

Only Plane 3's sizing module (a future slice) may ever convert a hint
into an actual executable quantity, using operator-configured capital,
exposure headroom, and cost estimates (Stage 3 §8). This baseline has no
knowledge of account size, cash balance, or any risk limit.

## Deterministic guarantees

Given the same `(snapshots, universe, previous_universe)`, the strategy
always returns the same list of `CandidateTrade` objects, in the same
(sorted-by-instrument-id, permitted-then-removed) order, with the same
deterministically-derived `candidate_id` (content hash of
`snapshot_id + strategy_version_id + action`). No randomness, no wall-clock
reads, no network calls, no hidden mutable state — `previous_universe` is
an explicit parameter, never internally remembered between calls.

## What this baseline does NOT do

- Does not compute any technical/predictive signal (no momentum, no
  RSI/MACD, no sentiment).
- Does not size positions in shares or rupees.
- Does not talk to a broker, a risk engine, or any external service.
- Does not claim, imply, or demonstrate profitability. It is
  infrastructure for the evaluation harness (ER-1), not evidence of
  alpha.
- Does not modify or expand the permitted universe itself.

## Known limitations

- Confidence is a fixed `1.0` for every acted-on decision and `0.0` for
  missing-data holds — it does not express graded uncertainty about
  price data quality (e.g. a slightly-stale-but-still-usable price is
  not distinguished from a perfectly fresh one; the SF-2 threshold is a
  hard cutoff, not a confidence gradient). This is an acceptable
  simplification for a zero-parameter baseline, revisited if a future
  Plane 2 candidate needs graded confidence.
- Rebalancing is triggered only by *membership* changes, not by price
  drift away from equal weight (e.g. if A doubles in price relative to
  B, this baseline does not rebalance back to 50/50 — it only reacts to
  universe membership changes, consistent with "rebalanced only when the
  permitted universe changes" in the spec). A drift-triggered rebalance
  rule, if ever wanted, would be a distinct, separately-evaluated
  strategy variant, not silently folded into this one.
