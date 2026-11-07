"""Optional NVIDIA hosted (NIM / build.nvidia.com) chat-completions provider (Slice 11 provider addition).

OpenAI-compatible Chat Completions over HTTPS using the standard library: no SDK, no framework, no tool
use, no streaming. Server-side only; the key never reaches the frontend, logs, journal or errors.

Environment:
  NVIDIA_API_KEY    secret (required)
  NVIDIA_MODEL      exact model id (default candidate: moonshotai/kimi-k2-instruct;
                    moonshotai/kimi-k2-thinking is supported by configuration)
  NVIDIA_BASE_URL   default https://integrate.api.nvidia.com/v1 ; the request goes to
                    <base>/chat/completions . Must be https.

The default endpoint and model ids are as supplied by the operator; this code was NOT able to verify them
against NVIDIA (no network, no credentials in the build environment). Availability, pricing, rate limits and
terms are the operator's to confirm. NEVER called by the automated test suites (they inject a transport).
"""

from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
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

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "moonshotai/kimi-k2-instruct"
SUPPORTED_THINKING_MODEL = "moonshotai/kimi-k2-thinking"
DEFAULT_TIMEOUT_S = 60.0

Transport = Callable[[str, dict, bytes, float], tuple[int, bytes]]
_THINK_BLOCK = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def _urllib_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310 - https enforced
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


def chat_completions_url(base_url: str) -> str:
    u = urllib.parse.urlparse(base_url.strip())
    if u.scheme != "https" or not u.netloc or u.username or u.password or u.query or u.fragment:
        raise ProviderUnavailable("NVIDIA_BASE_URL must be a plain https URL without credentials or query")
    return base_url.strip().rstrip("/") + "/chat/completions"


class NvidiaProvider:
    provider_name = "NVIDIA"
    is_real_provider = True

    def __init__(self, api_key: str, model_identifier: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL,
                 timeout_s: float = DEFAULT_TIMEOUT_S, transport: Transport | None = None) -> None:  # fmt: skip
        if not api_key or not model_identifier:
            raise ProviderUnavailable("NVIDIA_API_KEY and a model are both required")
        self._api_key = api_key
        self.model_identifier = model_identifier
        self.url = chat_completions_url(base_url)
        self.timeout_s = timeout_s
        self._transport = transport or _urllib_transport

    @classmethod
    def from_env(cls, environ: Mapping[str, str], **kw) -> NvidiaProvider:  # noqa: ANN003
        key = environ.get("NVIDIA_API_KEY", "").strip()
        if not key:
            raise ProviderUnavailable("NVIDIA_API_KEY is not set")
        return cls(key, environ.get("NVIDIA_MODEL", "").strip() or DEFAULT_MODEL,
                   environ.get("NVIDIA_BASE_URL", "").strip() or DEFAULT_BASE_URL, **kw)  # fmt: skip

    def __repr__(self) -> str:  # never reveals the key
        return f"NvidiaProvider(model={self.model_identifier!r}, url={self.url!r}, key=<redacted>)"

    def build_request_body(self, request: ProviderRequest) -> dict:
        return {
            "model": self.model_identifier, "max_tokens": request.max_output_tokens, "temperature": 0,
            "stream": False,
            "messages": [{"role": "system", "content": request.system}, {"role": "user", "content": request.user}],
        }  # fmt: skip (no `tools`, no `tool_choice`: the component has no tool capability)

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        headers = {"content-type": "application/json", "accept": "application/json",
                   "authorization": f"Bearer {self._api_key}"}  # fmt: skip
        body = json.dumps(self.build_request_body(request)).encode("utf-8")
        try:
            status, raw = self._transport(self.url, headers, body, self.timeout_s)
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
            msg = obj["choices"][0]["message"]
            text = msg["content"]
            if not isinstance(text, str):
                raise TypeError
            # Thinking models may prefix an inline <think>..</think> block; it is discarded, never stored.
            # (A separate `reasoning_content` field, if any, is never read.)
            text = _THINK_BLOCK.sub("", text, count=1)
            usage = obj.get("usage") or {}
            return ProviderResponse(
                text=text, model_identifier=(str(obj["model"]) if obj.get("model") else None),
                input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
                provider_request_id=obj.get("id"),
            )  # fmt: skip
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("malformed provider response envelope") from None
