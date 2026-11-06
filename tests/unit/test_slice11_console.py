"""Slice 11 - console read model for the AI research signal (read-only, recorded facts only)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import tempfile

from console_api import readmodel as R
from console_api.store import ArtifactStore
from tests.integration.test_slice11_pipeline import run_overlay


_TMP = None
DEMO: Path
IDS: dict = {}


def setUpModule():
    global _TMP, DEMO
    from tests.unit.test_console_api import (
        demo,
    )  # the same demo-store builder the console tests use

    _TMP = tempfile.TemporaryDirectory()
    DEMO = Path(_TMP.name) / "demo"
    IDS.update(demo.build(DEMO))


def tearDownModule():
    _TMP.cleanup()


class _FakeStore:
    def __init__(self, reader):
        self._r = reader

    def verified_reader(self, run_id, allow_unverified=False):
        return SimpleNamespace(reader=self._r)


class AiSignalsReadModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res, cls.j, cls.r, cls.o, cls.sigs, cls.svc = run_overlay("POSITIVE")
        cls.out = R.ai_signals(_FakeStore(cls.r), "run-x")

    def test_ai_enabled_summary_is_derived_only_from_journal_facts(self):
        o = self.out
        self.assertTrue(o["ai_used"])
        self.assertEqual(o["label"], "RESEARCH SIGNAL ONLY")
        self.assertTrue(o["read_only"])
        self.assertEqual(o["run_label"], "AI-ENABLED")
        self.assertGreater(o["adjusted_confidence_events"], 0)
        self.assertEqual(o["status_counts"].get("OK"), o["events"])
        self.assertEqual(o["models"], ["stub-model-v1"])

    def test_stub_is_never_presented_as_a_real_provider(self):
        self.assertIn("no real model was called", self.out["provider"])

    def test_tokens_present_but_cost_not_invented(self):
        self.assertIsNotNone(self.out["tokens"])
        self.assertIsNone(self.out["estimated_cost_usd"])  # no verified pricing configured

    def test_no_secret_or_key_material_in_payload(self):
        s = json.dumps(self.out, default=str).lower()
        for bad in ("api_key", "x-api-key", "sk-ant", "authorization"):
            self.assertNotIn(bad, s)

    def test_ai_disabled_run_reports_disabled_without_inventing_activity(self):
        out = R.ai_signals(
            ArtifactStore(DEMO), IDS["complete"] if "complete" in IDS else next(iter(IDS.values()))
        )
        self.assertFalse(out["ai_used"])
        self.assertEqual(out["run_label"], "AI-DISABLED")
        self.assertEqual(out["provider"], "DISABLED")
        self.assertEqual(out["disclosure_source"], "NOT_CONNECTED")
        self.assertNotIn("rows", out)


class ReadOnlySurface(unittest.TestCase):
    def test_no_mutating_or_secret_surface_added(self):
        src = (Path(__file__).resolve().parents[2] / "console_api" / "server.py").read_text()
        self.assertIn("ai-signals", src)
        for bad in ("ANTHROPIC", "os.environ", "api_key"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
