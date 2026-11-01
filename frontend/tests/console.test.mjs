import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createApp } from "../public/app.js";
import { ApiFailure, makeApi } from "../public/api.js";
import { buildHash, parseHash, val, esc } from "../public/format.js";
import * as V from "../public/views.js";
import { SNAP, META, snapApi, fakeRoot, text } from "./harness.mjs";

const S = META.scenarios, P = META.picked;
const go = async (hash, api = snapApi()) => { const root = fakeRoot(); const app = createApp({ root, api }); const r = await app.go(hash); return { html: root.innerHTML, r, api }; };

test("overview renders from synthetic fixture with evidence + synthetic labels + read-only badge", async () => {
  const { html, r } = await go(`#/?run=${S.success}`);
  assert.equal(r.ok, true);
  assert.match(html, /READ-ONLY/); assert.match(html, /DEMO MODE/); assert.match(html, /SYNTHETIC/);
  assert.match(html, /Synthetic infrastructure evidence/);
  assert.match(text(html), /Net P\s+L/); assert.match(html, /Total decisions/);
});

test("overview: unknown values are 'Unknown'/'Unavailable', never zero", async () => {
  const { html } = await go(`#/?run=${S.success}`);
  assert.match(html, /Benchmark comparison<\/dt><dd><span class="unknown"[^>]*>Unavailable/);
  assert.equal(val(null).includes(">0<"), false); assert.match(val(undefined), /Unknown/); assert.match(val(""), /Unknown/);
  assert.match(val("0"), /0/); // a recorded zero stays a zero
});

test("run explorer lists all runs incl. incomplete, labels synthetic, no ranking language", async () => {
  const { html } = await go("#/runs");
  for (const id of Object.values(S)) assert.ok(html.includes(id.slice(0, 20)), `missing ${id}`);
  assert.match(html, /INCOMPLETE/); assert.match(html, /SYNTHETIC/);
  assert.doesNotMatch(html, /best run|top run|alpha found|profitable/i);
});

test("selecting a run opens matching detail with links to decisions", async () => {
  const { html } = await go(`#/run/${S.partial_fill}`);
  assert.ok(html.includes(S.partial_fill.slice(0, 20))); assert.match(html, /Decisions<\/a>/); assert.match(html, /Metrics/);
  assert.match(html, /unliquidated|exit costs/i);
});

test("decision list shows HOLD, NO_TRADE, vetoes, partial/cancelled, incomplete, reconciliation-blocked", async () => {
  let all = (await go(`#/decisions?run=${S.success}`)).html; assert.match(all, /HOLD/); assert.match(all, /NO_TRADE/);
  all = (await go(`#/decisions?run=${S.risk_veto}`)).html; assert.match(all, /RISK_VETO/); assert.match(all, /REJECTED_AT_RISK/);
  all = (await go(`#/decisions?run=${S.partial_fill}`)).html; assert.match(all, /PARTIAL_OR_CANCELLED/);
  all = (await go(`#/decisions?run=${S.incomplete_blocked}`)).html; assert.match(all, /INCOMPLETE/); assert.match(all, /RECONCILIATION_BLOCKED/); assert.match(all, /Not finalized/);
});

test("selecting a decision opens the matching chain with timeline stages in order", async () => {
  const { run, decision } = P.filled;
  const { html } = await go(`#/decision/${decision}?run=${run}`);
  assert.ok(html.includes(decision.slice(0, 20)));
  const order = ["Data / feature snapshot", "Candidate", "Risk evaluation", "Sizing", "Order intent", "Submission / status", "Order lifecycle", "Fills", "Portfolio settlement", "Reconciliation", "Finalized"];
  let last = -1; for (const s of order) { const i = html.indexOf(s); assert.ok(i > last, `stage ${s} out of order`); last = i; }
  assert.match(html, /Event time/); assert.match(html, /Recorded at/); assert.match(html, /RR-8/); assert.match(html, /Recorded inputs/);
  assert.match(html, /Stored explanation/); assert.match(html, /strategy is not re-run/);
});

test("HOLD/no-trade decision renders absent stages as NOT_RECORDED (not as success)", async () => {
  const { html } = await go(`#/decision/${P.hold.decision}?run=${P.hold.run}`);
  assert.match(html, /NOT_RECORDED/); assert.match(html, /no event recorded for this stage/);
});

test("vetoed decision exposes failed rule outcome and recorded inputs", async () => {
  const { html } = await go(`#/decision/${P.veto.decision}?run=${P.veto.run}`);
  assert.match(html, /FAILED/); assert.match(html, /REJECTED_AT_RISK/);
});

test("incomplete decision is flagged, never presented as complete; blocked reconciliation visible", async () => {
  const { html } = await go(`#/decision/${P.incomplete.decision}?run=${P.incomplete.run}`);
  assert.match(html, /Incomplete decision/); assert.match(html, /never finalized/); assert.match(html, /BLOCKED/);
  assert.match(html, /UNCERTAIN/); assert.match(html, /Not finalized/);
});

test("risk page: RR results, vetoes, read-only statement, no controls", async () => {
  const { html } = await go(`#/risk?run=${S.risk_veto}`);
  assert.match(html, /RR-1/); assert.match(html, /RR-9/); assert.match(html, /READ-ONLY/); assert.match(html, /vetoes/i);
  assert.doesNotMatch(html, /<button/i); assert.doesNotMatch(html, /<form/i);
});

test("orders page: partial fills, cancel-after-fill, uncertain submission and blocked reconciliation", async () => {
  let { html } = await go(`#/orders?run=${S.partial_fill}`);
  assert.match(html, /PARTIAL_FILL/); assert.match(html, /CANCELLED_AFTER_FILL/);
  ({ html } = await go(`#/orders?run=${S.incomplete_blocked}`));
  assert.match(html, /UNCERTAIN_SUBMISSION/); assert.match(html, /blocked of/); assert.match(html, /internal 120 vs broker 0/);
  assert.match(html, /Last known stage/);
});

test("research report keeps validity separate from criteria/performance", async () => {
  const rep = Object.entries(SNAP).find(([k]) => k.startsWith("/research/reports/"))[0].split("/");
  const { html } = await go(`#/report/${rep[3]}/${rep[4]}`);
  assert.match(html, /Research validity/); assert.match(html, /Criteria &amp; performance/);
  assert.ok(html.indexOf("Research validity") < html.indexOf("Criteria &amp; performance"));
  assert.match(html, /INFRASTRUCTURE_ONLY/); assert.match(html, /CRITERIA_NOT_MET/); assert.match(html, /not a statement that the strategy is profitable/);
  assert.match(html, /Not admissible as evidence/); assert.match(html, /adverse criterion/);
});

test("research page lists reports, protocols and trial ledger", async () => {
  const { html } = await go("#/research");
  assert.match(html, /Evaluation reports/); assert.match(html, /Registered protocols/); assert.match(html, /Trial ledger/); assert.match(html, /separate/);
});

test("health page: integrity, hashes, exports, honest unavailable provenance", async () => {
  const { html } = await go(`#/health?run=${S.success}`);
  assert.match(html, /VERIFIED/); assert.match(html, /Head hash/); assert.match(html, /api\/export\/decisions\?run_id=/);
  assert.match(html, /Unavailable \(no ingestion-status artifact/);
});

test("synthetic/demo label persists across every principal page", async () => {
  for (const h of ["#/", "#/runs", `#/run/${S.success}`, `#/decisions?run=${S.success}`, `#/risk?run=${S.success}`, `#/orders?run=${S.success}`, "#/research", `#/health?run=${S.success}`])
    assert.match((await go(h)).html, /DEMO MODE/, h);
});

test("loading state is shown first; error: server unreachable", async () => {
  const root = fakeRoot(); const seen = [];
  const api = { async get() { seen.push(root.innerHTML); throw new ApiFailure("network", "SERVER_UNREACHABLE", "unreachable", 0); } };
  const r = await createApp({ root, api }).go("#/");
  assert.match(seen[0], /Loading/); assert.match(root.innerHTML, /role="alert"/); assert.match(root.innerHTML, /SERVER_UNREACHABLE/); assert.equal(r.error.code, "SERVER_UNREACHABLE");
});

test("empty: no runs shows explicit status and no silent demo fallback", async () => {
  const api = snapApi({ "/runs": { total: 0, limit: 500, offset: 0, items: [], demo: false }, "/health": { status: "ok", demo: false, runs: 0, bind: "loopback-only", trading_authority: "NONE" } });
  const { html } = await go("#/", api);
  assert.match(html, /No runs available/); assert.match(html, /rather than substituting synthetic data/); assert.doesNotMatch(html, /DEMO MODE/);
});

test("corrupt/unverifiable journal: explicit error with opt-in unverified view", async () => {
  const e = new ApiFailure("api", "JOURNAL_UNVERIFIED", "journal failed integrity verification", 422);
  const { html } = await go(`#/decisions?run=${S.success}`, snapApi({ [`/runs/${S.success}/decisions`]: e }));
  assert.match(html, /JOURNAL_UNVERIFIED/); assert.match(html, /data-allow-unverified/); assert.match(html, /withheld/);
});

test("partial data: missing artifacts render 'Unavailable', stale/partial banners", async () => {
  const eq = { run_id: "x", available: false, points: [], reason: "no equity curve recorded for this run" };
  const { html } = await go(`#/?run=${S.incomplete_blocked}`, snapApi({ [`/runs/${S.incomplete_blocked}/equity`]: eq }));
  assert.match(html, /Unavailable: no equity curve/); assert.match(html, /INCOMPLETE_DECISIONS/);
});

test("stale async responses are dropped (latest navigation wins)", async () => {
  const root = fakeRoot(); let release; const gate = new Promise((r) => (release = r)); const base = snapApi();
  const api = { async get(p, q) { if (p === "/runs" && !q.__fast) { await gate; } return base.get(p, q); } };
  const app = createApp({ root, api }); const first = app.go("#/runs");
  await app.go(`#/health?run=${S.success}`); release(); await first;
  assert.match(root.innerHTML, /Health, provenance/); assert.doesNotMatch(root.innerHTML, /Run explorer/);
});

test("unknown route is a visible not-found state", async () => { assert.match((await go("#/nope")).html, /Page not found/); });

test("API client sends GET only; app issues only read paths", async () => {
  const calls = []; const api = makeApi(async (url, init) => { calls.push([url, init.method]); return { ok: true, json: async () => ({}) }; });
  await api.get("/runs", { limit: 5 }); assert.deepEqual(calls[0], ["/api/runs?limit=5", "GET"]);
  const sa = snapApi(); await go(`#/?run=${S.success}`, sa); assert.ok(sa.calls.every((c) => !/export|POST|DELETE/.test(c)));
  const src = readFileSync(fileURLToPath(new URL("../public/api.js", import.meta.url)), "utf8");
  assert.doesNotMatch(src, /method:\s*["'](POST|PUT|PATCH|DELETE)/i);
});

test("escaping: hostile strings cannot inject markup", () => {
  assert.equal(esc('<img src=x onerror=alert(1)>'), "&lt;img src=x onerror=alert(1)&gt;");
  const html = V.errorView({ code: "X", message: '<script>alert(1)</script>' }); assert.doesNotMatch(html, /<script>/);
  assert.doesNotMatch(V.decisionsPage({ runId: "r", data: { items: [], integrity: null, total: 0, limit: 50, offset: 0 }, params: { instrument_id: '"><script>' } }), /<script>/);
});

test("hash routing helpers are deterministic", () => {
  assert.equal(buildHash("/decisions", { run: "a b", page: "", tag: "HOLD" }), "#/decisions?run=a%20b&tag=HOLD");
  assert.deepEqual(parseHash("#/decision/d1?run=r1").segments, ["decision", "d1"]); assert.equal(parseHash("#/decision/d1?run=r1").params.run, "r1");
});

test("accessibility structure: landmarks, skip link, captions, scoped headers, labelled controls, aria-current", async () => {
  const { html } = await go("#/runs");
  assert.match(html, /class="skip"/); assert.match(html, /<main id="main" tabindex="-1">/); assert.match(html, /<nav aria-label="Primary">/);
  assert.match(html, /aria-current="page"/); assert.match(html, /<caption>/); assert.match(html, /<th scope="col">/); assert.match(html, /<label>Search/);
  assert.equal((html.match(/<h1/g) || []).length, 1);
  const dec = (await go(`#/decisions?run=${S.success}`)).html; assert.match(dec, /<label>Outcome tag/);
});

test("no inline styles/handlers or external URLs anywhere in shipped frontend (CSP-safe, no secrets)", () => {
  const dir = fileURLToPath(new URL("../public/", import.meta.url));
  for (const f of readdirSync(dir)) {
    const src = readFileSync(dir + f, "utf8");
    assert.doesNotMatch(src, /\son(click|change|submit|load)=/i, f); assert.doesNotMatch(src, /\sstyle="/i, f);
    assert.doesNotMatch(src.replace(/http:\/\/www\.w3\.org\/\d+\/svg/g, ""), /https?:\/\/(?!127\.0\.0\.1|localhost)/i, f);
    assert.doesNotMatch(src, /(api[_-]?key|secret|password|bearer)\s*[:=]\s*["'][^"']{6,}/i, f);
  }
});

test("responsive CSS has stacked-table rules at 768px and 420px and no fixed wide widths", () => {
  const css = readFileSync(fileURLToPath(new URL("../public/styles.css", import.meta.url)), "utf8");
  assert.match(css, /@media \(max-width:768px\)/); assert.match(css, /@media \(max-width:420px\)/); assert.match(css, /td::before\{content:attr\(data-label\)/);
  assert.match(css, /:focus-visible/); assert.doesNotMatch(css, /[^-]width:\s*[4-9]\d\dpx|[^-]width:\s*\d{4}px/);
});

test("fixtures contain no secrets and are labelled synthetic", () => {
  const raw = JSON.stringify(SNAP);
  assert.equal(META.synthetic, true); assert.doesNotMatch(raw, /(?:bearer\s+[A-Za-z0-9._-]{12,}|sk-[A-Za-z0-9]{12,}|BEGIN (?:RSA )?PRIVATE KEY)/i);
});
