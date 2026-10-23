# Order lifecycle, idempotency and reconciliation (Slice 7)

Offline / simulated only. No LLM, no real broker, no credentials. Results are infrastructure checks, not
evidence of execution quality, profitability or regulatory approval.

## 1. What exists (extension, not replacement)
* `domain/models/order.py` — the **unchanged** Order state machine (the only lifecycle definition).
* `risk_execution/order_lifecycle/` — `OrderLifecycleManager` (+ `BrokerEvent`): approval re-validation,
  write-ahead submission, identity-based idempotent event processing, quarantine, halts, snapshot/restore.
* `risk_execution/reconciliation/` — `reconcile_execution` (orders, fills, positions, cash, 3-way) and
  `compare_cash_positions` (the Slice 6 two-ledger comparison, now the single shared implementation;
  `simulation.reconcile.reconcile` delegates to it with identical messages).
* `SimulatedBrokerAdapter` additions: `find_order_by_client_key`, `order_statuses`, one-shot fault injection
  (`inject_fault("FAIL_BEFORE_ACCEPT" | "FAIL_AFTER_ACCEPT")`). Added to the `BrokerAdapter` Protocol: `find_order_by_client_key`.
* `simulation/runner.py` now routes every submission through the manager, every fill/cancel/reject through
  `apply_event` (a redelivered fill is never booked twice), and runs the full reconciliation each cycle.

## 2. Permitted transitions (domain contract, verified by printing `ALLOWED_TRANSITIONS`)
| From | To | Evidence required |
|---|---|---|
| CANDIDATE | APPROVED | valid risk approval (manager re-validates) |
| APPROVED | SUBMITTED | adapter call attempted (write-ahead) |
| SUBMITTED | ACKNOWLEDGED / REJECTED / RECONCILIATION_REQUIRED | broker response or contradiction |
| ACKNOWLEDGED | PARTIALLY_FILLED / FILLED / **CANCELLED** (ADR-11) / REJECTED / RECONCILIATION_REQUIRED | fill event(s) / **broker-confirmed cancel** / broker reject |
| PARTIALLY_FILLED | FILLED / CANCELLED / RECONCILIATION_REQUIRED | fill / **cancel confirmed** |
| RECONCILIATION_REQUIRED | FILLED / PARTIALLY_FILLED / CANCELLED / REJECTED | operator resolution consistent with accounted fills |
| FILLED, CANCELLED, REJECTED | — (terminal, never reopened) | — |
Never occur: CANDIDATE→FILLED, any skip of APPROVED, any move out of a terminal state, RECONCILIATION_REQUIRED→ACKNOWLEDGED, SUBMITTED/APPROVED→CANCELLED.

## 3. Event identity and idempotency
Identity: broker `event_id` if present (`evt:<id>`); else fills by `fill_id` (`fill:<id>`); else ACK / REJECT /
CANCEL_CONFIRMED by kind + order ref (naturally once per order). No identity at all ⇒ INVALID + halt.
Fills are additionally guarded by `fill_id` across envelopes. Same identity + same fingerprint ⇒ duplicate
ignored (logged); same identity + different payload ⇒ conflict ⇒ quarantine + escalate + halt. Distinct
fill_ids with identical qty/price are two fills. Submission idempotency: the existing canonical
`idempotency_key`; the same key is never re-sent (`DUPLICATE_NOT_RESENT`), even while halted.

## 4. Event outcome table
| Event | State | Outcome |
|---|---|---|
| ACK | SUBMITTED | applied |
| ACK | ACK/PARTIAL/FILLED/CANCELLED | `STALE_IGNORED` (logged) |
| ACK | REJECTED / RECON / APPROVED(unsent) | quarantine + halt |
| REJECT | SUBMITTED/ACK | applied (broker reason stored) |
| REJECT | PARTIAL | quarantine, order → RECONCILIATION_REQUIRED (fills preserved) |
| REJECT | FILLED/CANCELLED | quarantine + halt |
| CANCEL_CONFIRMED | PARTIAL | applied; fills preserved |
| CANCEL_CONFIRMED | ACK (no fills) | applied → CANCELLED (ADR-11) |
| CANCEL_CONFIRMED | SUBMITTED (no ack recorded) | quarantine, → RECONCILIATION_REQUIRED (no evidence the order was ever live here) |
| CANCEL_CONFIRMED | FILLED/REJECTED | quarantine + halt |
| FILL | SUBMITTED | evidence-based implicit ack, then applied |
| FILL | ACK/PARTIAL | applied if cumulative ≤ qty and fill_type consistent; else quarantine + escalate |
| FILL | CANCELLED/REJECTED/RECON | **quarantined, not accounted**, halt |
| any | unknown order / mismatched ids | `UNKNOWN_ORDER` + halt |
A cancel *request* never changes state; a timed-out/failed request proves nothing.

## 5. Submission uncertainty
`LOCAL_FAILURE` (adapter refused, `BrokerRequestError`, no order exists) ≠ `REJECTED_BY_BROKER` ≠
`SENT_UNCONFIRMED` (any other adapter failure: order stays SUBMITTED, halt `UNCERTAIN_SUBMISSION`).
`resolve_uncertain_submission` asks the broker by client key and replays what it reports through `apply_event`
(never re-sends): found ⇒ `RECONCILED_FROM_BROKER`; absent ⇒ `ABSENT_AT_BROKER`, order closed REJECTED, and a retry
needs a **new** order with fresh risk evaluation. If the adapter cannot look up by key the submission stays
`UNRESOLVED`. Resolution never clears the halt. No exactly-once claim against a real broker is made.
Deviation noted: Stage 3 §9 says timeouts → RECONCILIATION_REQUIRED; because that state cannot return to
ACKNOWLEDGED, an unconfirmed submission stays SUBMITTED + halt, and escalates to RECONCILIATION_REQUIRED only on contradiction.

## 6. Reconciliation
Compares (1) lifecycle-implied state (opening + accepted fills), (2) the internal portfolio, (3) the broker ledger
and fill history: order identity/state/filled and outstanding qty, fill ids (missing / extra / contradictory),
positions and cash pairwise, quarantined evidence, unresolved submissions, portfolio-application lag.
Outcomes: `CONSISTENT`, `CONSISTENT_AFTER_SAFE_DUPLICATES`, `RECONCILED_FROM_BROKER_EVIDENCE` (missing fills ingested as
ordinary events and booked by the caller), `MISMATCH_DETECTED`, `UNRESOLVED`. "Cannot verify" (e.g. unknown charges ⇒
`CASH_UNVERIFIABLE`) is never "consistent". Run ids are deterministic content hashes. **Independence limit:** in the
offline simulation charges come from one cost model everywhere, so charge *rates* are not independently verified.

## 7. Halts and operator pathways
Any unresolved condition raises a `HaltRecord`; `submit` raises `ExecutionHalted`; the runner stops submitting and fails
the run `RECONCILIATION_REQUIRED` at the next settlement. Only `clear_halt(halt_id, operator_id, reason, run_id)` clears a
halt, and only if the order is no longer unresolved and (for reconciliation halts) a consistent run newer than the halt is
cited. A later passing check never clears a halt. Operator tools: `resolve_reconciliation_required`,
`accept_quarantined_fill`, `dismiss_quarantined`, `acknowledge_terminal_discrepancy` — all require operator id + evidence
and append to the record's `corrections`. Reconciliation never calls any of them, never changes risk thresholds,
and never edits historical decisions, fills or costs.

## 8. Persistence guarantees (genuine)
Superseded in detail by §12. Summary: `snapshot()`/`restore()` are the checksummed in-memory primitives; an OPTIONAL `CheckpointStore`
makes them an explicit, atomic on-disk checkpoint with a mandatory write-ahead record before any broker call. Without a configured
store the manager remains in-memory only. No database, exactly-once claim or crash-atomic multi-record update is provided.

## 9. Architecture decisions (ADR-9 re-audited, ADR-10, ADR-11, ADR-12)
**ADR-9/10:** `simulation/` imports research and execution; nothing imports `simulation`; research never imports execution
(AST tests + checker). New import rules keep lifecycle/reconciliation away from risk, sizing, research, strategies and data.

**ADR-11 — cancellation contract (decided in the closure pass).** Conflict: the Stage 3 §9 diagram draws a cancel edge only from
PARTIALLY_FILLED ("remaining qty cancelled or expires"); the domain module called its table "exact"; a Slice 6 test asserted
ACKNOWLEDGED→CANCELLED invalid. Authority for change: **Stage 1 FR-3 (Must)** (submit, modify and *cancel* orders) and the Stage 3
§10 broker interface (`cancel_order`). §9 is silent about, not prohibiting, cancelling a resting, entirely unfilled order, which is
the primary use of cancellation; without the edge a *successful* cancel is unrepresentable. The Slice 6 assertion encoded the
then-implemented contract, not a design requirement. Decision: add exactly one edge, `ACKNOWLEDGED → CANCELLED`, usable only on a
**broker-confirmed** cancel event. NOT added: SUBMITTED→CANCELLED, APPROVED→CANCELLED, RECONCILIATION_REQUIRED→ACKNOWLEDGED (no
acknowledgement ⇒ stays fail-closed). Tests changed (rationale in their docstrings): the Slice 6 simulated-broker test now asserts a
confirmed cancel; one lifecycle test that asserted the old escalation was removed as superseded and replaced by tests of the new
behaviour. This amends a diagram the code called "exact"; it is the smallest change consistent with FR-3 and is recorded for operator ratification.

**ADR-12 — restart persistence.** One explicit, atomic JSON checkpoint file (`CheckpointStore`); no database, queue or new dependency.

## 10. Per-fill fee and average-cost reconciliation (closure)
Each matched fill is compared with the broker's fill report on: fill/order identity (order id, client key, risk decision id),
quantity, price, **total charges**, **itemised components** (brokerage, STT, exchange, SEBI, GST, stamp duty) and **schedule version**.
Missing broker charges ⇒ `CHARGES_UNAVAILABLE_BROKER` (unresolved) — never zero, never recomputed from today's schedule; missing
recorded charges/components/schedule ⇒ the matching `*_UNAVAILABLE` unresolved kind. Position **average cost** (excl. fees, as the
portfolio and broker books define it) is compared three ways (lifecycle-implied, internal portfolio, broker ledger); a source that
cannot supply it yields `AVG_COST_UNAVAILABLE`, not a match. `LedgerView.avg_costs` is additive (default None = unknown).
**Policy:** cash, prices, per-fill charge totals/components, quantities — exact Decimal equality (scale-insensitive: 1.10 == 1.1).
Average cost is a derived quotient, compared with an inclusive absolute tolerance of 1e-9 INR: order-of-operations noise at 28
digits is ~1e-20, and 1e-9 is ~1000x below the smallest economically meaningful difference (1e-6 INR), so it cannot hide a real
error. Material = every mismatch and every unresolved item: `record_reconciliation` raises `RECONCILIATION_MISMATCH` and new
submissions are blocked until an operator clears it with a newer consistent run. **Unchanged caveat:** the offline simulator
uses one cost model everywhere, so agreement proves booking consistency, not that statutory rates or real execution costs are right.

## 11. Event identity and provenance (closure)
`BrokerEvent` gained optional `correlation_id`, `source`, `source_version`, `event_time` (None = unknown). Every event-log row
records: event id, stable identity, idempotency key, order id, broker order id, the record's `correlation_id`
(`corr_<hash of idempotency key>`, shared by submission, events, halts and recovery) plus any event-supplied correlation id,
source and version, `event_time` with `event_time_source` (`event` | `fill.timestamp` | `unknown`), `recorded_at` (injected clock —
distinct from event time), kind, outcome, a clipped (≤200 chars) reason, and the halt id for quarantines. `HaltRecord` gained
`recorded_at`, `correlation_id`, `event_identity`. `AppliedFill` retains charge components, schedule version, order id and source.
Snapshot **v2** carries all of it; **v1** snapshots still restore with these fields = unknown (never invented). Broker free text is
clipped everywhere it is stored; snapshots/checkpoints hold no sessions or credentials. This is not Slice 8's Decision Journal.

## 12. Restart / recovery — exactly what is guaranteed
**Provided and tested:** (a) *mandatory write-ahead checkpoint*: the intent record (state APPROVED) is checkpointed BEFORE the broker is
called; if that write fails nothing is sent (`CheckpointError`, record `LOCAL_FAILURE`, halt `CHECKPOINT_FAILURE`); later checkpoint
failures halt and raise; (b) atomic durable file write (temp + fsync + `os.replace`; a failed write leaves the previous checkpoint
intact); (c) restore validates version, checksum, request identity (caller supplies the original `OrderRequest`s — lifecycle never
manufactures one), transition history (replayed through the real state machine) and fill/state consistency; (d)
`recover_after_restart`: write-ahead records with no outcome become "sent, outcome unknown", every unconfirmed submission is looked up
at the broker by client key (found ⇒ evidence replayed; absent ⇒ closed, retry needs a NEW order), and broker fills/terminal outcomes
are replayed idempotently. It never re-sends and never clears halts. Boundaries covered by tests: before submission; after write-ahead
before acceptance; after acceptance before response; after ack before fills processed; after fill ingestion before portfolio
application; during reconciliation; duplicate/replayed delivery after restore. The broker object is retained across the simulated
manager restart (it stands in for an external broker); a test shows a *fresh* broker honestly reports ABSENT, i.e. recovery depends on
the external system's retained records.
**Not provided (crash windows left fail-closed or out of scope):** (1) a crash between applying a fill to the portfolio and
`mark_portfolio_applied` can re-offer an applied fill as pending; the portfolio application must be idempotent by fill id (the research
portfolio is not) — a double application would surface as a position/cash mismatch and halt; (2) a crash between an in-memory event
application and its checkpoint is recovered only if the broker still reports the evidence (`get_fills`); (3) the original
`OrderRequest` store belongs to sizing/Slice 8 — without it restore refuses; (4) no multi-file/multi-process atomicity, no checkpoint
history, no encryption at rest; (5) nothing here proves exactly-once execution at a real broker.

## 13. Limitations
Simulated broker only; fills are synthetic; risk thresholds remain unapproved examples; the `allow_exit_of_removed_instruments`
flag keeps Slice 6 semantics (exit of a *held* removed instrument only, never a buy), no live policy chosen.
Tests: `tests/unit/test_order_lifecycle.py`, `test_execution_reconciliation.py`, `test_fee_avgcost_reconciliation.py`,
`test_event_provenance.py`, `test_restart_recovery.py`, `tests/adversarial/test_slice7_isolation.py`, `tests/integration/test_slice7_pipeline.py`.
