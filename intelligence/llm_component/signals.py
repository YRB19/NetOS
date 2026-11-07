"""Signal service: context -> validated interpretation record (Slice 11).

This is the composition step that talks to a provider. It is deliberately OUTSIDE
`Strategy.generate_candidate_trades`: results are computed ahead of time into a `SignalStore`, and
the strategy overlay only does pure lookups. A failure of any kind degrades to an explicit
NO_SIGNAL/UNKNOWN record and never blocks the baseline.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from domain.models.disclosure import DisclosureContext
from intelligence.llm_component.prompt import prompt_hash, render_request
from intelligence.llm_component.provider import (
    ModelProvider,
    ProviderError,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from intelligence.llm_component.schema import (
    OUTPUT_SCHEMA_VERSION,
    DisclosureInterpretation,
    SchemaError,
    Status,
    parse_interpretation,
)
from shared.versioning.content_hash import hash_json_stable


class ProviderStatus(str, Enum):  # noqa: UP042
    OK = "OK"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    EMPTY_CONTEXT = "EMPTY_CONTEXT"


@dataclass(frozen=True)
class Pricing:
    """Only supplied by the operator from a VERIFIED price list; otherwise cost stays None."""

    usd_per_million_input_tokens: float
    usd_per_million_output_tokens: float
    verified_note: str


@dataclass(frozen=True)
class SignalConfig:
    enabled: bool = False
    max_requests: int = 50  # per service instance / evaluation run
    max_retries: int = 2  # bounded retry on rate limit only
    max_output_tokens: int = 400
    max_total_tokens: int | None = None
    pricing: Pricing | None = None
    retry_backoff_s: float = 1.0


@dataclass(frozen=True)
class SignalRecord:
    instrument_id: str
    decision_timestamp: datetime
    context_hash: str
    input_snapshot_id: str | None
    provider_status: ProviderStatus
    interpretation: DisclosureInterpretation | None
    detail: str  # sanitized, non-secret reason
    provider_name: str
    model_identifier: str
    prompt_hash: str
    output_schema_version: str = OUTPUT_SCHEMA_VERSION
    document_ids: tuple[str, ...] = ()
    requested_at: datetime | None = None
    completed_at: datetime | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost_usd: float | None = None
    response_hash: str | None = None
    attempts: int = 0
    # `model_identifier` is the CONFIGURED/requested id (may be an alias). The id the provider actually
    # returned is kept separately; if the provider returned none it is None and status UNAVAILABLE.
    resolved_model_identifier: str | None = None
    resolved_identifier_status: str = "NOT_CALLED"  # NOT_CALLED | RETURNED | UNAVAILABLE

    @property
    def requested_model_identifier(self) -> str:
        return self.model_identifier

    @property
    def has_signal(self) -> bool:
        return (
            self.provider_status is ProviderStatus.OK
            and self.interpretation is not None
            and self.interpretation.status is Status.SIGNAL
        )

    def to_payload(self) -> dict:
        return {
            "instrument_id": self.instrument_id, "decision_timestamp": self.decision_timestamp,
            "context_hash": self.context_hash, "input_snapshot_id": self.input_snapshot_id,
            "provider_status": self.provider_status.value, "detail": self.detail,
            "provider_name": self.provider_name, "model_identifier": self.model_identifier,
            "requested_model_identifier": self.model_identifier,
            "resolved_model_identifier": self.resolved_model_identifier,
            "resolved_model_identifier_status": self.resolved_identifier_status,
            "prompt_hash": self.prompt_hash, "output_schema_version": self.output_schema_version,
            "document_ids": list(self.document_ids), "requested_at": self.requested_at,
            "completed_at": self.completed_at,
            # NOTE: not named "*_tokens": the journal redactor masks any key containing "token".
            "usage_input_units": self.input_tokens, "usage_output_units": self.output_tokens, "estimated_cost_usd": self.estimated_cost_usd,
            "response_hash": self.response_hash, "attempts": self.attempts,
            "interpretation": self.interpretation.to_dict() if self.interpretation else None,
        }  # fmt: skip


class SignalStore:
    """Precomputed (instrument, decision_timestamp) -> SignalRecord. Pure lookup for the overlay."""

    def __init__(self) -> None:
        self._m: dict[tuple[str, datetime], SignalRecord] = {}

    def put(self, rec: SignalRecord) -> None:
        self._m[(rec.instrument_id, rec.decision_timestamp)] = rec

    def get(self, instrument_id: str, ts: datetime) -> SignalRecord | None:
        return self._m.get((instrument_id, ts))

    def records(self) -> tuple[SignalRecord, ...]:
        return tuple(self._m.values())


class SignalService:
    def __init__(self, provider: ModelProvider | None, config: SignalConfig,
                 clock: Callable[[], datetime] | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:  # fmt: skip
        self.provider = provider
        self.config = config
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleep
        self.requests_made = 0
        self.tokens_used = 0
        self.total_cost_usd = 0.0
        self.status_counts: dict[str, int] = {}

    @property
    def model_identifier(self) -> str:
        return getattr(self.provider, "model_identifier", "NONE")

    def _rec(self, ctx: DisclosureContext, status: ProviderStatus, detail: str, **kw) -> SignalRecord:  # noqa: ANN003
        self.status_counts[status.value] = self.status_counts.get(status.value, 0) + 1
        return SignalRecord(
            instrument_id=ctx.instrument_id, decision_timestamp=ctx.decision_timestamp,
            context_hash=ctx.context_hash, input_snapshot_id=ctx.input_snapshot_id,
            provider_status=status, detail=detail, interpretation=kw.pop("interpretation", None),
            provider_name=getattr(self.provider, "provider_name", "NONE"),
            model_identifier=self.model_identifier, prompt_hash=prompt_hash(),
            document_ids=ctx.document_ids, **kw,
        )  # fmt: skip

    def evaluate(self, ctx: DisclosureContext) -> SignalRecord:
        cfg = self.config
        if not cfg.enabled or self.provider is None:
            return self._rec(ctx, ProviderStatus.DISABLED, "AI overlay disabled; no provider call")
        if ctx.is_empty:
            return self._rec(ctx, ProviderStatus.EMPTY_CONTEXT, "no available disclosures; no provider call")
        request = render_request(ctx, cfg.max_output_tokens)
        started = self._clock()
        attempts = 0
        while True:
            if self.requests_made >= cfg.max_requests or (
                cfg.max_total_tokens is not None and self.tokens_used >= cfg.max_total_tokens
            ):
                return self._rec(ctx, ProviderStatus.BUDGET_EXHAUSTED, "request/token budget reached; no provider call",
                                 requested_at=started, attempts=attempts)  # fmt: skip
            self.requests_made += 1
            attempts += 1
            try:
                resp = self.provider.complete(request)
                break
            except ProviderRateLimited:
                if attempts > cfg.max_retries:
                    return self._rec(ctx, ProviderStatus.RATE_LIMITED, "rate limited; retries exhausted",
                                     requested_at=started, completed_at=self._clock(), attempts=attempts)  # fmt: skip
                self._sleep(cfg.retry_backoff_s * attempts)
            except ProviderTimeout:
                return self._rec(ctx, ProviderStatus.TIMEOUT, "provider timeout", requested_at=started,
                                 completed_at=self._clock(), attempts=attempts)  # fmt: skip
            except ProviderUnavailable as e:
                return self._rec(ctx, ProviderStatus.UNAVAILABLE, str(e)[:120], requested_at=started,
                                 completed_at=self._clock(), attempts=attempts)  # fmt: skip
            except ProviderError as e:
                return self._rec(ctx, ProviderStatus.PROVIDER_ERROR, str(e)[:120], requested_at=started,
                                 completed_at=self._clock(), attempts=attempts)  # fmt: skip
        done = self._clock()
        tin, tout = resp.input_tokens, resp.output_tokens
        self.tokens_used += (tin or 0) + (tout or 0)
        cost = None
        if cfg.pricing and tin is not None and tout is not None:
            cost = (tin * cfg.pricing.usd_per_million_input_tokens
                    + tout * cfg.pricing.usd_per_million_output_tokens) / 1_000_000  # fmt: skip
            self.total_cost_usd += cost
        common = dict(requested_at=started, completed_at=done, input_tokens=tin, output_tokens=tout,
                      estimated_cost_usd=cost, response_hash=hash_json_stable(resp.text), attempts=attempts,
                      resolved_model_identifier=resp.model_identifier or None,
                      resolved_identifier_status="RETURNED" if resp.model_identifier else "UNAVAILABLE")  # fmt: skip
        try:
            interp = parse_interpretation(resp.text, ctx.document_ids)
        except SchemaError as e:
            # Never a positive signal: the baseline is preserved.
            return self._rec(ctx, ProviderStatus.MALFORMED_OUTPUT, f"rejected: {e}"[:160], **common)
        return self._rec(ctx, ProviderStatus.OK, "validated", interpretation=interp, **common)
