"""Minimal, deterministic persistence for a canonical MarketData batch.

Stage 3 §5 (Slice 2 scope note): "Do not prematurely implement the full database architecture.
If persistence is needed for this slice, keep it simple and deterministic. A file-based
representation is acceptable for this milestone if it satisfies reproducibility."

This writes one JSON object per line (JSONL), sorted deterministically by
(instrument_id, timestamp, source) so that writing the same accepted batch twice produces
byte-identical output — a property directly exercised by the determinism test in
tests/integration/test_normalization_pipeline.py.

This is explicitly a Slice 2 stopgap, not the relational store Stage 2 §18 specifies for
later slices; it exists only so Slice 3 has something concrete to read.
"""

from __future__ import annotations

import json
from pathlib import Path

from domain.models.market_data import MarketData

_ISO_FMT = "%Y-%m-%dT%H:%M:%S.%f%z"


def market_data_to_dict(record: MarketData) -> dict:
    return {
        "instrument_id": record.instrument_id,
        "timestamp": record.timestamp.isoformat(),
        "open": record.open,
        "high": record.high,
        "low": record.low,
        "close": record.close,
        "volume": record.volume,
        "source": record.source,
        "ingestion_time": record.ingestion_time.isoformat(),
        "data_snapshot_version": record.data_snapshot_version,
        "adjusted": record.adjusted,
        "raw_ref": record.raw_ref,
    }


def dict_to_market_data(d: dict) -> MarketData:
    from datetime import datetime

    return MarketData(
        instrument_id=d["instrument_id"],
        timestamp=datetime.fromisoformat(d["timestamp"]),
        open=d["open"],
        high=d["high"],
        low=d["low"],
        close=d["close"],
        volume=d["volume"],
        source=d["source"],
        ingestion_time=datetime.fromisoformat(d["ingestion_time"]),
        data_snapshot_version=d["data_snapshot_version"],
        adjusted=d["adjusted"],
        raw_ref=d.get("raw_ref"),
    )


def write_market_data_jsonl(records: tuple[MarketData, ...], path: str | Path) -> str:
    """Write records sorted by identity_key, one JSON object per line. Returns the path written."""
    ordered = sorted(records, key=lambda r: (r.instrument_id, r.timestamp.isoformat(), r.source))
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for record in ordered:
            f.write(json.dumps(market_data_to_dict(record), sort_keys=True))
            f.write("\n")
    return str(p)


def read_market_data_jsonl(path: str | Path) -> tuple[MarketData, ...]:
    p = Path(path)
    records = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(dict_to_market_data(json.loads(line)))
    return tuple(records)
