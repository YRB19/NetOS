"""RawMarketObservation domain model.

Stage 3 §5 requires raw source data be preserved before any transformation: "Never overwrite
the original historical observation merely because normalization or adjustment occurs... A
future researcher must be able to determine: What did the source actually provide?"

This object is deliberately permissive on its `fields` payload (an opaque mapping of exactly
what the source gave us, field names untouched) because different sources have different
schemas and this object's whole job is to NOT normalize anything. Validation/typing happens
downstream, in data/validation and data/normalization, never here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shared.versioning.content_hash import hash_json_stable


@dataclass(frozen=True)
class RawMarketObservation:
    source: str
    source_row_ref: str  # e.g. "file.csv:line 42" — where this record physically came from
    fields: Mapping[str, Any]  # the untouched, source-native field names/values
    ingestion_time: datetime  # UTC-aware, when *we* pulled this record in

    def __post_init__(self) -> None:
        if not self.source or not self.source.strip():
            raise ValueError("RawMarketObservation.source must be a non-empty string.")
        if not self.source_row_ref or not self.source_row_ref.strip():
            raise ValueError("RawMarketObservation.source_row_ref must be a non-empty string.")
        if self.fields is None or len(self.fields) == 0:
            raise ValueError("RawMarketObservation.fields must be a non-empty mapping.")
        if self.ingestion_time.tzinfo is None:
            raise ValueError("RawMarketObservation.ingestion_time must be timezone-aware (UTC).")

    @property
    def raw_id(self) -> str:
        """Deterministic content-derived identity of this exact raw observation.

        Two RawMarketObservation instances with identical (source, source_row_ref, fields)
        always produce the same raw_id, regardless of when they were ingested — ingestion_time
        is deliberately excluded from the hash so re-ingesting the same historical file twice
        is recognizable as "the same raw record," which is what duplicate-detection (§ data
        pipeline validation) relies on.
        """
        payload = {
            "source": self.source,
            "source_row_ref": self.source_row_ref,
            "fields": dict(self.fields),
        }
        return "raw_" + hash_json_stable(payload)[:32]
