"""Explicit provider selection (Slice 11). There is NO default real provider and NO fallback.

`select_provider("stub"|"anthropic"|"nvidia", environ)` returns exactly that provider or raises
`ProviderUnavailable` (missing configuration). It never substitutes another provider, paid or not.
"""

from __future__ import annotations

from collections.abc import Mapping

from intelligence.llm_component.provider import ModelProvider, ProviderUnavailable, StubProvider, neutral_no_signal
from model_providers.anthropic_provider import AnthropicProvider
from model_providers.nvidia_provider import NvidiaProvider

PROVIDERS = ("stub", "anthropic", "nvidia")


def select_provider(name: str, environ: Mapping[str, str]) -> ModelProvider:
    import json

    if name == "stub":
        return StubProvider(json.dumps(neutral_no_signal()))
    if name == "anthropic":
        return AnthropicProvider.from_env(environ)
    if name == "nvidia":
        return NvidiaProvider.from_env(environ)
    raise ProviderUnavailable(f"unknown provider {name!r}; choose one of {PROVIDERS} (no fallback exists)")
