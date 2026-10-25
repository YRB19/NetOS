"""Journal event envelope, controlled error taxonomy and canonicalisation (Slice 8, ADR-14).

Canonicalisation (single definition, used for every event hash):
  * payload/link values are first normalised by `research.harness.jsonio.jsonable`: Decimal -> exact
    string, float -> repr string, datetime -> UTC ISO-8601, Enum -> value, tuples/sets -> lists;
  * the envelope is then serialised with sorted keys, separators (",", ":"), ensure_ascii=False;
  * hashes are SHA-256 hex via `shared.versioning.content_hash.hash_bytes`.
`content_fingerprint` excludes sequence / recorded_at / prev_hash / event_hash, so an idempotent re-delivery
of the same logical event is recognised even though it would be recorded at a different time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from research.harness.jsonio import jsonable
from shared.versioning.content_hash import hash_bytes

SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64


class ErrorCode(str, Enum):  # noqa: UP042 - repository enum convention
    """Controlled error taxonomy for journal / observability failures."""

    JOURNAL_WRITE_FAILED = "JOURNAL_WRITE_FAILED"
    JOURNAL_EVENT_CONFLICT = "JOURNAL_EVENT_CONFLICT"
    JOURNAL_CORRUPT = "JOURNAL_CORRUPT"
    JOURNAL_SEQUENCE_GAP = "JOURNAL_SEQUENCE_GAP"
    JOURNAL_HASH_MISMATCH = "JOURNAL_HASH_MISMATCH"
    JOURNAL_DUPLICATE_EVENT_ID = "JOURNAL_DUPLICATE_EVENT_ID"
    JOURNAL_UNSUPPORTED_SCHEMA = "JOURNAL_UNSUPPORTED_SCHEMA"
    JOURNAL_INVALID_EVENT = "JOURNAL_INVALID_EVENT"
    JOURNAL_CLOSED_AFTER_FAILURE = "JOURNAL_CLOSED_AFTER_FAILURE"
    JOURNAL_REQUIRED_MISSING = "JOURNAL_REQUIRED_MISSING"
    JOURNAL_REFERENCE_MISSING = "JOURNAL_REFERENCE_MISSING"
    JOURNAL_NOT_FOUND = "JOURNAL_NOT_FOUND"


class JournalError(Exception):
    """Controlled, secret-free journal failure. `str(e)` is already sanitised and bounded."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        from observability.decision_log.redaction import sanitize_text

        self.code = code
        self.message = sanitize_text(message)
        super().__init__(f"{code.value}: {self.message}")


class EventType(str, Enum):  # noqa: UP042
    DECISION_STARTED = "DECISION_STARTED"
    INPUT_SNAPSHOT_LINKED = "INPUT_SNAPSHOT_LINKED"
    CANDIDATE_EMITTED = "CANDIDATE_EMITTED"
    CANDIDATE_REJECTED = "CANDIDATE_REJECTED"
    RISK_EVALUATED = "RISK_EVALUATED"
    SIZING_EVALUATED = "SIZING_EVALUATED"
    ORDER_INTENT = "ORDER_INTENT"  # written BEFORE the broker is called
    SUBMISSION_RESULT = "SUBMISSION_RESULT"
    ORDER_TRANSITION = "ORDER_TRANSITION"
    BROKER_EVENT = "BROKER_EVENT"
    FILL_RECORDED = "FILL_RECORDED"
    PORTFOLIO_SETTLED = "PORTFOLIO_SETTLED"
    RECONCILIATION_RESULT = "RECONCILIATION_RESULT"
    DECISION_FINALIZED = "DECISION_FINALIZED"
    OPERATIONAL_FAILURE = "OPERATIONAL_FAILURE"
    CORRECTION = "CORRECTION"  # a new event referencing an original; the original is never edited


# Required payload keys per event type: the defined (minimal) schema, enforced at append time.
PAYLOAD_REQUIRED_KEYS: dict[EventType, frozenset[str]] = {
    EventType.DECISION_STARTED: frozenset({"instrument_id", "cycle_timestamp", "run_context"}),
    EventType.INPUT_SNAPSHOT_LINKED: frozenset({"snapshot_id", "snapshot_content_hash", "snapshot"}),
    EventType.CANDIDATE_EMITTED: frozenset({"candidate_id", "action", "rationale", "strategy_version_id"}),
    EventType.CANDIDATE_REJECTED: frozenset({"reason", "error_code"}),
    EventType.RISK_EVALUATED: frozenset({"risk_decision_id", "verdict", "risk_rule_version_id", "checks"}),
    EventType.SIZING_EVALUATED: frozenset({"outcome", "reason", "inputs", "quantity"}),
    EventType.ORDER_INTENT: frozenset({"idempotency_key", "instrument_id", "side", "quantity", "risk_decision_id"}),
    EventType.SUBMISSION_RESULT: frozenset({"idempotency_key", "outcome"}),
    EventType.ORDER_TRANSITION: frozenset({"order_id", "from_state", "to_state"}),
    EventType.BROKER_EVENT: frozenset({"kind", "broker_order_id"}),
    EventType.FILL_RECORDED: frozenset({"fill_id", "order_id", "quantity", "price", "charges"}),
    EventType.PORTFOLIO_SETTLED: frozenset({"fill_id", "portfolio_snapshot"}),
    EventType.RECONCILIATION_RESULT: frozenset({"ok", "mismatches"}),
    EventType.DECISION_FINALIZED: frozenset({"terminal_state", "decision_record"}),
    EventType.OPERATIONAL_FAILURE: frozenset({"error_code", "message"}),
    EventType.CORRECTION: frozenset({"corrects_event_id", "reason"}),
}


def _strip_enums(obj: object) -> object:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _strip_enums(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_enums(v) for v in obj]
    return obj


def normalize(obj: object) -> object:
    """jsonable(), then Enum -> its value at every depth (jsonable leaves str-mixin enums as enum objects, which
    would later stringify as 'Cls.MEMBER' under redaction)."""
    return _strip_enums(jsonable(obj))


def canonical_json(obj: object) -> str:
    return json.dumps(jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else jsonable(dt)  # type: ignore[return-value]


@dataclass(frozen=True)
class JournalEvent:
    schema_version: int
    event_id: str
    run_id: str
    sequence: int
    event_type: EventType
    decision_id: str | None
    links: dict  # entity / correlation links (order ids, idempotency key, candidate, risk, fill, decision_ids, ...)
    correlation_id: str
    producer: str
    producer_version: str
    event_time: str | None  # when the thing happened (simulated/market time); None = unknown
    data_available_at: str | None  # when the underlying data became available; None = unknown/not applicable
    recorded_at: str  # when the journal recorded it (injected clock) - distinct from event_time
    payload: dict
    prev_hash: str
    event_hash: str

    def content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version, "event_id": self.event_id, "run_id": self.run_id,
            "event_type": self.event_type.value, "decision_id": self.decision_id, "links": self.links,
            "correlation_id": self.correlation_id, "producer": self.producer,
            "producer_version": self.producer_version, "event_time": self.event_time,
            "data_available_at": self.data_available_at, "payload": self.payload,
        }  # fmt: skip

    def content_fingerprint(self) -> str:
        return hash_bytes(canonical_json(self.content_dict()).encode("utf-8"))

    def hashable_dict(self) -> dict:
        d = self.content_dict()
        d.update(sequence=self.sequence, recorded_at=self.recorded_at, prev_hash=self.prev_hash)
        return d

    def to_dict(self) -> dict:
        d = self.hashable_dict()
        d["event_hash"] = self.event_hash
        return d


def compute_event_hash(hashable: dict) -> str:
    return hash_bytes(canonical_json(hashable).encode("utf-8"))


def event_from_dict(d: dict) -> JournalEvent:
    if not isinstance(d, dict):
        raise JournalError(ErrorCode.JOURNAL_CORRUPT, "journal record is not a JSON object")
    ver = d.get("schema_version")
    if ver != SCHEMA_VERSION:
        raise JournalError(ErrorCode.JOURNAL_UNSUPPORTED_SCHEMA,
                           f"unsupported journal schema_version {ver!r}; this reader supports {SCHEMA_VERSION}")  # fmt: skip
    try:
        return JournalEvent(
            schema_version=ver, event_id=d["event_id"], run_id=d["run_id"], sequence=int(d["sequence"]),
            event_type=EventType(d["event_type"]), decision_id=d.get("decision_id"), links=dict(d["links"]),
            correlation_id=d["correlation_id"], producer=d["producer"], producer_version=d["producer_version"],
            event_time=d.get("event_time"), data_available_at=d.get("data_available_at"),
            recorded_at=d["recorded_at"], payload=dict(d["payload"]), prev_hash=d["prev_hash"],
            event_hash=d["event_hash"],
        )  # fmt: skip
    except (KeyError, ValueError, TypeError) as e:
        raise JournalError(ErrorCode.JOURNAL_CORRUPT, f"malformed journal record: {type(e).__name__}: {e}") from e
