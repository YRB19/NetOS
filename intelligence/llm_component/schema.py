"""Strict typed output schema for the disclosure interpretation (Slice 11).

The model may emit ONLY these fields. It can never emit BUY/SELL/HOLD, a quantity, a capital
amount, a risk approval, a broker instruction, a risk threshold or a promotion instruction:
any extra field is a hard rejection, never silently dropped. A parse failure is never turned into
a positive signal.

Semantics (documented once, enforced here):
  status                 SIGNAL | NO_SIGNAL | UNKNOWN
  sentiment              direction of the disclosure's implication for the company's equity
  confidence_adjustment  relative to a LONG (BUY) thesis: INCREASE = the disclosure supports it,
                         DECREASE = it undermines it. The deterministic overlay (not the model)
                         inverts this for SELL candidates. Must be consistent with sentiment.
  confidence             the model's own confidence in THIS classification, [0, 1]. It is NOT a
                         probability that the stock will rise.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum

OUTPUT_SCHEMA_VERSION = "disclosure_interpretation_v1"
MAX_RATIONALE_CHARS = 600


class Status(str, Enum):  # noqa: UP042
    SIGNAL = "SIGNAL"
    NO_SIGNAL = "NO_SIGNAL"
    UNKNOWN = "UNKNOWN"


class Sentiment(str, Enum):  # noqa: UP042
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class Materiality(str, Enum):  # noqa: UP042
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


class Adjustment(str, Enum):  # noqa: UP042
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    NO_CHANGE = "NO_CHANGE"
    NO_SIGNAL = "NO_SIGNAL"


class Uncertainty(str, Enum):  # noqa: UP042
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EventCategory(str, Enum):  # noqa: UP042
    EARNINGS_RESULTS = "EARNINGS_RESULTS"
    MANAGEMENT_CHANGE = "MANAGEMENT_CHANGE"
    MAJOR_CONTRACT_OR_ORDER = "MAJOR_CONTRACT_OR_ORDER"
    FUNDRAISING_OR_CAPITAL_CHANGE = "FUNDRAISING_OR_CAPITAL_CHANGE"
    MERGER_OR_ACQUISITION = "MERGER_OR_ACQUISITION"
    REGULATORY_OR_LEGAL = "REGULATORY_OR_LEGAL"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    OTHER_MATERIAL = "OTHER_MATERIAL"
    UNKNOWN = "UNKNOWN"


REQUIRED_KEYS = frozenset({
    "status", "sentiment", "materiality", "confidence", "confidence_adjustment", "uncertainty",
    "event_category", "source_document_refs", "rationale", "output_schema_version",
})  # fmt: skip

_ADJ_FOR_SENTIMENT = {
    Sentiment.POSITIVE: Adjustment.INCREASE,
    Sentiment.NEGATIVE: Adjustment.DECREASE,
    Sentiment.NEUTRAL: Adjustment.NO_CHANGE,
}


@dataclass(frozen=True)
class DisclosureInterpretation:
    status: Status
    sentiment: Sentiment
    materiality: Materiality
    confidence: float
    confidence_adjustment: Adjustment
    uncertainty: Uncertainty
    event_category: EventCategory
    source_document_refs: tuple[str, ...]
    rationale: str
    output_schema_version: str = OUTPUT_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "status": self.status.value, "sentiment": self.sentiment.value,
            "materiality": self.materiality.value, "confidence": self.confidence,
            "confidence_adjustment": self.confidence_adjustment.value,
            "uncertainty": self.uncertainty.value, "event_category": self.event_category.value,
            "source_document_refs": list(self.source_document_refs), "rationale": self.rationale,
            "output_schema_version": self.output_schema_version,
        }  # fmt: skip


class SchemaError(ValueError):
    """The model output failed strict validation. Carries a short, non-sensitive reason."""


def _enum(cls, v, name):  # noqa: ANN001
    try:
        return cls(v)
    except (ValueError, TypeError):
        raise SchemaError(f"{name}: unknown value {str(v)[:40]!r}") from None


def parse_interpretation(
    raw: str | dict, valid_document_ids: tuple[str, ...]
) -> DisclosureInterpretation:
    """Strictly validate raw model output against the schema and the exact input documents."""
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith(
            "```"
        ):  # tolerate a fenced block ONLY; content is still strictly validated
            text = text.strip("`")
            text = text[4:] if text[:4].lower() == "json" else text
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            raise SchemaError("output is not valid JSON") from None
    else:
        obj = raw
    if not isinstance(obj, dict):
        raise SchemaError("output must be a JSON object")
    keys = set(obj)
    if keys - REQUIRED_KEYS:
        raise SchemaError(f"unsupported fields present: {sorted(keys - REQUIRED_KEYS)}")
    if REQUIRED_KEYS - keys:
        raise SchemaError(f"missing required fields: {sorted(REQUIRED_KEYS - keys)}")
    if obj["output_schema_version"] != OUTPUT_SCHEMA_VERSION:
        raise SchemaError("output_schema_version mismatch")

    status = _enum(Status, obj["status"], "status")
    sentiment = _enum(Sentiment, obj["sentiment"], "sentiment")
    materiality = _enum(Materiality, obj["materiality"], "materiality")
    adj = _enum(Adjustment, obj["confidence_adjustment"], "confidence_adjustment")
    unc = _enum(Uncertainty, obj["uncertainty"], "uncertainty")
    cat = _enum(EventCategory, obj["event_category"], "event_category")

    conf = obj["confidence"]
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not math.isfinite(conf):
        raise SchemaError("confidence must be a finite number")
    if not 0.0 <= float(conf) <= 1.0:
        raise SchemaError("confidence must be within [0, 1]")

    refs = obj["source_document_refs"]
    if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
        raise SchemaError("source_document_refs must be a list of strings")
    unknown_refs = [r for r in refs if r not in valid_document_ids]
    if unknown_refs:
        raise SchemaError("source_document_refs cites documents that were not in the input")
    rationale = obj["rationale"]
    if not isinstance(rationale, str):
        raise SchemaError("rationale must be a string")
    if len(rationale) > MAX_RATIONALE_CHARS:
        raise SchemaError("rationale too long")

    if status is Status.SIGNAL:
        if sentiment not in _ADJ_FOR_SENTIMENT:
            raise SchemaError("SIGNAL requires a POSITIVE/NEGATIVE/NEUTRAL sentiment")
        if adj is not _ADJ_FOR_SENTIMENT[sentiment]:
            raise SchemaError("confidence_adjustment is inconsistent with sentiment")
        if not refs:
            raise SchemaError("SIGNAL requires at least one source_document_refs entry")
        if not rationale.strip():
            raise SchemaError("SIGNAL requires a non-empty rationale")
        if materiality in (Materiality.UNKNOWN,):
            raise SchemaError("SIGNAL requires a known materiality")
    else:
        if adj is not Adjustment.NO_SIGNAL:
            raise SchemaError("NO_SIGNAL/UNKNOWN require confidence_adjustment NO_SIGNAL")
        if status is Status.UNKNOWN and sentiment is not Sentiment.UNKNOWN:
            raise SchemaError("UNKNOWN requires sentiment UNKNOWN")
    return DisclosureInterpretation(
        status=status, sentiment=sentiment, materiality=materiality, confidence=float(conf),
        confidence_adjustment=adj, uncertainty=unc, event_category=cat,
        source_document_refs=tuple(refs), rationale=rationale.strip(),
    )  # fmt: skip
