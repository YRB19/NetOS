"""Slice 3 import paths for the canonical domain contracts."""

from domain.models.promotion import PromotionCandidate
from domain.models.research_artifacts import EvaluationRun, Experiment

__all__ = ["Experiment", "EvaluationRun", "PromotionCandidate"]
