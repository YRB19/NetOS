# ruff: noqa: UP042
# Keep existing Enum string/serialization semantics across slices.
"""StrategyVersion / ModelVersion / ConfigurationVersion / RiskRuleVersion
(Stage 3 §2, §15, §19).

All four are immutable once created — "a v0.2, v0.3, etc. convention should
be used rather than silent in-place edits" (Stage 1 DOC-6) applies to code
here as much as to the project's own documents. RiskRuleVersion is
deliberately its own type, tracked separately from general Plane 3
versioning, per RR-9: it must be independently verifiable that risk-rule
*semantics* are untouched by anything, even while Plane 3's code evolves
for unrelated engineering reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from types import MappingProxyType

from domain.models._validators import require_aware_utc, require_non_empty_str, require_uuid_like
from shared.time.clock import utc_now
from shared.versioning.identifiers import content_hash, new_id


class PromotionStatus(str, Enum):
    DRAFT = "DRAFT"  # produced by an experiment, not yet reviewed
    PAPER_APPROVED = "PAPER_APPROVED"
    LIVE_APPROVED = "LIVE_APPROVED"
    REJECTED = "REJECTED"


class Plane2Type(str, Enum):
    BASELINE = "BASELINE"  # deterministic (Stage 2 ADR-1)
    LLM = "LLM"


@dataclass(frozen=True, slots=True)
class StrategyVersion:
    plane2_type: Plane2Type
    code_or_config_hash: str
    version_id: str = ""  # content-addressed; derived if not supplied
    parent_version: str | None = None  # lineage, for ER-4's correction (Stage 3 §11)
    promotion_status: PromotionStatus = PromotionStatus.DRAFT
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.plane2_type, Plane2Type):
            raise ValueError(f"plane2_type must be a Plane2Type, got: {self.plane2_type!r}")
        require_non_empty_str(self.code_or_config_hash, "code_or_config_hash")
        if not self.version_id:
            object.__setattr__(
                self,
                "version_id",
                content_hash(self.plane2_type.value, self.code_or_config_hash),
            )
        require_uuid_like(self.version_id, "version_id")
        if not isinstance(self.promotion_status, PromotionStatus):
            raise ValueError(
                f"promotion_status must be a PromotionStatus, got: {self.promotion_status!r}"
            )
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))

    def promoted_to(self, status: PromotionStatus) -> StrategyVersion:
        """Return a NEW StrategyVersion reflecting a promotion-status change.

        Never mutates in place — a promotion-status change is itself a
        versioned fact (Stage 3 §14: the only writer of this transition is
        the human-gated promotion path, enforced at a higher layer, not
        here; this method just guarantees immutability of the record)."""
        return replace(self, promotion_status=status)


@dataclass(frozen=True, slots=True)
class ModelVersion:
    backbone_identifier: str
    prompt_or_weight_hash: str
    knowledge_cutoff: datetime  # mandatory — feeds ER-3's contamination check directly
    parent_strategy_version: str  # FK -> StrategyVersion.version_id
    version_id: str = ""

    def __post_init__(self) -> None:
        require_non_empty_str(self.backbone_identifier, "backbone_identifier")
        require_non_empty_str(self.prompt_or_weight_hash, "prompt_or_weight_hash")
        object.__setattr__(
            self, "knowledge_cutoff", require_aware_utc(self.knowledge_cutoff, "knowledge_cutoff")
        )
        require_uuid_like(self.parent_strategy_version, "parent_strategy_version")
        if not self.version_id:
            object.__setattr__(
                self,
                "version_id",
                content_hash(self.backbone_identifier, self.prompt_or_weight_hash),
            )
        require_uuid_like(self.version_id, "version_id")


@dataclass(frozen=True, slots=True)
class ConfigurationVersion:
    values: dict  # snapshot of all Plane 0 operator-set values (frozen via MappingProxyType below)
    set_by: str  # always the operator (Stage 3 §2)
    effective_from: datetime
    version_id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        # set_by is a free-text operator identity (e.g. a username), not
        # constrained to the literal string "operator" — the requirement
        # (Stage 3 §2) is that it is ALWAYS a human operator action, which
        # is enforced structurally elsewhere (§14/§16's promotion boundary),
        # not by string-matching this field.
        require_non_empty_str(self.set_by, "set_by")
        object.__setattr__(
            self, "effective_from", require_aware_utc(self.effective_from, "effective_from")
        )
        require_uuid_like(self.version_id, "version_id")
        if not isinstance(self.values, (dict, MappingProxyType)):
            raise ValueError("values must be a dict")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class RiskRuleVersion:
    """Tracked separately from general Plane 3 code versioning (RR-9)."""

    rule_set_hash: str
    effective_from: datetime
    version_id: str = ""

    def __post_init__(self) -> None:
        require_non_empty_str(self.rule_set_hash, "rule_set_hash")
        object.__setattr__(
            self, "effective_from", require_aware_utc(self.effective_from, "effective_from")
        )
        if not self.version_id:
            object.__setattr__(self, "version_id", content_hash(self.rule_set_hash))
        require_uuid_like(self.version_id, "version_id")
