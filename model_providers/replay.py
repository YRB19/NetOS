"""Record / replay wrappers for model-provider responses (Slice 12). NO network code here.

`RecordingProvider` wraps any provider and keeps the raw response text keyed by the request hash.
`ReplayProvider` serves ONLY those recorded responses; an unrecorded request raises
`ProviderUnavailable` (it never calls a provider, never invents a response). Replay reproduces the
RECORDED response of the original provider; it is not a new model call and says nothing about what a
live model would return today. Credentials are never part of a capture.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from intelligence.llm_component.prompt import ProviderRequest
from intelligence.llm_component.provider import ProviderResponse, ProviderUnavailable
from shared.versioning.content_hash import hash_json_stable


def request_key(req: ProviderRequest) -> str:
    return hash_json_stable([req.system, req.user, req.max_output_tokens, req.prompt_hash])


@dataclass(frozen=True)
class Capture:
    request_key: str
    provider_name: str
    requested_model_identifier: str
    resolved_model_identifier: str | None
    response_text: str
    input_tokens: int | None
    output_tokens: int | None
    is_real_provider: bool

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class RecordingProvider:
    def __init__(self, inner) -> None:  # noqa: ANN001
        self.inner = inner
        self.provider_name = inner.provider_name
        self.model_identifier = inner.model_identifier
        self.is_real_provider = bool(getattr(inner, "is_real_provider", False))
        self.captures: dict[str, Capture] = {}

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        resp = self.inner.complete(request)  # provider errors propagate unchanged (and are not captured)
        k = request_key(request)
        self.captures[k] = Capture(k, self.provider_name, self.model_identifier, resp.model_identifier, resp.text,
                                   resp.input_tokens, resp.output_tokens, self.is_real_provider)  # fmt: skip
        return resp

    def dump_jsonl(self) -> str:
        return "\n".join(json.dumps(c.to_dict(), sort_keys=True) for _, c in sorted(self.captures.items()))


class ReplayProvider:
    replayed = True

    def __init__(self, captures: Mapping[str, Capture], *, provider_name: str, model_identifier: str,
                 is_real_provider: bool) -> None:  # fmt: skip
        self._c = dict(captures)
        self.provider_name, self.model_identifier, self.is_real_provider = provider_name, model_identifier, is_real_provider
        self.calls = 0

    @classmethod
    def from_jsonl(cls, text: str) -> ReplayProvider:
        caps = {}
        for line in filter(None, text.splitlines()):
            d = json.loads(line)
            caps[d["request_key"]] = Capture(**d)
        any_c = next(iter(caps.values()), None)
        return cls(caps, provider_name=any_c.provider_name if any_c else "REPLAY",
                   model_identifier=any_c.requested_model_identifier if any_c else "none",
                   is_real_provider=any_c.is_real_provider if any_c else False)  # fmt: skip

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        c = self._c.get(request_key(request))
        if c is None:
            raise ProviderUnavailable("no recorded response for this request (replay never calls a provider)")
        return ProviderResponse(text=c.response_text, model_identifier=c.resolved_model_identifier,
                                input_tokens=c.input_tokens, output_tokens=c.output_tokens)  # fmt: skip
