"""Operator local-file disclosure import (Slice 11, Plane 1 adapter).

Reads a JSON array or JSONL file of disclosure items the OPERATOR obtained from an official
source. This adapter performs NO network access and invents no exchange API. It does not claim
that the items are authentic: `source_id` and `source_reference` are recorded as DECLARED by the
operator, and provenance verification remains the operator's responsibility.

Item fields (all timestamps must be ISO-8601 WITH an explicit UTC offset; naive times are rejected):
  source_document_id (required)  published_at (required)  text (required)
  exchange, symbol, isin         instrument identity as supplied; mapped EXACTLY, never fuzzily
  event_time, available_at, ingested_at (optional; ingested_at defaults to the import clock)
  title, source_reference, retention_note, revises_source_document_id (optional)

available_at defaults to max(published_at, ingested_at). An earlier available_at is rejected. When
backtesting history, a document ingested today is, correctly, NOT available to a past decision
unless the operator supplies a verified original `ingested_at`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from data.disclosures.source import SourceStatus
from data.disclosures.store import DisclosureStore
from domain.models.disclosure import DisclosureRecord, DisclosureStatus, text_hash
from shared.versioning.content_hash import hash_json_stable

LOCAL_SOURCE_ID = "OPERATOR_LOCAL_IMPORT"
MAX_TEXT_CHARS = 20_000


@dataclass(frozen=True)
class InstrumentMap:
    """Exact-match instrument mapping supplied by the operator. No name matching, ever."""

    by_isin: Mapping[str, str]
    by_exchange_symbol: Mapping[tuple[str, str], str]

    def resolve(self, exchange: str | None, symbol: str | None, isin: str | None):
        """-> (instrument_id | None, warnings, conflict)"""
        a = self.by_isin.get(isin) if isin else None
        b = self.by_exchange_symbol.get((exchange, symbol)) if exchange and symbol else None
        if a and b and a != b:
            return None, ("isin and exchange/symbol map to different instruments",), True
        return (a or b), (), False


def _ts(v: object, name: str, errs: list[str]) -> datetime | None:
    if v is None or v == "":
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        errs.append(f"{name} is not ISO-8601")
        return None
    if d.tzinfo is None:
        errs.append(f"{name} has no UTC offset (naive timestamps are rejected)")
        return None
    return d.astimezone(UTC)


class LocalDisclosureImport:
    source_id = LOCAL_SOURCE_ID

    def __init__(self, path: str | Path, clock: Callable[[], datetime] | None = None) -> None:
        self.path = Path(path)
        self._clock = clock or (lambda: datetime.now(UTC))

    def status(self) -> SourceStatus:
        return SourceStatus.LOCAL_IMPORT

    def read_raw(self) -> Iterable[dict]:
        raw = self.path.read_text(encoding="utf-8")
        s = raw.lstrip()
        if s.startswith("["):
            items = json.loads(raw)
        else:
            items = [json.loads(line) for line in raw.splitlines() if line.strip()]
        if not all(isinstance(i, dict) for i in items):
            raise ValueError("every disclosure item must be a JSON object")
        return items

    def load_into(self, store: DisclosureStore, instruments: InstrumentMap) -> dict:
        """Parse, validate, map and add. Returns an honest import report (no silent drops)."""
        report = {"source_id": self.source_id, "read": 0, "added": 0, "idempotent": 0,
                  "by_status": {}, "rejections": []}  # fmt: skip
        ingest_default = self._clock()
        for item in self.read_raw():
            report["read"] += 1
            rec = self._to_record(item, instruments, ingest_default)
            outcome = store.add(rec)
            report["added" if outcome == "ADDED" else "idempotent"] += 1
            report["by_status"][rec.status.value] = report["by_status"].get(rec.status.value, 0) + 1
            if rec.status in (DisclosureStatus.REJECTED, DisclosureStatus.UNMAPPED):
                report["rejections"].append(
                    {
                        "document_id": rec.document_id,
                        "status": rec.status.value,
                        "warnings": list(rec.warnings),
                    }
                )
        return report

    # ------------------------------------------------------------------
    def _to_record(
        self, item: dict, instruments: InstrumentMap, ingest_default: datetime
    ) -> DisclosureRecord:
        errs: list[str] = []
        src_id = str(item.get("source_document_id") or "").strip()
        text = item.get("text")
        text = text if isinstance(text, str) else None
        if not src_id:
            errs.append("source_document_id missing")
        if text is None or not text.strip():
            errs.append("text missing or empty")
        elif len(text) > MAX_TEXT_CHARS:
            errs.append(f"text exceeds {MAX_TEXT_CHARS} characters")
        published = _ts(item.get("published_at"), "published_at", errs)
        if published is None and not any(e.startswith("published_at") for e in errs):
            errs.append("published_at missing")
        event = _ts(item.get("event_time"), "event_time", errs)
        ingested = _ts(item.get("ingested_at"), "ingested_at", errs) or ingest_default.astimezone(
            UTC
        )
        avail = _ts(item.get("available_at"), "available_at", errs)
        if published is not None:
            floor = max(published, ingested)
            if avail is None:
                avail = floor
            elif avail < floor:
                errs.append("available_at precedes published_at/ingested_at")
        exch, sym, isin = item.get("exchange"), item.get("symbol"), item.get("isin")
        inst, warns, conflict = instruments.resolve(exch, sym, isin)
        content = text_hash(text) if text else text_hash("")
        doc_id = "disc_" + hash_json_stable([LOCAL_SOURCE_ID, src_id, content])[:24]
        revises = item.get("revises_source_document_id")
        # revises refers to a SOURCE doc id; the store resolves it to the original record's document_id
        common = dict(
            document_id=doc_id, source_id=LOCAL_SOURCE_ID, source_document_id=src_id or "UNKNOWN",
            exchange=exch, symbol=sym, isin=isin, event_time=event, published_at=published, ingested_at=ingested,
            content_hash=content, text=text, source_reference=item.get("source_reference"),
            title=str(item.get("title") or ""), retention_note=str(item.get("retention_note") or ""),
        )  # fmt: skip
        if errs:
            return DisclosureRecord(**{**common, "available_at": None, "instrument_id": None, "text": None,
                                       "content_hash": content}, status=DisclosureStatus.REJECTED,
                                    warnings=tuple(errs))  # fmt: skip
        if inst is None:
            why = warns or ("instrument not mapped by exact isin or exchange/symbol",)
            return DisclosureRecord(**{**common, "available_at": None, "instrument_id": None, "text": None},
                                    status=DisclosureStatus.UNMAPPED, warnings=tuple(why))  # fmt: skip
        # A revision names the SOURCE document it revises; the store links by source_document_id.
        revises_doc = f"src:{revises}" if revises else None
        dup = "dup_" + hash_json_stable([inst, content])[:16]
        return DisclosureRecord(**common, available_at=avail, instrument_id=inst, status=DisclosureStatus.VALID,
                                duplicate_group_id=dup, revises_document_id=revises_doc)  # fmt: skip
