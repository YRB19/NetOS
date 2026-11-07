"""Disclosure records and bounded disclosure context (Slice 11, Stage 3 §13).

A `DisclosureRecord` is one immutable, attributable corporate announcement/disclosure that
an operator (or a verified source adapter) supplied. It carries FOUR separate times so a
point-in-time rule can never be confused with an event date:

    event_time        when the underlying corporate event happened (as stated by the source)
    published_at      when the source says it published the document
    ingested_at       when NetOS ingested it
    available_at      the instant from which NetOS may use it in a decision
                      (>= published_at and >= ingested_at; never earlier than either)

Rule (no exceptions): a record may influence a decision only when
`available_at <= decision_timestamp`. A revision is a SEPARATE record that references the one
it revises (`revises_document_id`); the original is never overwritten.

`DisclosureContext` is the bounded, immutable, hash-addressed input handed to Plane 2 for ONE
instrument at ONE decision timestamp. It is what makes a historical model input reconstructable.

No logic that touches the network, the filesystem or a model lives here (domain is pure data).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from domain.models._validators import require_aware_utc, require_non_empty_str


class DisclosureStatus(str, Enum):  # noqa: UP042 - repository enum convention
    VALID = "VALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    UNMAPPED = "UNMAPPED"  # instrument could not be mapped exactly; never used in a context
    REJECTED = "REJECTED"  # failed validation; never used in a context


# Statuses that are allowed to enter a DisclosureContext.
USABLE_STATUSES = frozenset({DisclosureStatus.VALID, DisclosureStatus.VALID_WITH_WARNINGS})


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DisclosureRecord:
    document_id: str  # stable internal id (derived from source identity + content hash)
    source_id: str  # declared source identity, e.g. "OPERATOR_LOCAL_IMPORT"
    source_document_id: str  # the identifier the source itself uses (never invented)
    instrument_id: str | None  # canonical instrument id; None only when status is UNMAPPED/REJECTED
    exchange: str | None  # as supplied by the source
    symbol: str | None  # as supplied by the source
    isin: str | None  # as supplied; verified only when the mapping used it
    event_time: datetime | None
    published_at: datetime | None
    ingested_at: datetime
    available_at: datetime | None
    content_hash: str  # sha256 of the exact text
    text: str | None  # parsed text, only when retention terms allow
    source_reference: str | None  # permitted source reference / URL / local file path label
    title: str = ""
    status: DisclosureStatus = DisclosureStatus.VALID
    warnings: tuple[str, ...] = field(default_factory=tuple)
    duplicate_group_id: str = ""  # same content_hash + instrument => same group
    revises_document_id: str | None = None
    retention_note: str = ""  # source usage/retention metadata, free text, as supplied

    def __post_init__(self) -> None:
        require_non_empty_str(self.document_id, "document_id")
        require_non_empty_str(self.source_id, "source_id")
        require_non_empty_str(self.source_document_id, "source_document_id")
        require_non_empty_str(self.content_hash, "content_hash")
        object.__setattr__(self, "ingested_at", require_aware_utc(self.ingested_at, "ingested_at"))
        for name in ("event_time", "published_at", "available_at"):
            v = getattr(self, name)
            if v is not None:
                object.__setattr__(self, name, require_aware_utc(v, name))
        if not isinstance(self.status, DisclosureStatus):
            raise ValueError(f"status must be a DisclosureStatus, got: {self.status!r}")
        object.__setattr__(self, "warnings", tuple(self.warnings))
        if self.status in USABLE_STATUSES:
            if not self.instrument_id:
                raise ValueError("a usable DisclosureRecord requires a mapped instrument_id")
            if self.published_at is None or self.available_at is None:
                raise ValueError("a usable DisclosureRecord requires published_at and available_at")
            if self.available_at < self.published_at or self.available_at < self.ingested_at:
                raise ValueError("available_at must not precede published_at or ingested_at")
            if self.text is None or not self.text.strip():
                raise ValueError("a usable DisclosureRecord requires non-empty text")
            if text_hash(self.text) != self.content_hash:
                raise ValueError("content_hash does not match text")

    def is_usable_at(self, decision_timestamp: datetime) -> bool:
        """The ONLY availability gate: available_at <= decision_timestamp."""
        return (
            self.status in USABLE_STATUSES
            and self.available_at is not None
            and self.available_at <= decision_timestamp
        )


@dataclass(frozen=True, slots=True)
class DisclosureContext:
    """Bounded, immutable model input for one instrument at one decision timestamp."""

    instrument_id: str
    decision_timestamp: datetime
    documents: tuple[DisclosureRecord, ...]  # sorted (available_at, document_id); bounded
    max_documents: int
    lookback_days: int
    excluded_counts: tuple[tuple[str, int], ...] = ()  # (reason, n) for explicit accounting
    input_snapshot_id: str | None = None  # FeatureSnapshot.snapshot_id this context pairs with
    context_hash: str = ""

    def __post_init__(self) -> None:
        require_non_empty_str(self.instrument_id, "instrument_id")
        object.__setattr__(
            self, "decision_timestamp", require_aware_utc(self.decision_timestamp, "decision_timestamp")
        )
        object.__setattr__(self, "documents", tuple(self.documents))
        for d in self.documents:
            if not d.is_usable_at(self.decision_timestamp):
                raise ValueError(
                    f"document {d.document_id} is not usable at {self.decision_timestamp.isoformat()} "
                    "(point-in-time violation)"
                )
            if d.instrument_id != self.instrument_id:
                raise ValueError("document instrument_id does not match context instrument_id")
        if len(self.documents) > self.max_documents:
            raise ValueError("context exceeds max_documents")
        expected = self.compute_hash()
        if self.context_hash and self.context_hash != expected:
            raise ValueError("context_hash does not match context content")
        object.__setattr__(self, "context_hash", expected)

    def compute_hash(self) -> str:
        body = {
            "instrument_id": self.instrument_id,
            "decision_timestamp": self.decision_timestamp.isoformat(),
            "documents": [[d.document_id, d.content_hash] for d in self.documents],
            "max_documents": self.max_documents,
            "lookback_days": self.lookback_days,
        }
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]

    @property
    def is_empty(self) -> bool:
        return not self.documents

    @property
    def document_ids(self) -> tuple[str, ...]:
        return tuple(d.document_id for d in self.documents)
