# Simulated Broker (Slice 6, ADR-8)

`risk_execution/broker/interface.py` (broker-neutral `BrokerAdapter` protocol, §10) and
`risk_execution/broker/adapters/simulated.py` (`SimulatedBrokerAdapter`). Offline, deterministic, no
credentials, no network, no SDK, no wall clock (time is injected with `set_simulated_time`).
**This is not live execution and not realistic market microstructure.**

## Interface

`authenticate` (refuses any credentials: `CredentialsNotSupported`), `get_account_state`, `get_positions`,
`place_order`, `modify_order` (unsupported), `cancel_order`, `get_order_status`, `get_fills`, plus
simulation-only `advance(timestamp, open_prices)`, `ledger_snapshot()` and the test-only fault hook
`inject_ambiguous_response`.

## Lifecycle — the existing Order state machine, unchanged

`CANDIDATE -> APPROVED -> SUBMITTED -> ACKNOWLEDGED -> PARTIALLY_FILLED / FILLED`, `PARTIALLY_FILLED -> CANCELLED`,
`REJECTED`, `RECONCILIATION_REQUIRED`. The existing contract forbids cancelling an unfilled ACKNOWLEDGED
order; `cancel_order` there raises `InvalidOrderTransition` (contract deliberately not changed).

## Explicit fill assumption (`FULL_OR_FIXED_FRACTION_AT_NEXT_BAR_OPEN_NO_SLIPPAGE`)

MARKET only (LIMIT and fractional quantity => REJECTED). Fill price = bar **open** of the first bar strictly after
acceptance. No slippage, impact or queueing. Default: full fill. Optional deterministic partial fills:
`max(1, floor(quantity x max_fill_fraction_per_bar))` per bar of the *original* quantity; remainder may be
cancelled. SELLs execute before BUYs within a bar. Charges per fill come from the shared India-equity Cost
Model. A fill the broker cannot afford (cash/position) => REJECTED (or remainder CANCELLED), never silent.

## Determinism and idempotency

Order/broker/fill ids derive from the request's idempotency key. A duplicate `place_order` returns the existing
order (`duplicate=True`), creates nothing, fills once.

## Reconciliation

The broker keeps its **own** cash/position ledger. After every settlement the pipeline compares it with the
research portfolio (`simulation/reconcile.py`); disagreement fails the run (`RECONCILIATION_REQUIRED`). Each
`BrokerFillReport` carries order id, fill id, quantity, price, timestamp, state, risk-decision id,
idempotency key, charges and adapter id/version. An order in RECONCILIATION_REQUIRED is never filled and fails
the run closed. The broker never touches strategy state.

## Where the pipeline lives

`simulation/` (new leaf package, ADR-9 in `dependency-decisions.md`) wires strategy -> risk -> sizing -> broker ->
portfolio so the Slice 5 rule `research -X-> risk_execution` stays intact.
