"""Named, versioned feature sets. Slice 3 spec §5.

The Tier-1 context feature set is deliberately minimal: it exists to
let the Tier-1 baseline know instrument identity, a reference price,
and permitted-universe membership — nothing predictive. Explicitly
excluded from this feature set (per Slice 3 spec §5): RSI, MACD, moving
averages, momentum, sentiment, technical indicators, news features,
fundamental signals, LLM-generated values. Those belong to later slices
(Tier-2 momentum is Slice 6; the LLM component is Slice 13).
"""

from __future__ import annotations

from dataclasses import dataclass, field

TIER1_CONTEXT_FEATURE_SET_ID = "tier1_context_v1"

# The exact field contract this feature set promises to populate on a
# FeatureSnapshot. Used for self-documentation and for a contract test
# asserting the feature set doesn't silently grow predictive fields.
TIER1_CONTEXT_FIELDS: tuple[str, ...] = ("reference_price",)


@dataclass(frozen=True)
class FeatureSetDefinition:
    feature_set_id: str
    fields: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""


TIER1_CONTEXT_FEATURE_SET = FeatureSetDefinition(
    feature_set_id=TIER1_CONTEXT_FEATURE_SET_ID,
    fields=TIER1_CONTEXT_FIELDS,
    description=(
        "Minimal deterministic context: instrument identity, canonical "
        "reference price, and permitted-universe membership. No "
        "predictive/technical/sentiment features."
    ),
)
