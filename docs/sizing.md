# Deterministic Sizing (Slice 6)

`risk_execution/sizing/sizer.py` — Stage 3 §8, TR-3. **The only module that computes an executable
share quantity and constructs an `OrderRequest`** (an AST test enforces this).

`size_order(candidate, risk_decision, SizingInputs, SizingConfig) -> SizingDecision` (never raises).

## Approval is verified, not assumed

Refused (`REFUSED_NOT_APPROVED`, no order) unless the decision is a `RiskDecision` with verdict APPROVE,
belongs to this candidate, has no failed check and a ceiling >= 1.

## Calculation (Decimal, integer shares, FLOOR)

* BUY: `target_value = size_hint x equity x (1 - cash_buffer)`; `qty = floor((target_value - (held + pending_buy - pending_sell) x price) / price)`,
  then `min(qty, risk ceiling, affordable)` where affordable = `floor((cash + pending_sell_value - pending_buy_value)/price)`.
* SELL: `size_hint == 0` -> full exit of the unencumbered holding; else keep `floor(size_hint x equity x (1-buffer) / price)`.
  Clamped to `[0, ceiling, holding]`.
* `min_trade_notional` skips small partial trades (full exits exempt). Zero qty => `NO_TRADE` with reason.
* **Residual cash** is reported *before* transaction costs. Costs are not in the affordability clamp;
  `cash_buffer` is the explicit allowance and the broker rejects an unaffordable fill (never silent).
* Invalid input (price <= 0/NaN/inf/None, equity <= 0, missing portfolio, `size_hint` NaN/inf/<0/>1/None,
  bad pending counts, invalid config) => `REJECTED_INVALID_INPUT`. Zero `size_hint` BUY => `NO_TRADE`.
* Never negative, never fractional, never above the ceiling; identical inputs give identical outputs.

`OrderRequest`: MARKET, `risk_decision_id` link, deterministic `idempotency_key`. The existing contract has no
strategy/config fields; those travel in `SizingDecision`, `DecisionRecord` and the pipeline artifacts.

## Config

`SizingConfig(label, cash_buffer in [0,1), min_trade_notional)`; payload is part of experiment identity.

## Limitations

No lot sizes, price bands, margin, tax or impact model; reference price is the cycle's last close while
fills occur at the next open, so realised notional differs (rejection if cash is short).
