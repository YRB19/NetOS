"""Every model that Stage 3 §15/§19 requires to carry a version reference
actually has one, correctly typed and non-empty, and content-addressed
identities are genuinely deterministic (same content -> same id).
"""

import unittest

from domain.models import (
    ConfigurationVersion,
    ModelVersion,
    Plane2Type,
    PromotionStatus,
    RiskRuleVersion,
    StrategyVersion,
)
from tests.unit._helpers import utc


class TestVersionReferences(unittest.TestCase):
    def test_strategy_version_has_non_empty_id(self):
        sv = StrategyVersion(plane2_type=Plane2Type.BASELINE, code_or_config_hash="abc")
        self.assertIsInstance(sv.version_id, str)
        self.assertTrue(sv.version_id)

    def test_strategy_version_id_is_content_deterministic(self):
        sv1 = StrategyVersion(plane2_type=Plane2Type.BASELINE, code_or_config_hash="same-content")
        sv2 = StrategyVersion(plane2_type=Plane2Type.BASELINE, code_or_config_hash="same-content")
        self.assertEqual(sv1.version_id, sv2.version_id)

    def test_strategy_version_id_differs_for_different_content(self):
        sv1 = StrategyVersion(plane2_type=Plane2Type.BASELINE, code_or_config_hash="content-a")
        sv2 = StrategyVersion(plane2_type=Plane2Type.BASELINE, code_or_config_hash="content-b")
        self.assertNotEqual(sv1.version_id, sv2.version_id)

    def test_strategy_version_promotion_status_transition_is_non_mutating(self):
        sv = StrategyVersion(plane2_type=Plane2Type.BASELINE, code_or_config_hash="abc")
        self.assertEqual(sv.promotion_status, PromotionStatus.DRAFT)
        promoted = sv.promoted_to(PromotionStatus.PAPER_APPROVED)
        self.assertEqual(promoted.promotion_status, PromotionStatus.PAPER_APPROVED)
        self.assertEqual(sv.promotion_status, PromotionStatus.DRAFT)  # original untouched
        self.assertEqual(promoted.version_id, sv.version_id)  # same underlying artifact identity

    def test_model_version_requires_knowledge_cutoff(self):
        sv = StrategyVersion(plane2_type=Plane2Type.LLM, code_or_config_hash="abc")
        mv = ModelVersion(
            backbone_identifier="test-backbone",
            prompt_or_weight_hash="hash-1",
            knowledge_cutoff=utc(-30),
            parent_strategy_version=sv.version_id,
        )
        self.assertIsNotNone(mv.knowledge_cutoff)
        self.assertEqual(mv.knowledge_cutoff.tzinfo is not None, True)

    def test_model_version_id_is_content_deterministic(self):
        mv1 = ModelVersion(
            backbone_identifier="b",
            prompt_or_weight_hash="h",
            knowledge_cutoff=utc(-1),
            parent_strategy_version="parent-1",
        )
        mv2 = ModelVersion(
            backbone_identifier="b",
            prompt_or_weight_hash="h",
            knowledge_cutoff=utc(-1),
            parent_strategy_version="parent-2",  # lineage differs; content hash should not
        )
        self.assertEqual(mv1.version_id, mv2.version_id)

    def test_risk_rule_version_id_present_and_deterministic(self):
        rrv1 = RiskRuleVersion(rule_set_hash="rules-v1", effective_from=utc())
        rrv2 = RiskRuleVersion(rule_set_hash="rules-v1", effective_from=utc(1))
        self.assertTrue(rrv1.version_id)
        self.assertEqual(rrv1.version_id, rrv2.version_id)  # identity is content, not time

    def test_configuration_version_has_unique_identity_id(self):
        cv1 = ConfigurationVersion(values={"a": 1}, set_by="operator", effective_from=utc())
        cv2 = ConfigurationVersion(values={"a": 1}, set_by="operator", effective_from=utc())
        # ConfigurationVersion is identity-addressed (a fresh UUID per snapshot),
        # NOT content-addressed — two config snapshots with identical values
        # taken at different times are still distinct historical facts.
        self.assertNotEqual(cv1.version_id, cv2.version_id)


if __name__ == "__main__":
    unittest.main()
