"""Optional Anthropic Messages API provider (Slice 11).

Direct HTTPS call via the standard library (no SDK, no framework, no tool use). Requires SEPARATE
Anthropic Console API credentials; a Claude.ai Pro/Max subscription is not API access and Claude
Code CLI is not used as an inference runtime.

Environment:  ANTHROPIC_API_KEY   (secret; never logged, printed, persisted or exposed)
              ANTHROPIC_MODEL     (exact model id; required, no default is assumed)
This provider is NEVER called by the automated test suites (they inject an offline transport).
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping

from intelligence.llm_component.prompt import ProviderRequest
from intelligence.llm_component.provider import (
    ProviderError,
    ProviderRateLimited,
    ProviderResponse,
    ProviderTimeout,
    ProviderUnavailable,
)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_TIMEOUT_S = 30.0

# transport(url, headers, body_bytes, timeout) -> (status_code, response_body_bytes)
Transport = Callable[[str, dict, bytes, float], tuple[int, bytes]]


def _urllib_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310 - fixed https URL
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""
    except (TimeoutError, socket.timeout):
        raise
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise TimeoutError from None
        raise ProviderError("network error") from None


class AnthropicProvider:
    provider_name = "ANTHROPIC"
    is_real_provider = True

    def __init__(self, api_key: str, model_identifier: str, timeout_s: float = DEFAULT_TIMEOUT_S,
                 transport: Transport | None = None) -> None:  # fmt: skip
        if not api_key or not model_identifier:
            raise ProviderUnavailable("ANTHROPIC_API_KEY and ANTHROPIC_MODEL are both required")
        self._api_key = api_key
        self.model_identifier = model_identifier
        self.timeout_s = timeout_s
        self._transport = transport or _urllib_transport

    @classmethod
    def from_env(cls, environ: Mapping[str, str], **kw) -> AnthropicProvider:  # noqa: ANN003
        key = environ.get("ANTHROPIC_API_KEY", "").strip()
        model = environ.get("ANTHROPIC_MODEL", "").strip()
        if not key:
            raise ProviderUnavailable("ANTHROPIC_API_KEY is not set")
        if not model:
            raise ProviderUnavailable("ANTHROPIC_MODEL is not set")
        return cls(key, model, **kw)

    def __repr__(self) -> str:  # never reveals the key
        return f"AnthropicProvider(model={self.model_identifier!r}, key=<redacted>)"

    def build_request_body(self, request: ProviderRequest) -> dict:
        return {
            "model": self.model_identifier,
            "max_tokens": request.max_output_tokens,
            "temperature": 0,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
        }  # fmt: skip (no `tools` key: the component has no tool capability)

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        headers = {"content-type": "application/json", "x-api-key": self._api_key,
                   "anthropic-version": API_VERSION}  # fmt: skip
        body = json.dumps(self.build_request_body(request)).encode("utf-8")
        try:
            status, raw = self._transport(API_URL, headers, body, self.timeout_s)
        except (TimeoutError, socket.timeout):
            raise ProviderTimeout("request timed out") from None
        if status == 429:
            raise ProviderRateLimited("rate limited (HTTP 429)")
        if status in (408, 504):
            raise ProviderTimeout(f"timeout (HTTP {status})")
        if status != 200:
            raise ProviderError(f"provider returned HTTP {status}")  # body deliberately not echoed
        try:
            obj = json.loads(raw)
            text = "".join(b["text"] for b in obj["content"] if b.get("type") == "text")
            usage = obj.get("usage") or {}
            return ProviderResponse(
                text=text, model_identifier=str(obj.get("model") or self.model_identifier),
                input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                provider_request_id=obj.get("id"),
            )  # fmt: skip
        except (ValueError, KeyError, TypeError):
            raise ProviderError("malformed provider response envelope") from None
