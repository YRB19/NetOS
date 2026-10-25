"""Durable, append-only, hash-chained decision journal (Slice 8, ADR-14).

Storage: one JSONL file per run stream at `<root>/<run_id>/journal.jsonl` (stdlib only, portable,
reviewable). Each line is one immutable `JournalEvent` carrying a monotonic `sequence`, the previous
event's hash and its own hash. An append is flushed and fsync'd before success is reported.

Guarantees and limits (honest):
  * SINGLE WRITER per run stream (one process). No multi-process locking is implemented or claimed.
  * fsync gives durability against process crash on a normal local filesystem; it is not a claim about
    power-loss behaviour of every storage stack.
  * Corruption/truncation is DETECTED (fail closed on open and by `verify`), never silently repaired.
  * After any failed write the journal object refuses further appends (JOURNAL_CLOSED_AFTER_FAILURE).
  * Hash chaining is tamper-EVIDENT, not tamper-proof: someone who rewrites the whole file consistently
    can forge a chain; anchor `head_hash` externally if that threat matters.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from observability.decision_log.events import (
    GENESIS_HASH,
    PAYLOAD_REQUIRED_KEYS,
    SCHEMA_VERSION,
    ErrorCode,
    EventType,
    JournalError,
    JournalEvent,
    canonical_json,
    compute_event_hash,
    event_from_dict,
    normalize,
)
from observability.decision_log.redaction import sanitize
from research.harness.jsonio import jsonable
from shared.time.clock import utc_now
from shared.versioning.content_hash import hash_bytes

JOURNAL_FILENAME = "journal.jsonl"


def journal_path(root: Path | str, run_id: str) -> Path:
    return Path(root) / run_id / JOURNAL_FILENAME


@dataclass(frozen=True)
class VerificationReport:
    ok: bool
    event_count: int
    head_hash: str
    content_digest: str
    errors: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (ErrorCode value, detail)


def content_digest_of(events: list[JournalEvent]) -> str:
    """Deterministic digest of logical content only (excludes recorded_at / chain hashes)."""
    return hash_bytes(canonical_json([e.content_fingerprint() for e in events]).encode("utf-8"))


def verify_lines(lines: list[str], run_id: str | None = None) -> tuple[list[JournalEvent], VerificationReport]:
    """Parse + verify raw JSONL lines, collecting EVERY problem (no repair, no skipping)."""
    errs: list[tuple[str, str]] = []
    events: list[JournalEvent] = []
    for n, line in enumerate(lines, 1):
        try:
            events.append(event_from_dict(json.loads(line)))
        except json.JSONDecodeError as e:
            errs.append((ErrorCode.JOURNAL_CORRUPT.value, f"line {n}: not valid JSON ({e.msg}); truncated or corrupt"))
        except JournalError as e:
            errs.append((e.code.value, f"line {n}: {e.message}"))
    seen: dict[str, int] = {}
    prev = GENESIS_HASH
    for i, ev in enumerate(events, 1):
        if run_id is not None and ev.run_id != run_id:
            errs.append((ErrorCode.JOURNAL_CORRUPT.value, f"event {ev.event_id}: run_id {ev.run_id!r} != stream {run_id!r}"))
        if ev.event_id in seen:
            errs.append((ErrorCode.JOURNAL_DUPLICATE_EVENT_ID.value, f"event_id {ev.event_id} repeated (sequences {seen[ev.event_id]}, {ev.sequence})"))
        seen.setdefault(ev.event_id, ev.sequence)
        if ev.sequence != i:
            errs.append((ErrorCode.JOURNAL_SEQUENCE_GAP.value, f"expected sequence {i}, found {ev.sequence} (event {ev.event_id})"))
        if ev.prev_hash != prev:
            errs.append((ErrorCode.JOURNAL_HASH_MISMATCH.value, f"sequence {ev.sequence}: prev_hash does not match preceding event"))
        if compute_event_hash(ev.hashable_dict()) != ev.event_hash:
            errs.append((ErrorCode.JOURNAL_HASH_MISMATCH.value, f"sequence {ev.sequence}: event_hash does not match content"))
        prev = ev.event_hash
    head = events[-1].event_hash if events else GENESIS_HASH
    return events, VerificationReport(not errs, len(events), head, content_digest_of(events), tuple(errs))


def read_journal_file(path: Path | str) -> tuple[list[JournalEvent], VerificationReport]:
    p = Path(path)
    if not p.exists():
        raise JournalError(ErrorCode.JOURNAL_NOT_FOUND, f"no journal at {p.name}")
    raw = p.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    lines = text.split("\n")
    errs: list[tuple[str, str]] = []
    if lines and lines[-1] == "":
        lines.pop()
    elif raw:
        errs.append((ErrorCode.JOURNAL_CORRUPT.value, "file does not end with a newline: truncated final record"))
    events, rep = verify_lines(lines)
    if errs:
        rep = VerificationReport(False, rep.event_count, rep.head_hash, rep.content_digest, tuple(errs) + rep.errors)
    return events, rep


class DecisionJournal:
    """Base journal: validation, idempotency, chaining. Subclasses supply `_persist`."""

    is_test_double = False

    def __init__(self, run_id: str, clock: Callable[[], datetime] = utc_now) -> None:
        if not run_id or not isinstance(run_id, str):
            raise JournalError(ErrorCode.JOURNAL_INVALID_EVENT, "run_id must be a non-empty string")
        self.run_id = run_id
        self._clock = clock
        self._events: list[JournalEvent] = []
        self._by_id: dict[str, JournalEvent] = {}
        self._failed = False
        self.append_latencies_ms: list[float] = []  # observability: journal append latency
        self.append_failures = 0

    # --- storage hook -------------------------------------------------------
    def _persist(self, line: str) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def _load(self, events: list[JournalEvent]) -> None:
        self._events = list(events)
        self._by_id = {e.event_id: e for e in events}

    # --- read ---------------------------------------------------------------
    def events(self) -> tuple[JournalEvent, ...]:
        return tuple(self._events)

    def get(self, event_id: str) -> JournalEvent | None:
        return self._by_id.get(event_id)

    @property
    def head_hash(self) -> str:
        return self._events[-1].event_hash if self._events else GENESIS_HASH

    @property
    def failed(self) -> bool:
        return self._failed

    def content_digest(self) -> str:
        return content_digest_of(self._events)

    def reference(self) -> dict:
        return {"run_id": self.run_id, "event_count": len(self._events), "content_digest": self.content_digest(),
                "schema_version": SCHEMA_VERSION}  # fmt: skip

    # --- write --------------------------------------------------------------
    def append(self, event_type: EventType, event_id: str, payload: dict, *, decision_id: str | None = None,
               links: dict | None = None, correlation_id: str, producer: str, producer_version: str,
               event_time: datetime | None = None, data_available_at: datetime | None = None) -> JournalEvent:  # noqa: PLR0913
        if self._failed:
            raise JournalError(ErrorCode.JOURNAL_CLOSED_AFTER_FAILURE, "journal refused: an earlier write failed")
        if not isinstance(event_type, EventType) or not event_id or not isinstance(payload, dict):
            raise JournalError(ErrorCode.JOURNAL_INVALID_EVENT, "event_type/event_id/payload invalid")
        missing = PAYLOAD_REQUIRED_KEYS[event_type] - set(payload)
        if missing:
            raise JournalError(ErrorCode.JOURNAL_INVALID_EVENT, f"{event_type.value} payload missing keys {sorted(missing)}")
        norm_payload = sanitize(normalize(payload))
        norm_links = sanitize(normalize(links or {}))
        probe = JournalEvent(
            SCHEMA_VERSION, event_id, self.run_id, 0, event_type, decision_id, norm_links, correlation_id,  # type: ignore[arg-type]
            producer, producer_version, _iso(event_time), _iso(data_available_at), "", norm_payload, "", "",  # type: ignore[arg-type]
        )
        existing = self._by_id.get(event_id)
        if existing is not None:
            if existing.content_fingerprint() == probe.content_fingerprint():
                return existing  # idempotent re-delivery: no second event, no second effect
            raise JournalError(ErrorCode.JOURNAL_EVENT_CONFLICT, f"event_id {event_id} reused with a different payload")
        t0 = time.perf_counter()
        seq = len(self._events) + 1
        prev = self.head_hash
        recorded = _iso(self._clock()) or ""
        hashable = {**probe.content_dict(), "sequence": seq, "recorded_at": recorded, "prev_hash": prev}
        ev = JournalEvent(SCHEMA_VERSION, event_id, self.run_id, seq, event_type, decision_id, norm_links,  # type: ignore[arg-type]
                          correlation_id, producer, producer_version, probe.event_time, probe.data_available_at,
                          recorded, norm_payload, prev, compute_event_hash(hashable))  # fmt: skip
        try:
            self._persist(canonical_json(ev.to_dict()) + "\n")
        except Exception as e:  # noqa: BLE001 - any persistence failure is fatal for this journal object
            self._failed = True
            self.append_failures += 1
            raise JournalError(ErrorCode.JOURNAL_WRITE_FAILED, f"append failed: {type(e).__name__}") from e
        self._events.append(ev)
        self._by_id[event_id] = ev
        self.append_latencies_ms.append((time.perf_counter() - t0) * 1000.0)
        return ev

    def verify(self) -> VerificationReport:
        lines = [canonical_json(e.to_dict()) for e in self._events]
        return verify_lines(lines, self.run_id)[1]


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else jsonable(dt)  # type: ignore[return-value]


class FileDecisionJournal(DecisionJournal):
    """Production durable backend (JSONL + fsync). Re-opening verifies the whole chain and fails closed."""

    def __init__(self, root: Path | str, run_id: str, clock: Callable[[], datetime] = utc_now) -> None:
        super().__init__(run_id, clock)
        self.path = journal_path(root, run_id)
        if self.path.exists():
            events, rep = read_journal_file(self.path)
            if not rep.ok:
                raise JournalError(ErrorCode(rep.errors[0][0]), f"existing journal failed verification: {rep.errors[0][1]}")
            if any(e.run_id != run_id for e in events):
                raise JournalError(ErrorCode.JOURNAL_CORRUPT, "existing journal belongs to a different run")
            self._load(events)

    def _persist(self, line: str) -> None:
        new_dir = not self.path.parent.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        if new_dir or len(self._events) == 0:
            dfd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)


class InMemoryJournal(DecisionJournal):
    """EXPLICIT TEST DOUBLE. Not durable; never the production backend. `is_test_double` is True."""

    is_test_double = True

    def __init__(self, run_id: str = "pending", clock: Callable[[], datetime] = utc_now) -> None:
        super().__init__(run_id, clock)
        self.lines: list[str] = []

    def bind_run(self, run_id: str) -> None:
        if self._events and run_id != self.run_id:
            raise JournalError(ErrorCode.JOURNAL_INVALID_EVENT, "cannot rebind a non-empty journal")
        self.run_id = run_id

    def _persist(self, line: str) -> None:
        self.lines.append(line)
