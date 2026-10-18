# Tier-2 Momentum Baseline (Slice 6)

Deterministic **12-1 month price momentum**, monthly rebalance, configurable top fraction.
A research baseline (Stage 3 §12, ADR-7). **Not an AI strategy and not a profitability claim.**
Code: `intelligence/baseline/tier2_momentum.py` (strategy), `data/features/momentum.py`
(feature formation, Plane 1), `data/features/calendar.py`.

## Exact definition

```
momentum(i, t) = close_i(t - skip) / close_i(t - lookback) - 1        defaults: skip = 1, lookback = 12
```

* `t` = decision timestamp. `skip`/`lookback` are **calendar months** (day clamped to month end).
* `close_i(d)` = `close` of the last observation of instrument `i` on or before the **end of calendar
  day `d`**, and only if it is no older than `max_price_gap_days` (default 10) before `d`; otherwise
  momentum is *missing* (never zero, never forward-filled beyond that gap).
* The most recent `skip` month is **excluded** from the signal (tests: bars inside the skipped
  month can be changed arbitrarily without changing momentum; the bar at `t-1m` demonstrably matters).
* The `close` used is whatever the canonical `MarketData.close` holds; corporate-action adjustment is
  the Plane 1 normalizer's job (limitation below).

## No look-ahead

The feature builder discards every record stamped after `t` even if the caller passes one, on top of
the harness's `replay.visible(t)`. Adversarial tests hand the builder a poisoned future (including a single
observation 1 second after `t` that would make an instrument rank #1) and assert identical snapshots and
candidates. Universe membership comes from the in-force universe at `t`.

## Rebalance convention

`is_rebalance_date = 1.0` iff `t` is the **first distinct observation timestamp (across all visible
instruments) inside its calendar month (UTC)**, computed only from observations `<= t`. If the window
starts mid-month, the first rebalance is the first observation of the next month. On every other
cycle the strategy emits **HOLD** for each permitted instrument (HOLD is a first-class decision, TR-4),
never trades. If the flag is unavailable the strategy HOLDs (fail safe).

## Ranking, ties, selection

* Eligible = permitted AND complete snapshot AND momentum present. Others get **HOLD** (a name is never
  liquidated because its data is missing).
* Sort by momentum **descending**, tie-break by `instrument_id` **ascending** (stable; no randomness).
* `k = max(1, ceil(selection_fraction * n_eligible))`, exact decimal arithmetic (30 x 0.1 = 3, not 4).
  Presets: `TOP_DECILE = 0.10`, `TOP_QUINTILE = 0.20`. `selection_fraction` must be in (0, 1]; bool, NaN,
  inf, strings are rejected.
* **Small universes:** never silently selects zero. 3 names at a decile -> 1 selected; 1 name -> 1 selected.
  With **zero** eligible names every instrument is HOLD with an explicit rationale.
* Selected -> `BUY`, `size_hint = 1/k` (equal-weight *target fraction of equity*, not a quantity).
  Not selected -> `SELL`, `size_hint = 0.0`. Removed from the universe -> `SELL` any day.
* `confidence = 1 - (rank-1)/n_eligible`; `uncertainty_band = None` (no model uncertainty exists).

## Provenance and version

`strategy_version_id = "tier2_momentum_12_1_v1@<16-hex hash of the full config>"` (existing
`make_version_id`). Selection fraction, lookback, skip and gap are in the hash, so changing any of them
changes the version and the experiment identity. `strategy_version()` returns the domain
`StrategyVersion`. The feature-set id is hashed the same way and the strategy **refuses** snapshots built
with a different feature set. Candidates carry strategy version, snapshot id, rationale; no quantity,
order, credential or broker field exists on them.

## Limitations

Synthetic validation only. Uses canonical `close` (adjustment correctness depends on Plane 1). Calendar
months are UTC; no exchange-holiday calendar is modeled. Monthly "first observation" depends on the data
supplied. Equal weights summing to 1.0 meet a gross/leverage cap of exactly 1.0 with zero headroom, so
top-up BUYs after price drift are vetoed (see `risk-engine.md`). Nothing here shows the factor works
after costs in Indian equities.
