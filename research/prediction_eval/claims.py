"""Fact-check separation: factual claims vs forecasts/inferences (Slice 13 §8.3)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ClaimKind(str, Enum):  # noqa: UP042
    FACT = "FACT"
    INFERENCE = "INFERENCE"


class ClaimStatus(str, Enum):  # noqa: UP042
    VERIFIED_AGAINST_SOURCE = "VERIFIED_AGAINST_SOURCE"
    HYPOTHESIS = "HYPOTHESIS"  # inferences are never "verified"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Claim:
    claim_id: str
    kind: ClaimKind
    text: str
    disclosure_id: str | None = None
    asserted_published_at: datetime | None = None


def check_claim(c: Claim, disclosure_index: Mapping[str, datetime]) -> ClaimStatus:
    """disclosure_index maps source disclosure id -> its recorded publication time."""
    if c.kind is ClaimKind.INFERENCE:
        return ClaimStatus.HYPOTHESIS
    if not c.disclosure_id:
        return ClaimStatus.UNSUPPORTED
    pub = disclosure_index.get(c.disclosure_id)
    if pub is None:
        return ClaimStatus.UNSUPPORTED
    if c.asserted_published_at is not None and c.asserted_published_at != pub:
        return ClaimStatus.UNSUPPORTED
    return ClaimStatus.VERIFIED_AGAINST_SOURCE
