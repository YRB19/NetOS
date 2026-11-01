// Command-centre redesign tests (frontend only; node:test). They assert honesty rules, not just rendering.
import test from "node:test";
import assert from "node:assert/strict";
import { createApp } from "../public/app.js";
import * as CC from "../public/command.js";
import { META, snapApi, fakeRoot, text } from "./harness.mjs";

const S = META.scenarios;
const go = async (hash, api = snapApi()) => { const root = fakeRoot(); const app = createApp({ root, api }); const r = await app.go(hash); return { html: root.innerHTML, r, api }; };
const ov = (id) => snapApi().get(`/runs/${id}/overview`);

test("command centre is the landing page with all five regions and eight stages", async () => {
  const { html, r } = await go(`#/?run=${S.success}`);
  assert.equal(r.ok, true);
  for (const id of ["h-in", "h-core", "h-term", "h-cap", "h-sum"]) assert.ok(html.includes(`id="${id}"`), id);
  assert.equal((html.match(/class="node node-/g) || []).length, 8);
  assert.match(html, /INTELLIGENCE PROVIDER: NOT CONNECTED/); assert.match(html, /READ-ONLY/); assert.match(html, /RECORDED REPLAY/);
  assert.match(html, /SYNTHETIC ENVIRONMENT/); assert.match(html, /DEMO MODE/);
  assert.equal((html.match(/<h1/g) || []).length, 1);
});

test("six navigation areas exist; legacy pages keep their own active area", async () => {
  const { html } = await go("#/runs");
  for (const l of ["COMMAND CENTRE", "RUNS &amp; EXPERIMENTS", "DECISION HISTORY", "RISK &amp; EXECUTION", "RESEARCH", "SYSTEM / AUDIT"]) assert.ok(html.includes(l), l);
  const o = await go(`#/orders?run=${S.success}`);
  assert.match(o.html, /aria-label="Section"/); assert.match(o.html, /Orders &amp; reconciliation/);
});

test("honesty: no live/AI claims; deterministic engine and unconnected sources are stated", async () => {
  const { html } = await go(`#/?run=${S.success}`);
  assert.doesNotMatch(html, /\b(ONLINE|ALIVE|LIVE TRADING|thinking|reasoning\.\.\.)\b/i);
  assert.match(html, /not an AI agent/i); assert.match(html, /Live NSE market feed/); assert.match(html, /NOT CONNECTED/);
  assert.match(html, /Per-instrument price series are not persisted/);
  assert.doesNotMatch(html, /data-live="1"/);
});

test("no execution or control affordances were introduced", async () => {
  const { html, api } = await go(`#/?run=${S.success}`);
  assert.doesNotMatch(html, /<form|type="submit"|Place order|Submit order|Kill switch|Halt trading|Transfer capital/i);
  const buttons = [...html.matchAll(/<button[^>]*>/g)].map((m) => m[0]);
  assert.ok(buttons.every((b) => /data-stream-filter/.test(b)), "only display-filter buttons exist");
  assert.ok(api.calls.every((c) => !/export|POST|DELETE|PUT/.test(c)));
});

test("stage derivation uses only recorded facts; missing detail is UNAVAILABLE, not fabricated", async () => {
  const o = await ov(S.success);
  const st = CC.deriveStages({ ov: o, detail: null, order: null });
  assert.equal(st.length, 8);
  assert.equal(st.find((s) => s.key === "data").status, "METADATA_ONLY");
  for (const k of ["context", "analysis", "proposal", "risk", "allocation", "execution", "settlement"]) assert.equal(st.find((s) => s.key === k).status, "UNAVAILABLE", k);
});

test("a HOLD-only chain never shows execution or settlement as recorded", () => {
  const detail = { decision_id: "d1", stages: [{ stage: "snapshot", status: "RECORDED", facts: [{}] }, { stage: "candidate", status: "RECORDED", facts: [{ action: "HOLD", strategy_version_id: "s1", model_version_id: null }] },
    { stage: "fills", status: "NOT_RECORDED", facts: [] }, { stage: "portfolio_settlement", status: "NOT_RECORDED", facts: [] }], events: [] };
  const st = CC.deriveStages({ ov: { run: { dataset: {}, evidence: {} } }, detail, order: null });
  assert.equal(st.find((s) => s.key === "execution").status, "NOT_RECORDED");
  assert.equal(st.find((s) => s.key === "settlement").status, "NOT_RECORDED");
  assert.equal(st.find((s) => s.key === "analysis").status, "DETERMINISTIC");
});

test("risk veto renders as FAILED and an order is not shown as executed without a fill", () => {
  const detail = { decision_id: "d2", stages: [{ stage: "risk", status: "RECORDED", facts: [{ verdict: "REJECT", checks: [{ check_id: "RR-1", passed: false }] }] },
    { stage: "submission", status: "RECORDED", facts: [{ outcome: "ACCEPTED" }] }, { stage: "fills", status: "NOT_RECORDED", facts: [] }], events: [] };
  const st = CC.deriveStages({ ov: { run: { dataset: {}, evidence: {} } }, detail, order: null });
  assert.equal(st.find((s) => s.key === "risk").status, "FAILED");
  assert.match(st.find((s) => s.key === "execution").summary, /no fill is recorded/);
});

test("stream rows come from persisted events, keep unknown types verbatim, and never invent rows", () => {
  const r = CC.streamRow({ event_type: "RISK_EVALUATED", payload: { verdict: "REJECT", checks: [{ check_id: "RR-1", passed: false }] }, sequence: 3, event_id: "e", recorded_at: "2026-01-01T00:00:00Z" });
  assert.equal(r.cat, "RISK"); assert.equal(r.text, "Order blocked"); assert.equal(r.kind, "bad");
  const u = CC.streamRow({ event_type: "SOMETHING_NEW", payload: {}, sequence: 1, event_id: "x" });
  assert.equal(u.cat, "EVENT"); assert.equal(u.text, "SOMETHING_NEW");
  assert.deepEqual(CC.fallbackRows({ orders: null, recon: null }), []);
});

test("missing equity stays 'Unavailable', never zero; synthetic marker on capital panel", async () => {
  const { html } = await go(`#/?run=${S.incomplete_blocked}`);
  assert.match(html, /Unavailable: /); assert.match(html, /INCOMPLETE_DECISIONS/);
  const ok = await go(`#/?run=${S.success}`);
  assert.match(ok.html, /SYNTHETIC VALUES/); assert.match(ok.html, /Benchmark comparison: <span class="unknown"/);
});

test("auxiliary read failures degrade to Unavailable instead of failing the page", async () => {
  const base = snapApi();
  const api = { calls: [], async get(p, q) { if (/\/orders|\/reconciliation|\/decisions\//.test(p)) throw new Error("boom"); return base.get(p, q); } };
  const { html, r } = await go(`#/?run=${S.success}`, api);
  assert.equal(r.ok, true); assert.match(html, /Fills are unavailable|No fills/); assert.match(html, /id="h-core"/);
});

test("all view output is CSP-safe: no inline style attributes or handlers", async () => {
  const { html } = await go(`#/?run=${S.success}`);
  assert.doesNotMatch(html, /\sstyle="/); assert.doesNotMatch(html, /\son[a-z]+=/i); assert.doesNotMatch(text(html), /\[object Object\]|undefined|NaN/);
});
