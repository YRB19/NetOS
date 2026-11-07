"""ModelVersion construction for the AI overlay (Slice 11).

`domain.models.versions.ModelVersion` derives its DEFAULT version_id from only
(backbone_identifier, prompt_or_weight_hash). That would give two models with different
knowledge cutoffs, schema versions or parents the SAME id. Changing that default would silently
re-identify old artifacts, so it is left untouched; this builder passes an explicit version_id
derived from EVERY materially relevant field instead.

Knowledge cutoff is mandatory and is NEVER invented. If a reliable cutoff has not been
established, the declaration is UNKNOWN and the ModelVersion carries the far-future sentinel date
so every contamination check FAILS CLOSED (no confirmatory classification is possible).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from domain.models.versions import ModelVersion
from intelligence.llm_component.prompt import prompt_hash
from intelligence.llm_component.schema import OUTPUT_SCHEMA_VERSION
from shared.versioning.content_hash import hash_json_stable

UNKNOWN_CUTOFF_SENTINEL = datetime(9999, 12, 31, tzinfo=UTC)


class CutoffBasis(str, Enum):  # noqa: UP042
    PROVIDER_DOCUMENTED = "PROVIDER_DOCUMENTED"  # operator cites authoritative provider documentation
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CutoffDeclaration:
    basis: CutoffBasis
    cutoff: datetime | None = None
    source_note: str = ""  # where the date came from (URL/title) - required when documented

    def __post_init__(self) -> None:
        if self.basis is CutoffBasis.PROVIDER_DOCUMENTED:
            if self.cutoff is None or not self.source_note.strip():
                raise ValueError("a documented cutoff requires a date and a source_note")
        elif self.cutoff is not None:
            raise ValueError("an UNKNOWN cutoff must not carry a date")

    @property
    def effective_cutoff(self) -> datetime:
        return self.cutoff if self.cutoff is not None else UNKNOWN_CUTOFF_SENTINEL

    @property
    def confirmatory_eligible(self) -> bool:
        return self.basis is CutoffBasis.PROVIDER_DOCUMENTED


def build_model_version(provider_name: str, model_identifier: str, cutoff: CutoffDeclaration,
                        parent_strategy_version_id: str) -> ModelVersion:  # fmt: skip
    backbone = f"{provider_name}:{model_identifier}"
    p_hash = prompt_hash()
    vid = hash_json_stable([backbone, p_hash, OUTPUT_SCHEMA_VERSION, cutoff.effective_cutoff.isoformat(),
                            cutoff.basis.value, parent_strategy_version_id])[:32]  # fmt: skip
    return ModelVersion(backbone_identifier=backbone, prompt_or_weight_hash=p_hash,
                        knowledge_cutoff=cutoff.effective_cutoff,
                        parent_strategy_version=parent_strategy_version_id, version_id=vid)  # fmt: skip
