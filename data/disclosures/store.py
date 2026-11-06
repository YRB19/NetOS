"""In-memory, append-only disclosure store with point-in-time retrieval (Slice 11, Plane 1).

Nothing is overwritten: re-adding an identical record is idempotent, a changed document under
the same source id becomes a NEW record (different content hash => different document_id), and a
declared revision keeps the original. Retrieval applies the single availability gate
`available_at <= decision_timestamp` and accounts for everything it leaves out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from domain.models.disclosure import (
    USABLE_STATUSES,
    DisclosureContext,
    DisclosureRecord,
    DisclosureStatus,
)

DEFAULT_MAX_DOCUMENTS = 5
DEFAULT_LOOKBACK_DAYS = 14
MAX_DOCUMENTS_HARD_CAP = 20  # no unbounded news history per snapshot, ever


@dataclass(frozen=True)
class ContextConfig:
    max_documents: int = DEFAULT_MAX_DOCUMENTS
    lookback_days: int = DEFAULT_LOOKBACK_DAYS

    def __post_init__(self) -> None:
        if not (1 <= self.max_documents <= MAX_DOCUMENTS_HARD_CAP):
            raise ValueError(f"max_documents must be within [1, {MAX_DOCUMENTS_HARD_CAP}]")
        if not (1 <= self.lookback_days <= 366):
            raise ValueError("lookback_days must be within [1, 366]")


class DisclosureStore:
    def __init__(self) -> None:
        self._records: dict[str, DisclosureRecord] = {}
        self._order: list[str] = []

    # ------------------------------------------------------------------ write
    def add(self, rec: DisclosureRecord) -> str:
        """Returns 'ADDED' | 'IDEMPOTENT'. Never overwrites."""
        existing = self._records.get(rec.document_id)
        if existing is not None:
            if existing == rec:
                return "IDEMPOTENT"
            raise ValueError(f"document_id {rec.document_id} reused with different content")
        self._records[rec.document_id] = rec
        self._order.append(rec.document_id)
        return "ADDED"

    def records(self) -> tuple[DisclosureRecord, ...]:
        return tuple(self._records[i] for i in self._order)

    def counts_by_status(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self._records.values():
            out[r.status.value] = out.get(r.status.value, 0) + 1
        return out

    # ------------------------------------------------------------------- read
    def build_context(
        self,
        instrument_id: str,
        decision_timestamp: datetime,
        config: ContextConfig | None = None,
        input_snapshot_id: str | None = None,
    ) -> DisclosureContext:
        cfg = config or ContextConfig()
        floor = decision_timestamp - timedelta(days=cfg.lookback_days)
        excluded: dict[str, int] = {}

        def _x(reason: str) -> None:
            excluded[reason] = excluded.get(reason, 0) + 1

        cand: list[DisclosureRecord] = []
        for r in self.records():
            if r.instrument_id != instrument_id:
                continue
            if r.status not in USABLE_STATUSES:
                continue  # unmapped/rejected never enter a context (counted at ingestion)
            if r.available_at is None or r.available_at > decision_timestamp:
                _x("NOT_YET_AVAILABLE")
                continue
            if r.available_at < floor:
                _x("STALE_OUTSIDE_LOOKBACK")
                continue
            cand.append(r)

        # A revision that is itself available supersedes the original it revises.
        # `revises_document_id` is either an internal document_id or "src:<source_document_id>".
        superseded_ids = {r.revises_document_id for r in cand if r.revises_document_id}
        kept: list[DisclosureRecord] = []
        for r in cand:
            if r.document_id in superseded_ids or f"src:{r.source_document_id}" in superseded_ids:
                _x("SUPERSEDED_BY_AVAILABLE_REVISION")
            else:
                kept.append(r)

        # Exact duplicates: keep the earliest-available of each duplicate group.
        kept.sort(key=lambda r: (r.available_at, r.document_id))
        seen: set[str] = set()
        unique: list[DisclosureRecord] = []
        for r in kept:
            g = r.duplicate_group_id or r.content_hash
            if g in seen:
                _x("DUPLICATE")
                continue
            seen.add(g)
            unique.append(r)

        # Bounded: keep the most recent N (by availability), present oldest->newest.
        if len(unique) > cfg.max_documents:
            excluded["OVER_MAX_DOCUMENTS"] = len(unique) - cfg.max_documents
            unique = unique[-cfg.max_documents :]
        return DisclosureContext(
            instrument_id=instrument_id,
            decision_timestamp=decision_timestamp,
            documents=tuple(unique),
            max_documents=cfg.max_documents,
            lookback_days=cfg.lookback_days,
            excluded_counts=tuple(sorted(excluded.items())),
            input_snapshot_id=input_snapshot_id,
        )


def status_label(s: DisclosureStatus) -> str:
    return s.value
