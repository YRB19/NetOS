"""Version-identifier machinery shared across planes (Stage 3 §15/§19).

Stage 3 is explicit that this milestone should establish "the correct typed
fields and deterministic representation" for versioning, not a full
version-management service. This module provides exactly that: a content
hash helper for content-addressed artifacts (StrategyVersion, ModelVersion,
etc.) and a UUID helper for identity-addressed records (DecisionRecord,
Experiment, etc.) — both deterministic in the sense that the same logical
identity always produces the same representation, which is what §19's
reconstruction guarantee ultimately depends on.
"""

from __future__ import annotations

import hashlib
import uuid


def new_id() -> str:
    """A fresh, globally-unique identifier for identity-addressed records."""
    return str(uuid.uuid4())


def content_hash(*parts: str) -> str:
    """A deterministic content-address for versioned artifacts.

    Given the same ordered parts (e.g. serialized code/config), always
    produces the same hash — this is what makes a StrategyVersion or
    ModelVersion's identity a fact about its content, not an arbitrary
    counter, per Stage 3 §19's "content-addressed hash" scheme.
    """
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")  # separator, avoids ("ab","c") == ("a","bc") collisions
    return digest.hexdigest()
