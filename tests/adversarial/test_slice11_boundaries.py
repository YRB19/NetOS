"""Slice 11 - architecture boundaries for the AI component (ADR-22). Planted violations must be caught."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.adversarial.test_slice6_isolation import plant

ROOT = Path(__file__).resolve().parents[2]


class ProviderLeafPackage(unittest.TestCase):
    def test_no_plane_may_import_model_providers(self):
        for pkg in ("intelligence/baseline", "intelligence/llm_component", "risk_execution/risk_engine", "research/harness",
                    "governance/config", "data/features", "simulation", "observability/decision_log", "domain/models"):  # fmt: skip
            v = plant(pkg, "bad", "from model_providers.anthropic_provider import AnthropicProvider\n")
            self.assertTrue(v, pkg)

    def test_model_providers_cannot_reach_execution_risk_governance_or_data(self):
        for tgt in ("risk_execution.broker", "risk_execution.risk_engine", "governance.config", "research.harness",
                    "data.adapters", "simulation", "intelligence.baseline", "intelligence.llm_component.overlay"):  # fmt: skip
            v = plant("model_providers", "bad", f"import {tgt}\n")
            self.assertTrue(v, tgt)

    def test_nvidia_provider_is_inside_the_same_leaf_boundary(self):
        for tgt in ("risk_execution.broker", "governance.config", "data.adapters", "simulation"):
            self.assertTrue(plant("model_providers", "nvidia_extra", f"import {tgt}\n"), tgt)
        self.assertTrue(plant("risk_execution/broker", "bad", "from model_providers.nvidia_provider import NvidiaProvider\n"))

    def test_model_providers_may_use_only_provider_and_prompt_types(self):
        ok = plant("model_providers", "okmod", "from intelligence.llm_component.provider import ProviderError\n"
                   "from intelligence.llm_component.prompt import ProviderRequest\n")  # fmt: skip
        self.assertEqual(ok, [])

    def test_llm_component_cannot_import_broker_risk_or_governance(self):
        for tgt in ("risk_execution.broker", "risk_execution.risk_engine", "governance.config", "research.harness", "data.adapters"):
            self.assertTrue(plant("intelligence/llm_component", "bad", f"import {tgt}\n"), tgt)

    def test_slice6_no_network_modules_inside_intelligence_still_true(self):
        net = re.compile(r"^\s*(import|from)\s+(socket|urllib|http|requests|httpx|ssl|asyncio)\b", re.M)
        for f in (ROOT / "intelligence").rglob("*.py"):
            self.assertIsNone(net.search(f.read_text()), f)

    def test_only_model_providers_references_the_api_key_env_names(self):
        for d in ("intelligence", "data", "domain", "risk_execution", "research", "observability", "simulation",
                  "console_api", "governance", "frontend/public"):  # fmt: skip
            for f in (ROOT / d).rglob("*"):
                if f.is_file() and f.suffix in {".py", ".js", ".html"}:
                    for name in ("ANTHROPIC_API_KEY", "NVIDIA_API_KEY"):
                        self.assertNotIn(name, f.read_text(), f)

    def test_no_api_key_material_committed_anywhere(self):
        pat = re.compile(r"(sk-ant-[A-Za-z0-9_-]{10,}|nvapi-[A-Za-z0-9_-]{20,})")
        for f in ROOT.rglob("*"):
            if f.is_file() and ".venv" not in f.parts and ".git" not in f.parts and f.suffix in {".py", ".md", ".json", ".jsonl", ".js", ".mjs", ".html", ".txt", ".toml"}:
                self.assertIsNone(pat.search(f.read_text(errors="ignore")), f)


class ExistingContractsUntouched(unittest.TestCase):
    def test_candidate_trade_and_feature_snapshot_fields_unchanged(self):
        from dataclasses import fields

        from domain.models.feature_snapshot import FeatureSnapshot
        from domain.models.trade import CandidateTrade

        self.assertEqual({f.name for f in fields(CandidateTrade)},
                         {"candidate_id", "instrument_id", "timestamp", "action", "size_hint", "confidence",
                          "uncertainty_band", "rationale", "input_snapshot_id", "strategy_version_id", "model_version_id"})  # fmt: skip
        self.assertNotIn("disclosure", " ".join(f.name for f in fields(FeatureSnapshot)))

    def test_default_model_version_identity_unchanged_for_old_artifacts(self):
        from datetime import UTC, datetime

        from domain.models.versions import ModelVersion

        a = ModelVersion("B", "h", datetime(2023, 1, 1, tzinfo=UTC), "p")
        b = ModelVersion("B", "h", datetime(2024, 1, 1, tzinfo=UTC), "p2")
        self.assertEqual(a.version_id, b.version_id)  # documented legacy behaviour, deliberately NOT changed


if __name__ == "__main__":
    unittest.main()
