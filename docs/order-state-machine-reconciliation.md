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
| ACKNOWLEDGED | PARTIALLY_FILLED / FILLED / REJECTED / RECONCILIATION_REQUIRED | fill event(s) / broker reject |
| PARTIALLY_FILLED | FILLED / CANCELLED / RECONCILIATION_REQUIRED | fill / **cancel confirmed** |
| RECONCILIATION_REQUIRED | FILLED / PARTIALLY_FILLED / CANCELLED / REJECTED | operator resolution consistent with accounted fills |
| FILLED, CANCELLED, REJECTED | — (terminal, never reopened) | — |
Never occur: CANDIDATE→FILLED, any skip of APPROVED, any move out of a terminal state, RECONCILIATION_REQUIRED→ACKNOWLEDGED.

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
| CANCEL_CONFIRMED | ACK/SUBMITTED (no fills) | quarantine, → RECONCILIATION_REQUIRED (**no legal edge in the contract**, see §9) |
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
In-memory by design. `snapshot()` / `restore()` give an explicit, checksum-protected JSON round trip; restore replays order
history through the real state machine and requires the caller to supply the original `OrderRequest` objects (this
package never constructs one). A restored manager keeps idempotency, quarantine and halts. **Not provided:** durable storage,
crash-atomic multi-record updates, restart survival without an explicit snapshot. The interrupted-portfolio-update case
is covered by a recoverable workflow (`fills_pending_portfolio_application` / `mark_portfolio_applied`; reconciliation reports
pending application as unresolved), not by a transaction.

## 9. Architecture decision (ADR-10; ADR-9 re-audited)
`simulation/` imports research and execution; nothing imports `simulation`; research never imports execution — verified by AST test
and the checker. This is valid under ADR-9 and needs no change. New rules (ADR-10): lifecycle/reconciliation cannot import
risk engine, sizing, research, simulation, intelligence, governance or data adapters; risk/sizing/broker cannot import them;
lifecycle cannot import reconciliation. Open decision for the operator (not made here): add an `ACKNOWLEDGED -> CANCELLED`
edge (and possibly `RECONCILIATION_REQUIRED -> ACKNOWLEDGED`) to the domain contract so cancelling an unfilled order is not an escalation.
A Slice 6 test deliberately asserts the current contract, so it was left untouched.

## 10. Limitations
Simulated broker only; fills are synthetic; no durable store; risk thresholds remain unapproved examples; the
`allow_exit_of_removed_instruments` flag keeps Slice 6 semantics (exit of a *held* removed instrument only, never a buy) and no live policy is chosen.
Tests: `tests/unit/test_order_lifecycle.py`, `test_execution_reconciliation.py`, `tests/adversarial/test_slice7_isolation.py`,
`tests/integration/test_slice7_pipeline.py`.
