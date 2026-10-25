# Decision Journal & Observability (Slice 8, ADR-14)

Status: implemented and tested against SYNTHETIC simulation data only. Infrastructure evidence, not proof of alpha,
profitability, broker compatibility or live readiness.

## 1. Canonical decision contract
`DecisionRecord` (Stage 3 §4) remains THE canonical decision artifact. **It gained no fields**, so persisted
`decision_records.jsonl` artifacts from Slices 5-7 are byte-identical and still readable (fixture:
`tests/fixtures/legacy/decision_records_slice7.jsonl`, produced by Slice 7 code; a test re-serialises and compares).
Additive changes only:
* `TerminalState` gained `HOLD`, `NO_TRADE`, `SKIPPED_PENDING_ORDER`, `REJECTED_INVALID_CANDIDATE`. The original eight
  members keep their meaning. `HOLD` (a candidate whose action is HOLD) is distinct from `NO_CANDIDATE` (no candidate
  at all - none is ever invented). These four states must not reference an order (validator).
* `RiskCheckResult` gained `evidence` (tuple of exact `(name, value)` strings captured at evaluation time) and
  `evaluable`. Empty `evidence` means "not captured" - consumers must not reconstruct it. `detail` stays prose.
* Everything else the roadmap asks for (extension data: run context, evidence class, snapshot content, sizing inputs,
  portfolio snapshots, version ids) lives in typed journal event payloads, not in new DecisionRecord fields.

Decision-cycle key: `(run_id, cycle_timestamp, instrument_id, candidate_id | "NO_CANDIDATE")` ->
`decision_id = "dec_" + sha256(...)[:24]`. The journal's `DECISION_FINALIZED` embeds the DecisionRecord with this id; the
legacy per-order id is kept in `legacy_decision_record_id` for cross-reference with `decision_records.jsonl`.

## 2. Journal events (`observability/decision_log`)
Envelope `JournalEvent` (schema_version 1): `event_id`, `run_id`, `decision_id`, monotonic `sequence`, `event_type`,
`links` (order ids, idempotency key, fill id, `decision_ids` for run-level events), `correlation_id`, `producer`,
`producer_version`, `event_time` (when it happened; None = unknown), `data_available_at` (None = unknown / not
captured - the pipeline does not currently capture availability times and records None rather than inventing them),
`recorded_at` (injected clock), `payload`, `prev_hash`, `event_hash`.
Types: DECISION_STARTED, INPUT_SNAPSHOT_LINKED, CANDIDATE_EMITTED, CANDIDATE_REJECTED, RISK_EVALUATED, SIZING_EVALUATED,
ORDER_INTENT, SUBMISSION_RESULT, ORDER_TRANSITION, BROKER_EVENT, FILL_RECORDED, PORTFOLIO_SETTLED, RECONCILIATION_RESULT,
DECISION_FINALIZED, OPERATIONAL_FAILURE, CORRECTION. Required payload keys per type are enforced at append.

Canonicalisation: `research.harness.jsonio.jsonable` (Decimal -> exact string, float -> repr string, datetimes -> UTC ISO,
dataclasses -> `__type__` dicts), then every Enum (even str-mixin) -> its value; sorted keys, compact separators; SHA-256 via
`shared.versioning.content_hash`. `event_hash` covers the envelope incl. `sequence`, `recorded_at`, `prev_hash`.
`content_fingerprint` excludes sequence/recorded_at/hashes and drives idempotency.

Event identity: `evt_ + sha256([run, decision|RUN, type, key])[:24]`. Re-delivery of the same id with identical content is a
no-op (returns the stored event); same id with different content raises `JOURNAL_EVENT_CONFLICT`; different ids with
identical payloads stay separate events. Corrections are new `CORRECTION` events; nothing is ever updated in place.
Re-running an identical configuration against the same journal root is idempotent (tested).

## 3. Storage and durability
`<root>/<run_id>/journal.jsonl`, one canonical JSON event per line, written with `os.write` + `fsync` before success is
returned (directory fsync on creation). Limits, stated plainly: single writer per run stream (no multi-process locking
exists or is claimed); fsync semantics are those of the local filesystem; hash chaining is tamper-EVIDENT, not tamper-proof
(a consistent full rewrite can forge a chain - anchor the head hash elsewhere if that matters). Reopening verifies the whole chain
and **fails closed**; corruption is never truncated or repaired. After any failed write the journal object refuses all further
appends (`JOURNAL_CLOSED_AFTER_FAILURE`). `InMemoryJournal` is an explicit test double (`is_test_double = True`), not a
production backend. `python -m observability.decision_log.verify <root> <run_id>` reports corruption, gaps, hash
mismatches, duplicate ids and truncation (exit 1) and never modifies the file.

## 4. Pipeline integration (`simulation/journaling.py`, `simulation/runner.py`)
`PipelineHarness.run(..., journal_factory=callable(run_id) -> journal, evidence_class="...")`. **A journal is required**: with
no factory the run fails `JOURNAL_FAILURE` before any order is possible; a journal for another run id is rejected.
Written incrementally, in order: DECISION_STARTED + INPUT_SNAPSHOT_LINKED (full feature snapshot values + content hash +
source bar timestamps + pre-decision portfolio) -> CANDIDATE_EMITTED -> RISK_EVALUATED (every check with outcome and
structured evidence) -> SIZING_EVALUATED (inputs, headroom/ceiling, constraints, outcome) -> **ORDER_INTENT (before the broker call)**
-> SUBMISSION_RESULT + ORDER_TRANSITION (idempotent per order/index) -> BROKER_EVENT (incoming evidence before processing) ->
FILL_RECORDED (itemised charges) -> PORTFOLIO_SETTLED (written only after the portfolio booking) -> RECONCILIATION_RESULT ->
DECISION_FINALIZED. HOLD, NO_TRADE, SKIPPED_PENDING_ORDER, NO_CANDIDATE, REJECTED_INVALID_CANDIDATE, vetoes, broker
rejections, cancellations and reconciliation-required outcomes all produce a finalized decision. Reconciliation runs after
finalisation within a cycle, so a finalized record says `reconciliation_at_finalization = PENDING...` and the reader derives
`reconciliation_status` (OK / BLOCKED / NOT_RECORDED) from the later linked events.

Failure behaviour (all tested): pre-submission write fails -> broker never called; post-submission write fails ->
`OrderLifecycleManager.halt_external("JOURNAL_FAILURE")` blocks further submissions, the run fails `JOURNAL_FAILURE`, the order
is recoverable through the existing broker `find_order_by_client_key` + Slice 7 reconciliation (not auto-resolved here);
FILL_RECORDED failure -> no settlement claim; a failed run leaves its decisions `INCOMPLETE` (no fabricated final record).
A failed run attempts a run-level OPERATIONAL_FAILURE event listing the open decisions.

## 5. Query interface (`observability/decision_log/query.py`)
`JournalReader.from_file/from_journal` (refuses an unverified journal unless `allow_unverified`), `verify`, `get_event`,
`events_for_decision`, `list_decisions(limit<=1000, offset)` (journal order, stable), `decision_chain`, `explain`,
`decision_record_from_dict`. Read-only; imports no execution/strategy/risk code (tested in a subprocess). Missing linked
objects are returned as `MissingReference(kind, expected_id, expected_source, referenced_by)`; nothing is regenerated.

## 6. Observability and security
Controlled `ErrorCode` taxonomy; `PipelineRunResult.telemetry` (journal append count/failures/latency, stage seconds,
incomplete input snapshots, reconciliation checks/unresolved mismatches, open decisions) - wall-clock values are NOT persisted into
run artifacts. `journal_ref` (run id, event count, content digest) IS persisted as `journal_ref.json` and is deterministic.
Redaction (`redaction.py`): sensitive keys removed, token-like text masked, text bounded; `JournalError` text is sanitised; no
raw provider responses or headers are stored; no model chain-of-thought is stored (no model exists in this slice).

## 7. Limitations
Single-writer file journal; the in-memory portfolio of `PipelineHarness` is still not crash-resumable; lifecycle and portfolio
checkpoints are separate (not a joint atomic commit); `data_available_at` and the pre-decision portfolio marks are not captured
in every path (recorded as unknown); unrealised P&L is not given at the settlement stage; the simulated broker and portfolio
share one cost calculation, so booking consistency is shown, not statutory-rate correctness; ADR-11 awaits operator
ratification; the roadmap file was not in the workspace. pytest/ruff/mypy are not installed here.
