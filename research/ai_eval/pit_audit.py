"""Signal-level point-in-time and provenance audit (Slice 12).

Runs on `SignalRecord.to_payload()` dicts and `DisclosureRecord`s. It NEVER repairs data: a signal
that fails a blocking check is excluded with a coded reason, and the exclusion is logged. The
audit is the gate in front of the signal store used by confirmatory arms, and also the
after-the-fact detector for any applied signal that should not have been eligible.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from domain.models.disclosure import USABLE_STATUSES, DisclosureRecord
from shared.time.clock import ensure_utc


class Provenance(str, Enum):  # noqa: UP042
    OFFLINE_FIXTURE = "OFFLINE_FIXTURE"  # deterministic stub / recorded test fixture; not a model response
    LIVE_CAPTURED = "LIVE_CAPTURED"  # real provider response recorded at/before the decision time
    RETROSPECTIVE_REPLAY = "RETROSPECTIVE_REPLAY"  # real provider run AFTER the decision time on old documents
    NO_PROVIDER_OUTPUT = "NO_PROVIDER_OUTPUT"  # disabled / failed / empty: nothing to classify


BLOCKING = (
    "SNAPSHOT_ID_MISSING", "SNAPSHOT_ID_MISMATCH", "DOC_UNKNOWN", "DOC_AVAILABILITY_MISSING",
    "DOC_NOT_AVAILABLE_AT_DECISION", "DOC_PUBLISHED_AFTER_DECISION", "DOC_TIMESTAMPS_INCONSISTENT",
    "DOC_STATUS_UNUSABLE", "MODEL_CUTOFF_UNDECLARED", "MODEL_CUTOFF_OVERLAP", "MODEL_ID_UNRESOLVED",
    "OUTSIDE_EVALUATION_WINDOW", "SCHEMA_VERSION_MISMATCH", "PROMPT_HASH_MISMATCH",
    "CONTRADICTORY_DUPLICATE", "DUPLICATE_SIGNAL",
)  # fmt: skip


def _ts(v: object) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return ensure_utc(v)
    return ensure_utc(datetime.fromisoformat(str(v)))


@dataclass(frozen=True)
class SignalAuditEntry:
    key: tuple[str, str]  # (instrument_id, decision_timestamp iso)
    provenance: Provenance
    provider_status: str
    eligible: bool
    reasons: tuple[str, ...]
    document_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"instrument_id": self.key[0], "decision_timestamp": self.key[1],
                "provenance": self.provenance.value, "provider_status": self.provider_status,
                "eligible": self.eligible, "reasons": list(self.reasons),
                "document_ids": list(self.document_ids)}  # fmt: skip


@dataclass(frozen=True)
class PitAuditReport:
    entries: tuple[SignalAuditEntry, ...]
    run_level_findings: tuple[str, ...]
    resolved_model_identifiers: tuple[str, ...]

    @property
    def eligible_keys(self) -> frozenset[tuple[str, str]]:
        return frozenset(e.key for e in self.entries if e.eligible)

    @property
    def exclusion_log(self) -> list[dict]:
        return [e.to_dict() for e in self.entries if not e.eligible]

    def counts(self) -> dict:
        by_reason: dict[str, int] = {}
        by_prov: dict[str, int] = {}
        for e in self.entries:
            by_prov[e.provenance.value] = by_prov.get(e.provenance.value, 0) + 1
            for r in e.reasons:
                by_reason[r] = by_reason.get(r, 0) + 1
        return {"signals_audited": len(self.entries), "eligible": len(self.eligible_keys),
                "excluded": sum(1 for e in self.entries if not e.eligible),
                "exclusions_by_reason": dict(sorted(by_reason.items())),
                "by_provenance": dict(sorted(by_prov.items()))}  # fmt: skip

    def to_dict(self) -> dict:
        return {"counts": self.counts(), "run_level_findings": list(self.run_level_findings),
                "resolved_model_identifiers": list(self.resolved_model_identifiers),
                "entries": [e.to_dict() for e in self.entries]}  # fmt: skip


def classify_provenance(sig: Mapping, decision_ts: datetime) -> Provenance:
    if sig.get("provider_name") == "STUB":
        return Provenance.OFFLINE_FIXTURE
    if sig.get("provider_status") != "OK":
        return Provenance.NO_PROVIDER_OUTPUT
    done = _ts(sig.get("completed_at"))
    if done is not None and done <= decision_ts:
        return Provenance.LIVE_CAPTURED
    return Provenance.RETROSPECTIVE_REPLAY


def audit_signals(
    signals: Iterable[Mapping], *, documents: Mapping[str, DisclosureRecord],
    expected_snapshot_ids: Mapping[tuple[str, str], str], model_cutoff: datetime | None,
    window: tuple[datetime, datetime], expected_schema_version: str, expected_prompt_hash: str,
) -> PitAuditReport:  # fmt: skip
    """Audit every signal. `expected_snapshot_ids[(instrument, decision_ts_iso)]` is the id of the
    FeatureSnapshot of the candidate the signal would adjust (taken from the baseline run, never
    inferred from the signal itself)."""
    w0, w1 = ensure_utc(window[0]), ensure_utc(window[1])
    cutoff = ensure_utc(model_cutoff) if model_cutoff is not None else None
    sigs = list(signals)
    seen: dict[tuple[str, str], str] = {}
    entries: list[SignalAuditEntry] = []
    resolved_ok: set[str] = set()
    for s in sigs:
        dts = _ts(s["decision_timestamp"])
        assert dts is not None
        key = (str(s["instrument_id"]), dts.isoformat())
        reasons: list[str] = []
        prov = classify_provenance(s, dts)
        # duplicates
        fingerprint = str(s.get("response_hash") or s.get("context_hash"))
        if key in seen:
            reasons.append("DUPLICATE_SIGNAL" if seen[key] == fingerprint else "CONTRADICTORY_DUPLICATE")
        else:
            seen[key] = fingerprint
        # snapshot provenance (exact; never inferred)
        sid = s.get("input_snapshot_id")
        if not sid:
            reasons.append("SNAPSHOT_ID_MISSING")
        elif key in expected_snapshot_ids and expected_snapshot_ids[key] != sid:
            reasons.append("SNAPSHOT_ID_MISMATCH")
        elif key not in expected_snapshot_ids:
            reasons.append("SNAPSHOT_ID_MISMATCH")  # no candidate/snapshot exists for this key
        # documents
        for did in s.get("document_ids") or ():
            d = documents.get(did)
            if d is None:
                reasons.append("DOC_UNKNOWN")
                continue
            if d.status not in USABLE_STATUSES:
                reasons.append("DOC_STATUS_UNUSABLE")
            if d.available_at is None:
                reasons.append("DOC_AVAILABILITY_MISSING")
                continue
            av = ensure_utc(d.available_at)
            if av > dts:
                reasons.append("DOC_NOT_AVAILABLE_AT_DECISION")
            if d.published_at is not None:
                pub = ensure_utc(d.published_at)
                if pub > dts:
                    reasons.append("DOC_PUBLISHED_AFTER_DECISION")
                if av < pub or av < ensure_utc(d.ingested_at):
                    reasons.append("DOC_TIMESTAMPS_INCONSISTENT")
        # model knowledge cutoff (enforced per signal, in evaluation, not only at ingestion)
        if cutoff is None:
            reasons.append("MODEL_CUTOFF_UNDECLARED")
        elif dts <= cutoff:
            reasons.append("MODEL_CUTOFF_OVERLAP")
        # requested vs returned model identifier (a real provider must return one)
        if prov is not Provenance.OFFLINE_FIXTURE and s.get("provider_status") == "OK":
            if s.get("resolved_model_identifier_status") != "RETURNED" or not s.get("resolved_model_identifier"):
                reasons.append("MODEL_ID_UNRESOLVED")
        if s.get("provider_status") == "OK" and s.get("resolved_model_identifier"):
            resolved_ok.add(str(s["resolved_model_identifier"]))
        if not (w0 <= dts <= w1):
            reasons.append("OUTSIDE_EVALUATION_WINDOW")
        if s.get("output_schema_version") != expected_schema_version:
            reasons.append("SCHEMA_VERSION_MISMATCH")
        if s.get("prompt_hash") != expected_prompt_hash:
            reasons.append("PROMPT_HASH_MISMATCH")
        uniq = tuple(dict.fromkeys(reasons))
        entries.append(SignalAuditEntry(key, prov, str(s.get("provider_status")), not uniq, uniq,
                                        tuple(s.get("document_ids") or ())))  # fmt: skip
    findings: list[str] = []
    if len(resolved_ok) > 1:
        findings.append(f"MODEL_ID_DRIFT: {len(resolved_ok)} distinct provider-returned identifiers across the run")
    return PitAuditReport(tuple(entries), tuple(findings), tuple(sorted(resolved_ok)))


def applied_but_ineligible(ai_events: Iterable[Mapping], eligible_keys: frozenset[tuple[str, str]]) -> list[dict]:
    """Journal-side detector: AI_SIGNAL_EVALUATED payloads with applied=True whose signal key is not
    in the eligible set. Any entry is an integrity breach (an ineligible signal influenced a decision)."""
    bad = []
    for p in ai_events:
        if str(p.get("applied")).lower() != "true":
            continue
        sig = p.get("signal") or {}
        if not sig:
            bad.append({"reason": "APPLIED_WITHOUT_SIGNAL", "payload_keys": sorted(p)})
            continue
        key = (str(sig["instrument_id"]), _ts(sig["decision_timestamp"]).isoformat())  # type: ignore[union-attr]
        if key not in eligible_keys:
            bad.append({"reason": "APPLIED_INELIGIBLE_SIGNAL", "instrument_id": key[0], "decision_timestamp": key[1]})
    return bad
