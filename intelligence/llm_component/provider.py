"""Model-provider interface, errors and the deterministic offline stub (Slice 11).

A provider turns a `ProviderRequest` into raw text. It holds no broker credential, no order method
and no risk access. Errors are categorised and carry NO secrets.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from domain.models.disclosure import DisclosureContext
from intelligence.llm_component.prompt import ProviderRequest


class ProviderError(Exception):
    category = "PROVIDER_ERROR"


class ProviderUnavailable(ProviderError):  # no credentials / not configured
    category = "UNAVAILABLE"


class ProviderTimeout(ProviderError):
    category = "TIMEOUT"


class ProviderRateLimited(ProviderError):
    category = "RATE_LIMITED"


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    model_identifier: str | None  # the identifier the PROVIDER returned; None if it did not return one
    input_tokens: int | None = None
    output_tokens: int | None = None
    provider_request_id: str | None = None


class ModelProvider(Protocol):
    provider_name: str
    model_identifier: str
    is_real_provider: bool

    def complete(self, request: ProviderRequest) -> ProviderResponse: ...


class StubProvider:
    """Deterministic OFFLINE provider for tests/demos. Never a real model; labelled as such."""

    provider_name = "STUB"
    is_real_provider = False

    def __init__(self, responder: Callable[[ProviderRequest], str] | dict | str | None = None,
                 model_identifier: str = "stub-model-v1") -> None:  # fmt: skip
        self.model_identifier = model_identifier
        self._responder = responder
        self.calls = 0

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        r = self._responder
        if r is None:
            text = json.dumps(neutral_no_signal())
        elif callable(r):
            text = r(request)
        elif isinstance(r, dict):
            text = json.dumps(r)
        else:
            text = r
        return ProviderResponse(text=text, model_identifier=self.model_identifier,
                                input_tokens=len(request.user) // 4, output_tokens=len(text) // 4)  # fmt: skip


def neutral_no_signal() -> dict:
    return {"status": "NO_SIGNAL", "sentiment": "UNKNOWN", "materiality": "NONE", "confidence": 0.5,
            "confidence_adjustment": "NO_SIGNAL", "uncertainty": "HIGH", "event_category": "UNKNOWN",
            "source_document_refs": [], "rationale": "", "output_schema_version": "disclosure_interpretation_v1"}  # fmt: skip


def stub_signal(context: DisclosureContext, sentiment: str, materiality: str = "HIGH",
                confidence: float = 0.9, category: str = "EARNINGS_RESULTS") -> dict:  # fmt: skip
    """Build a schema-valid SIGNAL payload citing every document in `context` (test helper)."""
    adj = {"POSITIVE": "INCREASE", "NEGATIVE": "DECREASE", "NEUTRAL": "NO_CHANGE"}[sentiment]
    return {"status": "SIGNAL", "sentiment": sentiment, "materiality": materiality, "confidence": confidence,
            "confidence_adjustment": adj, "uncertainty": "LOW", "event_category": category,
            "source_document_refs": list(context.document_ids), "rationale": f"Stub classification: {sentiment}.",
            "output_schema_version": "disclosure_interpretation_v1"}  # fmt: skip
