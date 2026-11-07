"""NVIDIA hosted provider + explicit provider selection. OFFLINE: every call goes through an injected
transport; urlopen is patched to fail the test if it is ever reached. No credentials, no cost."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from intelligence.llm_component.prompt import render_request
from intelligence.llm_component.provider import (
    ProviderError, ProviderRateLimited, ProviderTimeout, ProviderUnavailable, StubProvider, stub_signal,
)  # fmt: skip
from intelligence.llm_component.signals import ProviderStatus, SignalConfig, SignalService
from model_providers.anthropic_provider import AnthropicProvider
from model_providers.factory import select_provider
from model_providers.nvidia_provider import (
    DEFAULT_BASE_URL, DEFAULT_MODEL, SUPPORTED_THINKING_MODEL, NvidiaProvider, chat_completions_url,
)  # fmt: skip
from tests.unit._slice11_helpers import T0
from tests.unit.test_slice11_ai_component import ctx_one

ROOT = Path(__file__).resolve().parents[2]
KEY = "nvapi-SECRET-KEY-123456"


def envelope(text, model="moonshotai/kimi-k2-instruct", usage=None):
    return {"id": "chatcmpl-1", "model": model, "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160} if usage is None else usage}  # fmt: skip


def make(status=200, body=None, exc=None, **kw):
    calls = []

    def tr(url, headers, data, timeout):
        calls.append((url, headers, json.loads(data), timeout))
        if exc:
            raise exc
        return status, json.dumps(body if body is not None else envelope("{}")).encode()

    return NvidiaProvider(KEY, transport=tr, **kw), calls


class ConfigurationTests(unittest.TestCase):
    def test_defaults_and_endpoint(self):
        p = NvidiaProvider.from_env({"NVIDIA_API_KEY": "k"})
        self.assertEqual(p.model_identifier, "moonshotai/kimi-k2-instruct")
        self.assertEqual(DEFAULT_MODEL, "moonshotai/kimi-k2-instruct")
        self.assertEqual(p.url, "https://integrate.api.nvidia.com/v1/chat/completions")
        self.assertEqual(DEFAULT_BASE_URL, "https://integrate.api.nvidia.com/v1")

    def test_thinking_model_and_base_url_by_configuration(self):
        p = NvidiaProvider.from_env({"NVIDIA_API_KEY": "k", "NVIDIA_MODEL": SUPPORTED_THINKING_MODEL,
                                     "NVIDIA_BASE_URL": "https://example.test/v1/"})  # fmt: skip
        self.assertEqual(p.model_identifier, "moonshotai/kimi-k2-thinking")
        self.assertEqual(p.url, "https://example.test/v1/chat/completions")

    def test_missing_key_is_unavailable(self):
        for env in ({}, {"NVIDIA_API_KEY": "  "}, {"NVIDIA_MODEL": "m"}):
            with self.assertRaises(ProviderUnavailable):
                NvidiaProvider.from_env(env)

    def test_base_url_must_be_plain_https(self):
        for bad in ("http://integrate.api.nvidia.com/v1", "ftp://x/v1", "https://user:pw@host/v1", "https://h/v1?x=1", "https:///v1", "x"):
            with self.assertRaises(ProviderUnavailable, msg=bad):
                chat_completions_url(bad)


class RequestAndResponseTests(unittest.TestCase):
    def setUp(self):
        self.req = render_request(ctx_one())

    def test_request_construction_no_tools_server_side_auth(self):
        p, calls = make(timeout_s=7)
        p.complete(self.req)
        url, headers, body, timeout = calls[0]
        self.assertEqual(url, "https://integrate.api.nvidia.com/v1/chat/completions")
        self.assertEqual(headers["authorization"], f"Bearer {KEY}")
        self.assertEqual((body["model"], body["temperature"], body["stream"], timeout), ("moonshotai/kimi-k2-instruct", 0, False, 7))
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        for forbidden in ("tools", "tool_choice", "functions"):
            self.assertNotIn(forbidden, body)

    def test_returned_model_and_usage_are_retained(self):
        p, _ = make(body=envelope("{}", model="moonshotai/kimi-k2-instruct-0905"))
        r = p.complete(self.req)
        self.assertEqual(r.model_identifier, "moonshotai/kimi-k2-instruct-0905")  # resolved id, not the configured one
        self.assertEqual((r.input_tokens, r.output_tokens, r.provider_request_id), (120, 40, "chatcmpl-1"))

    def test_unreturned_model_is_none_not_copied_from_config(self):
        body = envelope("{}")
        del body["model"]
        self.assertIsNone(make(body=body)[0].complete(self.req).model_identifier)

    def test_http_error_mapping(self):
        for status, exc in ((429, ProviderRateLimited), (408, ProviderTimeout), (504, ProviderTimeout), (500, ProviderError), (401, ProviderError)):
            with self.assertRaises(exc):
                make(status=status)[0].complete(self.req)
        with self.assertRaises(ProviderTimeout):
            make(exc=TimeoutError())[0].complete(self.req)

    def test_malformed_envelopes(self):
        for body in ({"weird": 1}, {"choices": []}, {"choices": [{"message": {"content": None}}]}, {"choices": [{"message": {}}]}):
            with self.assertRaises(ProviderError) as cm:
                make(body=body)[0].complete(self.req)
            self.assertIn("malformed", str(cm.exception))

    def test_secret_never_in_errors_or_repr(self):
        with self.assertRaises(ProviderError) as cm:
            make(status=500, body={"error": f"{KEY} echoed"})[0].complete(self.req)
        self.assertNotIn("SECRET", str(cm.exception))
        self.assertNotIn("SECRET", repr(make()[0]))

    def test_think_block_discarded_and_reasoning_field_never_read(self):
        c = ctx_one()
        good = json.dumps(stub_signal(c, "POSITIVE"))
        body = envelope("<think>private chain of thought</think>\n" + good, model="moonshotai/kimi-k2-thinking")
        body["choices"][0]["message"]["reasoning_content"] = "SECRET REASONING"
        r = make(body=body)[0].complete(self.req)
        self.assertEqual(r.text, good)
        self.assertNotIn("REASONING", r.text)
        self.assertNotIn("private", r.text)


class ReusesExistingPipeline(unittest.TestCase):
    """Same canonical schema, provenance, timeout handling, budget and failure-to-NO_SIGNAL behaviour."""

    def svc(self, provider, **cfg):
        return SignalService(provider, SignalConfig(enabled=True, **cfg), clock=lambda: T0, sleep=lambda s: None)

    def test_valid_classification_with_full_provenance(self):
        c = ctx_one()
        p, _ = make(body=envelope(json.dumps(stub_signal(c, "POSITIVE")), model="moonshotai/kimi-k2-instruct-0905"))
        rec = self.svc(p).evaluate(c)
        self.assertEqual(rec.provider_status, ProviderStatus.OK)
        self.assertTrue(rec.has_signal)
        self.assertEqual(rec.provider_name, "NVIDIA")
        self.assertEqual(rec.requested_model_identifier, "moonshotai/kimi-k2-instruct")
        self.assertEqual(rec.resolved_model_identifier, "moonshotai/kimi-k2-instruct-0905")
        self.assertEqual((rec.input_tokens, rec.output_tokens), (120, 40))
        payload = json.dumps(rec.to_payload(), default=str)
        self.assertNotIn("SECRET", payload)
        self.assertNotIn(KEY, payload)

    def test_same_schema_rejection_forbidden_fields(self):
        c = ctx_one()
        p, _ = make(body=envelope(json.dumps({**stub_signal(c, "POSITIVE"), "action": "BUY", "quantity": 10})))
        rec = self.svc(p).evaluate(c)
        self.assertEqual(rec.provider_status, ProviderStatus.MALFORMED_OUTPUT)
        self.assertFalse(rec.has_signal)

    def test_failures_become_explicit_no_signal_states(self):
        c = ctx_one()
        for kw, st in (({"status": 429}, "RATE_LIMITED"), ({"exc": TimeoutError()}, "TIMEOUT"), ({"status": 500}, "PROVIDER_ERROR"),
                       ({"body": envelope("not json")}, "MALFORMED_OUTPUT")):  # fmt: skip
            p, _ = make(**kw)
            rec = self.svc(p, max_retries=0).evaluate(c)
            self.assertEqual(rec.provider_status.value, st)
            self.assertFalse(rec.has_signal)

    def test_bounded_retry_on_rate_limit_and_request_budget(self):
        c = ctx_one()
        p, calls = make(status=429)
        self.svc(p, max_retries=2).evaluate(c)
        self.assertEqual(len(calls), 3)
        p2, calls2 = make(body=envelope(json.dumps(stub_signal(c, "POSITIVE"))))
        s = self.svc(p2, max_requests=2)
        st = [s.evaluate(c).provider_status for _ in range(4)]
        self.assertEqual(st, [ProviderStatus.OK] * 2 + [ProviderStatus.BUDGET_EXHAUSTED] * 2)
        self.assertEqual(len(calls2), 2)


class ExplicitSelectionNoFallback(unittest.TestCase):
    def test_each_provider_is_selected_by_name_only(self):
        env = {"NVIDIA_API_KEY": "n", "ANTHROPIC_API_KEY": "a", "ANTHROPIC_MODEL": "m"}
        self.assertIsInstance(select_provider("nvidia", env), NvidiaProvider)
        self.assertIsInstance(select_provider("anthropic", env), AnthropicProvider)
        self.assertIsInstance(select_provider("stub", {}), StubProvider)

    def test_never_silently_falls_back_to_another_provider(self):
        # nvidia requested, only the OTHER paid provider is configured -> unavailable, not substituted
        with self.assertRaises(ProviderUnavailable):
            select_provider("nvidia", {"ANTHROPIC_API_KEY": "a", "ANTHROPIC_MODEL": "m"})
        with self.assertRaises(ProviderUnavailable):
            select_provider("anthropic", {"NVIDIA_API_KEY": "n"})
        with self.assertRaises(ProviderUnavailable):
            select_provider("", {"NVIDIA_API_KEY": "n", "ANTHROPIC_API_KEY": "a", "ANTHROPIC_MODEL": "m"})
        with self.assertRaises(ProviderUnavailable):
            select_provider("openai", {})

    def test_provider_names_are_distinct_for_journal_and_console(self):
        self.assertEqual({NvidiaProvider("k").provider_name, AnthropicProvider("k", "m").provider_name, StubProvider().provider_name},
                         {"NVIDIA", "ANTHROPIC", "STUB"})  # fmt: skip

    def test_urlopen_never_reached_by_the_suite(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call in test")):
            make()[0].complete(render_request(ctx_one()))


class SmokeCommand(unittest.TestCase):
    """The manual smoke command, exercised only where it cannot reach the network."""

    def run_cmd(self, *args, env_extra=None):
        d = tempfile.mkdtemp()
        f = Path(d) / "d.jsonl"
        f.write_text(json.dumps({"source_document_id": "S-1", "isin": "I1", "published_at": "2026-04-01T09:00:00+00:00",
                                 "ingested_at": "2026-04-01T09:30:00+00:00", "text": "SYNTHETIC announcement."}))  # fmt: skip
        env = {"PATH": os.environ.get("PATH", ""), **(env_extra or {})}
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "slice11_smoke.py"), "--disclosures", str(f), "--instrument", "I1",
                               "--decision-time", "2026-04-06T10:00:00+00:00", "--isin-map", "I1=I1", *args],
                              capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)  # fmt: skip

    def test_stub_default_is_offline_and_succeeds(self):
        r = self.run_cmd()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(json.loads(r.stdout)["real_provider"])

    def test_real_provider_requires_confirm_live(self):
        for prov in ("nvidia", "anthropic"):
            r = self.run_cmd("--provider", prov, env_extra={"NVIDIA_API_KEY": "x", "ANTHROPIC_API_KEY": "y", "ANTHROPIC_MODEL": "m"})
            self.assertEqual(r.returncode, 2)
            self.assertIn("--confirm-live", r.stderr)
            self.assertEqual(r.stdout, "")

    def test_nvidia_without_its_key_stops_and_does_not_use_another_provider(self):
        r = self.run_cmd("--provider", "nvidia", "--confirm-live", env_extra={"ANTHROPIC_API_KEY": "y", "ANTHROPIC_MODEL": "m"})
        self.assertEqual(r.returncode, 2)
        self.assertIn("NVIDIA_API_KEY is not set", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_no_secret_in_output(self):
        r = self.run_cmd("--provider", "nvidia", "--confirm-live", env_extra={"NVIDIA_API_KEY": "should-not-appear", "NVIDIA_BASE_URL": "http://insecure/v1"})
        self.assertEqual(r.returncode, 2)  # non-https base URL rejected before any call
        self.assertNotIn("should-not-appear", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
