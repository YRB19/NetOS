"""Dataset quality, survivorship and provenance warnings (Slice 9, ADR-18)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from data.features.universe import PermittedUniverse
from domain.models.market_data import MarketData


@dataclass(frozen=True)
class DatasetProvenance:
    dataset_id: str
    version: str
    source_description: str
    is_synthetic: bool
    source_verified: bool = False
    point_in_time_verified: bool = False
    survivorship_free_claimed: bool = False
    corporate_actions_source: str | None = None
    delisted_instruments: frozenset[str] = frozenset()  # explicitly recorded delistings


def assess_quality(market_data: list[MarketData], universes: list[PermittedUniverse],
                   provenance: DatasetProvenance, *, stale_run_length: int = 3) -> dict:  # fmt: skip
    warnings: list[dict] = []

    def warn(code: str, severity: str, detail: str, instruments: list[str] | None = None):
        warnings.append({"code": code, "severity": severity, "detail": detail, "instruments": sorted(instruments or [])})  # fmt: skip

    by_inst: dict[str, list[MarketData]] = defaultdict(list)
    for m in market_data:
        by_inst[m.instrument_id].append(m)
    all_ts = sorted({m.timestamp for m in market_data})
    for inst, rows in sorted(by_inst.items()):
        have = {r.timestamp for r in rows}
        first, last = min(have), max(have)
        missing = [t for t in all_ts if first <= t <= last and t not in have]
        if missing:
            warn("MISSING_BARS", "WARNING", f"{inst} lacks {len(missing)} bar(s) other instruments have", [inst])
        rows.sort(key=lambda r: r.timestamp)
        run = 1
        for a, b in zip(rows, rows[1:], strict=False):
            same = (a.open, a.high, a.low, a.close, a.volume) == (b.open, b.high, b.low, b.close, b.volume)
            run = run + 1 if same else 1
            if run == stale_run_length:
                warn("STALE_OBSERVATIONS", "WARNING", f"{inst} has {stale_run_length}+ identical consecutive bars", [inst])
                break
        flags = {r.adjusted for r in rows}
        if len(flags) > 1:
            warn("CORPORATE_ACTION_ADJUSTMENT_MISMATCH", "ERROR", f"{inst} mixes adjusted and as-traded bars", [inst])
    universe_ids = {i for u in universes for i in u.instrument_ids}
    unknown = set(by_inst) - universe_ids
    if unknown:
        warn("IDENTITY_MAPPING_GAP", "WARNING", "instruments in data but in no universe version (symbol change / mapping gap?)", list(unknown))  # fmt: skip
    ordered = sorted(universes, key=lambda u: u.effective_from)
    for a, b in zip(ordered, ordered[1:], strict=False):
        dropped = set(a.instrument_ids) - set(b.instrument_ids)
        if dropped:
            undocumented = dropped - provenance.delisted_instruments
            if undocumented:
                warn("POSSIBLE_SURVIVORSHIP_BIAS", "WARNING",
                     f"instruments removed between {a.version} and {b.version} with no recorded delisting", list(undocumented))  # fmt: skip
    if not provenance.survivorship_free_claimed:
        warn("SURVIVORSHIP_NOT_ESTABLISHED", "WARNING", "dataset not established as survivorship-free")
    if provenance.is_synthetic:
        warn("SYNTHETIC_DATA", "INFO", "synthetic fixture: infrastructure check only, not market evidence")
    if not provenance.is_synthetic and not provenance.source_verified:
        warn("UNVERIFIED_HISTORY_SOURCE", "ERROR", "historical source is not verified")
    if not provenance.is_synthetic and not provenance.point_in_time_verified:
        warn("POINT_IN_TIME_NOT_VERIFIED", "ERROR", "point-in-time provenance inadequate for a clean historical claim")
    if provenance.corporate_actions_source is None and not provenance.is_synthetic:
        warn("CORPORATE_ACTION_SOURCE_MISSING", "WARNING", "no corporate-action source recorded")
    if provenance.is_synthetic:
        evidence = "SYNTHETIC_INFRASTRUCTURE"
    elif not any(w["severity"] == "ERROR" for w in warnings):
        evidence = "HISTORICAL_VERIFIED_FOR_STATED_CHECKS"
    else:
        evidence = "HISTORICAL_UNVERIFIED"
    return {"dataset_id": provenance.dataset_id, "version": provenance.version, "evidence_class": evidence,
            "warnings": warnings, "blocking_errors": sum(1 for w in warnings if w["severity"] == "ERROR")}  # fmt: skip
