import test from "node:test";
import assert from "node:assert/strict";
import { aiPanel } from "../public/command.js";

test("AI panel: no data is shown as unavailable, never as activity", () => {
  const h = aiPanel(null);
  assert.match(h, /RESEARCH SIGNAL ONLY/);
  assert.match(h, /Unavailable/);
  assert.doesNotMatch(h, /thinking|processing|analys/i);
});

test("AI panel: AI-disabled run says DISABLED / NOT_CONNECTED and invents nothing", () => {
  const h = aiPanel({ ai_used: false, run_label: "AI-DISABLED", provider: "DISABLED", disclosure_source: "NOT_CONNECTED", reason: "no events" });
  assert.match(h, /AI-DISABLED/);
  assert.match(h, /NOT_CONNECTED/);
  assert.doesNotMatch(h, /<table/);
});

test("AI panel: AI-enabled run shows recorded facts, label, and stub honesty; escapes HTML", () => {
  const h = aiPanel({
    ai_used: true, run_label: "AI-ENABLED", provider: "STUB_OR_OFFLINE (no real model was called)", models: ["stub-model-v1"],
    model_versions: ["abc"], prompt_hashes: ["0123456789abcdef"], output_schema_versions: ["disclosure_interpretation_v1"],
    events: 3, adjusted_confidence_events: 2, no_signal_or_unknown: 1, status_counts: { OK: 2, TIMEOUT: 1 },
    tokens: { input: 10, output: 5 }, estimated_cost_usd: null,
    rows: [{ instrument_id: "<img src=x onerror=alert(1)>", provider_status: "OK", sentiment: "POSITIVE", materiality: "HIGH", applied: true, original_confidence: "0.5", adjusted_confidence: "0.58" }],
  });
  assert.match(h, /RESEARCH SIGNAL ONLY/);
  assert.match(h, /no real model was called/);
  assert.match(h, /requested model: stub-model-v1/);
  assert.match(h, /returned by provider/);
  assert.match(h, /not computed/);
  assert.match(h, /cannot change BUY\/SELL\/HOLD/);
  assert.doesNotMatch(h, /<img src=x/);
  assert.doesNotMatch(h, /<button|<form|<input/);
});

import { createApp } from "../public/app.js";
import { META, snapApi, fakeRoot } from "./harness.mjs";

test("command centre renders the AI panel (read-only, labelled) on a run page", async () => {
  const root = fakeRoot();
  const app = createApp({ root, api: snapApi() });
  await app.go(`#/?run=${META.scenarios.success}`);
  assert.match(root.innerHTML, /AI research signal/);
  assert.match(root.innerHTML, /RESEARCH SIGNAL ONLY/);
});
