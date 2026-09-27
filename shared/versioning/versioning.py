"""Version-identifier machinery, per Stage 3 §19.

Used by every plane needing an immutable, content-addressed, or
incrementing version identifier (StrategyVersion, ModelVersion,
ConfigurationVersion, RiskRuleVersion, cost_model_version, data
snapshot version, feature-set version, universe version, etc.).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def content_hash(payload: Any) -> str:
    """Deterministic content-addressed hash for a JSON-serializable payload.

    Sorts keys so field order never changes the hash. Used to derive
    reproducible version identifiers (e.g. a feature-set version derived
    from its exact definition) rather than hand-assigned strings that can
    drift out of sync with what they claim to describe.
    """
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def make_version_id(label: str, payload: Any | None = None) -> str:
    """Build a human-readable-plus-content-addressed version id.

    e.g. make_version_id("tier1_context", {"fields": [...]})
      -> "tier1_context@ab12cd34ef56ab12"

    If payload is None, returns the bare label (used for hand-assigned,
    explicitly documented version labels such as strategy version ids,
    where a human-readable, stable string is the point).
    """
    if payload is None:
        return label
    return f"{label}@{content_hash(payload)}"
