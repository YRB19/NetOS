"""Deterministic event-identity helper on top of a journal (Slice 8). Producer-side, write path."""

from __future__ import annotations

from datetime import datetime

from observability.decision_log.events import EventType, JournalEvent
from observability.decision_log.journal import DecisionJournal
from shared.versioning.content_hash import hash_json_stable


def decision_id_for(run_id: str, cycle_timestamp: datetime, instrument_id: str, candidate_id: str | None) -> str:
    """Decision-cycle key = (run, cycle timestamp, instrument, candidate-or-NO_CANDIDATE).

    An empty strategy output is represented by the literal "NO_CANDIDATE" - no candidate is ever invented."""
    return "dec_" + hash_json_stable([run_id, cycle_timestamp.isoformat(), instrument_id, candidate_id or "NO_CANDIDATE"])[:24]


class JournalRecorder:
    def __init__(self, journal: DecisionJournal, producer: str, producer_version: str) -> None:
        self.journal = journal
        self.run_id = journal.run_id
        self.producer = producer
        self.producer_version = producer_version
        self.correlation_id = "corr_" + hash_json_stable([journal.run_id])[:20]

    def event_id(self, event_type: EventType, decision_id: str | None, key: str = "") -> str:
        return "evt_" + hash_json_stable([self.run_id, decision_id or "RUN", event_type.value, key])[:24]

    def emit(self, event_type: EventType, payload: dict, *, decision_id: str | None = None, key: str = "",
             links: dict | None = None, event_time: datetime | None = None,
             data_available_at: datetime | None = None) -> JournalEvent:
        return self.journal.append(
            event_type, self.event_id(event_type, decision_id, key), payload, decision_id=decision_id,
            links=links, correlation_id=self.correlation_id, producer=self.producer,
            producer_version=self.producer_version, event_time=event_time, data_available_at=data_available_at,
        )  # fmt: skip
