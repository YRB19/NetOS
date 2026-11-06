// NetOS command centre: pure view functions (data) => HTML string. No DOM, no network, no timers, no randomness.
// Everything shown is derived from persisted artifacts returned by the read-only API. Where a fact is not recorded it
// is shown as Unknown / Unavailable / NOT CONNECTED, never as zero and never as invented activity.
import { esc, val, ts, badge, evidenceBadge, statusBadge, warnings, buildHash, unknown, toNum, num, fmtNum, dir } from "./format.js";
import { overviewDetail, factsHtml, STAGE_TITLE, short, link } from "./views.js";

// ------------------------------------------------------------------ stage model
/** The eight agent-workflow stages, clockwise from the top of the ring. `from` lists journal stages that evidence each one. */
export const AGENT_STAGES = [
  { key: "data", label: "DATA INGESTION", tag: "DATA", from: [] },
  { key: "context", label: "CONTEXT BUILDING", tag: "CONTEXT", from: ["snapshot"] },
  { key: "analysis", label: "INTELLIGENCE / ANALYSIS", tag: "ANALYSIS", from: ["candidate"] },
  { key: "proposal", label: "TRADE PROPOSAL", tag: "PROPOSAL", from: ["candidate"] },
  { key: "risk", label: "RISK VALIDATION", tag: "RISK", from: ["risk"] },
  { key: "allocation", label: "CAPITAL ALLOCATION", tag: "ALLOCATION", from: ["sizing"] },
  { key: "execution", label: "ORDER EXECUTION", tag: "EXECUTION", from: ["order_intent", "submission", "order_lifecycle", "fills"] },
  { key: "settlement", label: "PORTFOLIO SETTLEMENT", tag: "SETTLEMENT", from: ["portfolio_settlement", "reconciliation"] },
];
const REACHED = new Set(["RECORDED", "METADATA_ONLY", "DETERMINISTIC", "FAILED"]);
const STATUS_TEXT = { RECORDED: "RECORDED", METADATA_ONLY: "DATASET METADATA ONLY", DETERMINISTIC: "DETERMINISTIC ENGINE", NOT_RECORDED: "NOT RECORDED",
  NOT_CONNECTED: "NOT CONNECTED", UNAVAILABLE: "UNAVAILABLE", FAILED: "BLOCKED / FAILED" };

const jstage = (detail, name) => (detail && detail.stages ? detail.stages.find((s) => s.stage === name) : null);
const jevent = (detail, type) => (detail && detail.events ? detail.events.find((e) => e.event_type === type) : null);
const recorded = (detail, name) => { const s = jstage(detail, name); return !!s && s.status === "RECORDED"; };
const lastFact = (detail, name) => { const s = jstage(detail, name); return s && s.facts && s.facts.length ? s.facts[s.facts.length - 1] : null; };

/** Derive each stage's state from recorded facts only. Returns [{...stage, status, summary, rows:[[k,v]], raw:[journal stage names]}]. */
export function deriveStages({ ov, detail, order }) {
  const ds = ov.run.dataset || {};
  const out = [];
  const gone = !detail;
  const un = (extra = {}) => ({ status: "UNAVAILABLE", summary: "Decision detail could not be loaded, so this stage cannot be shown.", rows: [], ...extra });
  const nr = (why) => ({ status: "NOT_RECORDED", summary: why || "No event was recorded for this stage in the selected decision.", rows: [] });

  for (const st of AGENT_STAGES) {
    let r;
    if (st.key === "data") {
      r = ds.data_snapshot_version
        ? { status: "METADATA_ONLY", summary: "The run used a persisted dataset snapshot. No ingestion events (files received, validation passes) are persisted, so this is shown from dataset metadata only.",
            rows: [["Dataset snapshot", val(ds.data_snapshot_version, { code: true })], ["Window", `${ts(ds.window_start)} \u2192 ${ts(ds.window_end)}`], ["Evidence", evidenceBadge(ov.run.evidence)]] }
        : nr("The run records no dataset snapshot.");
    } else if (gone) {
      r = un();
    } else if (st.key === "context") {
      const ev = jevent(detail, "INPUT_SNAPSHOT_LINKED"); const snap = ev && ev.payload && ev.payload.snapshot;
      r = recorded(detail, "snapshot")
        ? { status: "RECORDED", summary: `Feature snapshot ${short((ev && ev.payload.snapshot_id) || "", 26)} was linked to this decision${snap && snap.incomplete ? " and is marked INCOMPLETE" : ""}.`,
            rows: [["Snapshot", val(ev && ev.payload.snapshot_id, { code: true })], ["Feature set", val(snap && snap.feature_set_version, { code: true })], ["Reference price", fmtNum(snap && snap.reference_price, { dp: 4 })],
              ["Incomplete", val(snap ? String(snap.incomplete) : null)], ["Missing fields", val(snap && (snap.missing_fields || []).length ? snap.missing_fields.join(", ") : "None recorded")]] }
        : nr();
    } else if (st.key === "analysis") {
      const c = lastFact(detail, "candidate");
      if (!c) r = nr("No candidate was generated, so no analysis result exists for this decision.");
      else if (c.model_version_id) r = { status: "RECORDED", summary: "An intelligence-provider model version is recorded against the candidate.", rows: [["Model version", val(c.model_version_id, { code: true })], ["Strategy", val(c.strategy_version_id, { code: true })]] };
      else r = { status: "DETERMINISTIC", summary: "The candidate was produced by a deterministic strategy engine. This is not an AI agent: no model or provider event is recorded.",
        rows: [["Strategy version", val(c.strategy_version_id, { code: true })], ["Model version", unknown("None (deterministic)")], ["Intelligence provider", unknown("NOT CONNECTED")]] };
    } else if (st.key === "proposal") {
      const c = lastFact(detail, "candidate");
      r = c ? { status: "RECORDED", summary: `Proposed action ${c.action}. The rationale below is the stored explanation, not model reasoning.`,
        rows: [["Action", val(c.action)], ["Rationale (as recorded)", val(c.rationale, { word: "Not recorded" })], ["Confidence", val(c.confidence, { word: "Not recorded" })],
          ["Size hint (a suggestion, not a quantity)", val(c.size_hint, { word: "Not recorded" })], ["Uncertainty band", val(c.uncertainty_band, { word: "Not recorded" })]] } : nr("No candidate trade was recorded.");
    } else if (st.key === "risk") {
      const f = lastFact(detail, "risk");
      if (!f) r = nr("No risk evaluation was recorded for this decision.");
      else {
        const checks = f.checks || []; const failed = checks.filter((c) => c.passed === false); const notEval = checks.filter((c) => c.evaluable === false);
        const ok = f.verdict === "APPROVE";
        r = { status: ok ? "RECORDED" : "FAILED", summary: ok ? `Risk validation passed: ${checks.length - failed.length} of ${checks.length} recorded checks passed.` : `Risk verdict ${f.verdict}: order blocked or resized. Failed: ${failed.map((c) => c.check_id).join(", ") || "see evidence"}.`,
          rows: [["Verdict", statusBadge(f.verdict)], ["Checks passed / recorded", `${checks.length - failed.length} / ${checks.length}`], ["Failed checks", val(failed.map((c) => c.check_id).join(", "), { word: "None" })],
            ["Not evaluable", val(notEval.map((c) => c.check_id).join(", "), { word: "None" })], ["Quantity ceiling", val(f.approved_qty_ceiling)], ["Risk rule version", val(f.risk_rule_version_id && short(f.risk_rule_version_id, 22), { code: true })]] };
      }
    } else if (st.key === "allocation") {
      const f = lastFact(detail, "sizing");
      r = f ? { status: "RECORDED", summary: f.outcome === "ORDER" ? `Sizing calculated ${f.side} ${f.quantity} (${f.reason}).` : `Sizing outcome ${f.outcome}: ${f.reason || "no quantity allocated"}.`,
        rows: [["Outcome", statusBadge(f.outcome)], ["Side", val(f.side)], ["Quantity", val(f.quantity)], ["Reference price", fmtNum(f.reference_price, { dp: 4 })], ["Risk ceiling", val(f.risk_quantity_ceiling)], ["Reason", val(f.reason)]] } : nr("No sizing result was recorded, so no capital was allocated.");
    } else if (st.key === "execution") {
      const fills = jstage(detail, "fills"); const sub = lastFact(detail, "submission"); const intent = lastFact(detail, "order_intent"); const life = jstage(detail, "order_lifecycle");
      const any = ["order_intent", "submission", "order_lifecycle", "fills"].some((n) => recorded(detail, n));
      if (!any) r = nr("No order was created or submitted for this decision.");
      else {
        const lastTo = life && life.facts && life.facts.length ? life.facts[life.facts.length - 1].to_state : null;
        const flags = (order && order.flags) || [];
        const nFills = fills && fills.facts ? fills.facts.length : 0;
        const bad = flags.includes("UNCERTAIN_SUBMISSION") || (sub && sub.outcome && !["ACCEPTED", "ACKNOWLEDGED"].includes(sub.outcome));
        r = { status: bad ? "FAILED" : "RECORDED",
          summary: nFills ? `Order reached ${lastTo || "a recorded state"} with ${nFills} fill(s) confirmed by the simulated broker.` : `Order ${lastTo || "submitted"}; no fill is recorded, so nothing is shown as executed.`,
          rows: [["Order intent", intent ? `${val(intent.side)} ${val(intent.quantity)} ${val(intent.order_type)}` : unknown("Not recorded")], ["Submission", sub ? statusBadge(sub.outcome || sub.submission_status) : unknown("Not recorded")],
            ["Last recorded order state", val(lastTo, { word: "None recorded" })], ["Fills recorded", esc(nFills)], ["Flags", flags.length ? flags.map((f) => badge(f, "bad")).join(" ") : "None"]] };
      }
    } else {
      const ps = lastFact(detail, "portfolio_settlement"); const rec = lastFact(detail, "reconciliation");
      r = ps ? { status: rec && rec.ok === false ? "FAILED" : "RECORDED", summary: rec ? (rec.ok ? "Settlement was applied and the later reconciliation result is consistent." : "Settlement was applied but reconciliation recorded a mismatch.") : "Settlement was applied; no reconciliation result is recorded after it.",
        rows: [["Cash after settlement", fmtNum(ps.cash)], ["Cumulative costs", fmtNum(ps.cumulative_costs)], ["Positions", val((ps.positions || []).map((p) => `${p.instrument_id}:${p.quantity}`).join(", "), { word: "None" })],
          ["Reconciliation", rec ? statusBadge(rec.ok ? "OK" : "BLOCKED") : unknown("Not recorded")]] } : nr("No portfolio settlement was recorded (no fill to settle).");
    }
    out.push({ ...st, ...r });
  }
  return out;
}

// --------------------------------------------------------------- ring (SVG)
const CX = 300, CY = 235, R = 150, NR = 23;
const pol = (r, deg) => [CX + r * Math.cos((deg * Math.PI) / 180), CY + r * Math.sin((deg * Math.PI) / 180)];
const f1 = (n) => n.toFixed(1);

function ring({ stages, hash, selected, hub }) {
  const ang = (i) => -90 + i * 45;
  const arcs = stages.map((s, i) => {
    const n = stages[(i + 1) % 8]; const loop = i === 7;
    const [x1, y1] = pol(R, ang(i) + 9), [x2, y2] = pol(R, ang(i) + 36);
    const on = !loop && REACHED.has(s.status) && REACHED.has(n.status);
    return `<path class="arc${on ? " arc-on" : ""}${loop ? " arc-loop" : ""}" pathLength="1" d="M${f1(x1)} ${f1(y1)} A${R} ${R} 0 0 1 ${f1(x2)} ${f1(y2)}"/>`;
  }).join("");
  const nodes = stages.map((s, i) => {
    const [x, y] = pol(R, ang(i)); const c = Math.cos((ang(i) * Math.PI) / 180), sn = Math.sin((ang(i) * Math.PI) / 180);
    const lx = x + c * (NR + 10), ly = y + sn * (NR + 14) + 4; const anchor = c > 0.3 ? "start" : c < -0.3 ? "end" : "middle";
    return `<a class="node node-${esc(s.status)}${s.key === selected ? " is-selected" : ""}" href="${esc(hash(s.key))}" data-stage="${esc(s.key)}" aria-label="Stage ${i + 1}, ${esc(s.label)}: ${esc(STATUS_TEXT[s.status])}"${s.key === selected ? ' aria-current="true"' : ""}>
<circle class="node-halo" cx="${f1(x)}" cy="${f1(y)}" r="${NR + 6}"/><circle class="node-disc" cx="${f1(x)}" cy="${f1(y)}" r="${NR}"/><text class="node-no" x="${f1(x)}" y="${f1(y + 5)}" text-anchor="middle">${i + 1}</text>
<text class="node-lbl" x="${f1(lx)}" y="${f1(ly)}" text-anchor="${anchor}">${esc(s.tag)}</text></a>`;
  }).join("");
  const ticks = Array.from({ length: 48 }, (_, i) => { const [a, b] = pol(112, i * 7.5), [c2, d] = pol(i % 6 === 0 ? 104 : 108, i * 7.5); return `M${f1(a)} ${f1(b)}L${f1(c2)} ${f1(d)}`; }).join("");
  const lines = hub.map((l, i) => `<text class="hub-t hub-t${i}" x="${CX}" y="${CY - 22 + i * 19}" text-anchor="middle">${esc(l)}</text>`).join("");
  return `<svg class="ring" viewBox="0 0 600 470" role="group" aria-label="Agent workflow: eight stages, clockwise from the top">
<circle class="ring-bg" cx="${CX}" cy="${CY}" r="${R}"/><circle class="ring-in" cx="${CX}" cy="${CY}" r="96"/><path class="ticks" d="${ticks}"/>${arcs}
<circle class="hub" cx="${CX}" cy="${CY}" r="84"/>${lines}${nodes}</svg>`;
}

// ------------------------------------------------------------ agent tiles
/** Seven architectural roles. These are roles, not running AI models: each tile reports only what the recorded artifacts show. */
export function agentTiles({ ov, orders, recon, detail }) {
  const r = ov.run, ps = r.pipeline_summary || null, hasJournal = !!ov.decisions;
  const cycles = r.metrics && r.metrics.decision_cycles;
  const cand = detail && recorded(detail, "candidate") ? lastFact(detail, "candidate") : null;
  const tiles = [
    { name: "Orchestrator", kind: "ROLE", status: cycles != null ? "DETERMINISTIC" : "NOT_RECORDED", line: cycles != null ? `Deterministic pipeline harness: ${cycles} decision cycle(s) recorded` : "No cycle count recorded", note: "No agent orchestrator runtime exists yet." },
    { name: "Data Reader", kind: "ROLE", status: r.dataset && r.dataset.data_snapshot_version ? "DETERMINISTIC" : "NOT_RECORDED", line: r.dataset && r.dataset.data_snapshot_version ? `Dataset snapshot ${short(r.dataset.data_snapshot_version, 14)} read` : "No dataset snapshot recorded", note: "Reads persisted bars; no live feed connected." },
    { name: "Researcher", kind: "ROLE", status: "NOT_CONNECTED", line: `No research agent. ${r.reports ? r.reports.length : 0} offline evaluation report(s) for this run`, note: "Web, filings and news research are not implemented." },
    { name: "Investment Analyst", kind: "ROLE", status: cand && cand.model_version_id ? "RECORDED" : hasJournal ? "DETERMINISTIC" : "NOT_RECORDED", line: hasJournal ? `Deterministic strategy ${short(r.strategy_version_id || "", 24)}; Claude provider NOT CONNECTED` : "No decision journal recorded", note: "Reserved for the future Claude-powered intelligence provider." },
    { name: "Deterministic Risk Engine", kind: "ROLE", status: ps ? (ps.risk_vetoes ? "FAILED" : "RECORDED") : "NOT_RECORDED", line: ps ? `${ps.risk_decisions} risk decision(s); ${ps.risk_vetoes} veto(es)` : "No pipeline risk summary recorded", note: "Hard veto authority; not an AI component." },
    { name: "Execution Adapter", kind: "ROLE", status: ps ? ((orders && orders.items || []).some((o) => (o.flags || []).includes("UNCERTAIN_SUBMISSION")) ? "FAILED" : "RECORDED") : "NOT_RECORDED", line: ps ? `Simulated broker ${val(r.versions.broker_config)}: ${ps.orders_submitted} submitted, ${ps.fills} fill(s)` : "No execution summary recorded", note: "No real broker is connected." },
    { name: "Portfolio Monitor", kind: "ROLE", status: ov.reconciliation ? (ov.reconciliation.blocked ? "FAILED" : "RECORDED") : "NOT_RECORDED", line: ov.reconciliation ? `${ov.reconciliation.total} reconciliation(s); ${ov.reconciliation.blocked} blocked` : "No reconciliation recorded", note: "Reads recorded settlement and reconciliation results." },
  ];
  return tiles;
}

const tileHtml = (t) => `<li class="tile tile-${esc(t.status)}"><span class="tile-dot" aria-hidden="true"></span><h3 class="tile-name">${esc(t.name)}</h3>
<p class="tile-status">${esc(STATUS_TEXT[t.status] || t.status)}</p><p class="tile-line">${esc(t.line)}</p><p class="tile-note">${esc(t.note)}</p></li>`;

// ------------------------------------------------------------ activity stream
const EVT = {
  DECISION_STARTED: ["AUDIT", "Decision cycle opened"], INPUT_SNAPSHOT_LINKED: ["DATA", "Snapshot linked"], CANDIDATE_EMITTED: ["SIGNAL", "Candidate generated"],
  RISK_EVALUATED: ["RISK", "Validation"], SIZING_EVALUATED: ["SIZING", "Quantity calculated"], ORDER_INTENT: ["EXECUTION", "Order intent recorded"],
  SUBMISSION_RESULT: ["EXECUTION", "Submission"], ORDER_TRANSITION: ["EXECUTION", "Order state change"], BROKER_EVENT: ["EXECUTION", "Broker event"],
  FILL_RECORDED: ["FILL", "Fill recorded"], PORTFOLIO_SETTLED: ["PORTFOLIO", "Settlement completed"], RECONCILIATION_RESULT: ["RECON", "Reconciliation"],
  DECISION_FINALIZED: ["AUDIT", "Decision finalized"],
};
export const CATEGORIES = ["DATA", "SIGNAL", "RISK", "SIZING", "EXECUTION", "FILL", "PORTFOLIO", "RECON", "AUDIT", "EVENT"];

/** Turn one persisted journal event into a labelled row. Unknown event types keep their raw name (no invented label). */
export function streamRow(e) {
  const p = e.payload || {}; const [cat, base] = EVT[e.event_type] || ["EVENT", e.event_type];
  let text = base, kind = "neutral", outcome = "";
  switch (e.event_type) {
    case "CANDIDATE_EMITTED": text = `${base}: ${p.action}`; outcome = p.confidence != null ? `confidence ${p.confidence}` : ""; break;
    case "RISK_EVALUATED": kind = p.verdict === "APPROVE" ? "ok" : "bad"; text = p.verdict === "APPROVE" ? "Validation passed" : p.verdict === "REJECT" ? "Order blocked" : `Verdict ${p.verdict}`;
      outcome = (p.checks || []).filter((c) => c.passed === false).map((c) => c.check_id).join(", ") || `${(p.checks || []).length} checks`; break;
    case "SIZING_EVALUATED": text = p.outcome === "ORDER" ? `${base}: ${p.side} ${p.quantity}` : `Sized as ${p.outcome}`; outcome = p.outcome; break;
    case "ORDER_INTENT": text = `${base}: ${p.side} ${p.quantity}`; break;
    case "SUBMISSION_RESULT": kind = p.outcome === "ACCEPTED" ? "ok" : "bad"; text = p.outcome === "ACCEPTED" ? "Submission acknowledged" : `Submission ${p.outcome}`; outcome = p.order_state || ""; break;
    case "ORDER_TRANSITION": text = `Order ${p.from_state} \u2192 ${p.to_state}`; outcome = p.detail || ""; break;
    case "BROKER_EVENT": text = `Broker ${p.kind}`; outcome = p.price != null ? `${p.quantity}@${p.price}` : ""; break;
    case "FILL_RECORDED": kind = "ok"; text = `${base}: ${p.quantity}@${p.price}`; outcome = p.charges && p.charges.total_cost != null ? `est. charges ${p.charges.total_cost}` : ""; break;
    case "PORTFOLIO_SETTLED": kind = "ok"; outcome = p.newly_applied === false ? "already applied" : ""; break;
    case "RECONCILIATION_RESULT": kind = p.ok ? "ok" : "bad"; text = p.ok ? "Reconciliation consistent" : "Reconciliation BLOCKED"; outcome = (p.mismatches || []).length ? `${p.mismatches.length} mismatch(es)` : ""; break;
    case "DECISION_FINALIZED": text = `${base}: ${p.terminal_state}`; break;
    default: break;
  }
  return { cat, text, kind, outcome, time: e.event_time || p.transition_at || e.recorded_at || null, timeIsEvent: !!(e.event_time || p.transition_at), seq: e.sequence, ref: e.event_id };
}

/** Fallback when decision detail is unavailable: chronological records derived from the order and reconciliation APIs. */
export function fallbackRows({ orders, recon }) {
  const rows = [];
  for (const o of (orders && orders.items) || []) {
    for (const h of o.state_history || []) rows.push({ cat: "EXECUTION", text: `Order ${h.from} \u2192 ${h.to}`, kind: "neutral", outcome: h.detail || "", time: h.at, timeIsEvent: true, seq: null, ref: o.order_id || o.order_key });
    for (const f of o.fills || []) rows.push({ cat: "FILL", text: `Fill recorded: ${f.quantity}@${f.price}`, kind: "ok", outcome: f.total_charges ? `est. charges ${f.total_charges}` : "", time: f.timestamp, timeIsEvent: true, seq: null, ref: f.fill_id });
  }
  for (const x of (recon && recon.items) || []) rows.push({ cat: "RECON", text: x.ok ? "Reconciliation consistent" : "Reconciliation BLOCKED", kind: x.ok ? "ok" : "bad", outcome: (x.mismatches || []).length ? `${x.mismatches.length} mismatch(es)` : "", time: x.event_time, timeIsEvent: true, seq: null, ref: x.event_id });
  return rows.sort((a, b) => String(a.time).localeCompare(String(b.time)));
}

const clock = (t) => (t ? String(t).replace("T", " ").replace("+00:00", "Z").replace(/:00Z$/, "Z") : null);

function stream({ rows, title, sourceNote }) {
  const chips = ["ALL", ...CATEGORIES.filter((c) => rows.some((r) => r.cat === c))].map((c, i) =>
    `<button type="button" class="chip-btn chip-${esc(c.toLowerCase())}" data-stream-filter="${esc(c)}" aria-pressed="${i === 0 ? "true" : "false"}">${esc(c)}</button>`).join("");
  const body = rows.length ? rows.map((r) => `<li class="ev ev-${esc(r.cat.toLowerCase())} ev-${esc(r.kind)}" data-cat="${esc(r.cat)}"><time class="ev-t"${r.time ? ` datetime="${esc(r.time)}"` : ""}${r.timeIsEvent ? "" : ' title="Journal write time (no event time recorded)"'}>${r.time ? esc(clock(r.time)) : unknown("n/a")}</time>
<span class="ev-c">${esc(r.cat)}</span><span class="ev-x">${esc(r.text)}</span><span class="ev-o">${esc(r.outcome || "")}</span><code class="ev-r" title="${esc(r.ref || "")}">${esc(short(r.ref || "", 14))}</code></li>`).join("")
    : `<li class="ev-empty">No events are recorded for the selected run. Nothing is generated to fill this panel.</li>`;
  return `<section class="panel term-panel" aria-labelledby="h-term"><header class="panel-h"><h3 id="h-term">ACTIVITY STREAM</h3><span class="panel-sub">${esc(title)}</span></header>
<div class="chips" role="group" aria-label="Filter events by category (display only)">${chips}</div>
<ol class="term" data-filter="ALL" aria-live="off" aria-label="Recorded events in chronological order">${body}</ol>
<p class="foot">${esc(sourceNote)} Rows are persisted events in recorded order; none are synthesised.</p></section>`;
}

// ------------------------------------------------------------ intake panel
function intake({ ov, detail }) {
  const r = ov.run, ds = r.dataset || {};
  const ev = jevent(detail, "INPUT_SNAPSHOT_LINKED"); const snap = ev && ev.payload && ev.payload.snapshot;
  const item = (status, name, type, ref, at, warn) => `<li class="in in-${esc(status)}"><span class="in-s">${esc(STATUS_TEXT[status] || status)}</span><span class="in-n">${esc(name)}</span><span class="in-t">${esc(type)}</span>
<span class="in-r">${ref ? `<code>${esc(ref)}</code>` : ""}</span><span class="in-a">${at ? ts(at) : ""}</span>${warn ? `<span class="in-w">${esc(warn)}</span>` : ""}</li>`;
  const grp = (title, items) => `<li class="ingrp"><h4>${esc(title)}</h4><ul class="inlist">${items.join("")}</ul></li>`;
  const feat = r.versions && r.versions.feature_set_version;
  return `<section class="panel intake" aria-labelledby="h-in"><header class="panel-h"><h3 id="h-in">INPUT / INTELLIGENCE INTAKE</h3><span class="panel-sub">what has entered the system</span></header>
<ul class="ingroups">
${grp("Market data", [ds.data_snapshot_version ? item("RECORDED", "Historical bars", "dataset snapshot", short(ds.data_snapshot_version, 18), ds.window_end, "") : item("NOT_RECORDED", "Historical bars", "dataset snapshot", "", null, ""),
    item("NOT_CONNECTED", "Live NSE market feed", "not implemented", "", null, "")])}
${grp("Company & financial information", [item("NOT_CONNECTED", "Filings / fundamentals", "not implemented", "", null, "")])}
${grp("Research documents", [item("NOT_CONNECTED", "Document intake & parsing", "not implemented", "", null, ""),
    item((r.reports || []).length ? "RECORDED" : "NOT_RECORDED", "Evaluation reports", "offline research harness", `${(r.reports || []).length} for this run`, null, "")])}
${grp("Feature snapshots", [feat ? item("RECORDED", "Feature set", "deterministic features", short(feat, 22), ev && ev.recorded_at, snap && snap.incomplete ? "Snapshot marked INCOMPLETE" + (snap.missing_fields && snap.missing_fields.length ? `: ${snap.missing_fields.join(", ")}` : "") : "")
    : item("NOT_RECORDED", "Feature set", "deterministic features", "", null, "")])}
${grp("Other sources", [item("NOT_CONNECTED", "News & web research", "not implemented", "", null, "")])}
</ul></section>`;
}

// ------------------------------------------------------------ portfolio workspace
const compact = (n) => new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(n);
const day = (t) => String(t).slice(0, 10);

function equityChart(points, fills) {
  const pts = points.map((p) => ({ t: Date.parse(p.timestamp), y: toNum(p.equity), ts: p.timestamp })).filter((p) => Number.isFinite(p.t) && p.y !== null);
  if (pts.length < 2) return `<p class="empty" role="status">Not enough recorded equity points to chart.</p>`;
  const W = 640, H = 230, L = 54, Rr = 14, T = 14, B = 24;
  const lo0 = Math.min(...pts.map((p) => p.y)), hi0 = Math.max(...pts.map((p) => p.y)), pad = (hi0 - lo0 || Math.abs(hi0) || 1) * 0.08, lo = lo0 - pad, hi = hi0 + pad;
  const t0 = pts[0].t, t1 = pts[pts.length - 1].t, X = (t) => L + ((t - t0) / (t1 - t0 || 1)) * (W - L - Rr), Y = (y) => T + (1 - (y - lo) / (hi - lo)) * (H - T - B);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${f1(X(p.t))} ${f1(Y(p.y))}`).join("");
  const area = `${line}L${f1(X(t1))} ${H - B}L${f1(X(t0))} ${H - B}Z`;
  const trend = dir(pts[pts.length - 1].y - pts[0].y) || "flat";
  const grid = [0, 1, 2, 3].map((i) => { const y = lo + ((hi - lo) * i) / 3; return `<path class="grid" d="M${L} ${f1(Y(y))}H${W - Rr}"/><text class="axis" x="${L - 6}" y="${f1(Y(y) + 3)}" text-anchor="end">${esc(compact(y))}</text>`; }).join("");
  const nearest = (t) => pts.reduce((a, b) => (Math.abs(b.t - t) < Math.abs(a.t - t) ? b : a));
  const marks = (fills || []).map((f) => { const t = Date.parse(f.timestamp); if (!Number.isFinite(t) || t < t0 || t > t1) return ""; const n = nearest(t), x = X(t), y = Y(n.y), buy = f.side !== "SELL";
    return `<path class="mk ${buy ? "mk-buy" : "mk-sell"}" d="${buy ? `M${f1(x)} ${f1(y - 9)}l5 8h-10z` : `M${f1(x)} ${f1(y + 9)}l5 -8h-10z`}"><title>${esc(`${f.side || "FILL"} ${f.quantity}@${f.price} ${f.instrument_id || ""}`)}</title></path>`; }).join("");
  const last = pts[pts.length - 1];
  return `<svg class="chart chart-${trend}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Equity curve from ${pts.length} recorded points, ${esc(day(pts[0].ts))} to ${esc(day(last.ts))}, range ${esc(compact(lo0))} to ${esc(compact(hi0))}. Fill markers are recorded fills.">
<defs><linearGradient id="eqg" x1="0" y1="0" x2="0" y2="1"><stop class="eqg-a" offset="0"/><stop class="eqg-b" offset="1"/></linearGradient></defs>${grid}
<path class="area" d="${area}" fill="url(#eqg)"/><path class="eq-line" pathLength="1" d="${line}"/>${marks}<circle class="eq-dot" cx="${f1(X(last.t))}" cy="${f1(Y(last.y))}" r="3.5"/>
<text class="axis" x="${L}" y="${H - 6}">${esc(day(pts[0].ts))}</text><text class="axis" x="${W - Rr}" y="${H - 6}" text-anchor="end">${esc(day(last.ts))}</text></svg>`;
}

function drawdownStrip(points) {
  const d = points.map((p) => ({ t: Date.parse(p.timestamp), v: toNum(p.drawdown) })).filter((p) => Number.isFinite(p.t) && p.v !== null);
  if (d.length < 2) return `<p class="empty">Drawdown series unavailable.</p>`;
  const mx = Math.max(...d.map((p) => p.v)); const W = 640, H = 46;
  if (mx <= 0) return `<p class="note dd-flat">Recorded drawdown is 0 at every point on this curve.</p>`;
  const t0 = d[0].t, t1 = d[d.length - 1].t, X = (t) => ((t - t0) / (t1 - t0 || 1)) * W, Y = (v) => 4 + (v / mx) * (H - 8);
  const path = d.map((p, i) => `${i ? "L" : "M"}${f1(X(p.t))} ${f1(Y(p.v))}`).join("");
  return `<svg class="ddchart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Drawdown from recorded points, deepest ${esc((mx * 100).toFixed(2))} percent"><path class="dd-area" d="${path}L${W} 2L0 2Z"/><path class="dd-line" d="${path}"/></svg>`;
}

/** Horizontal stacked bar drawn with SVG attributes (no inline styles). parts: [{v, cls, label}] */
function barSvg(parts, aria) {
  const tot = parts.reduce((a, x) => a + x.v, 0); let x = 0;
  const rects = parts.map((p) => { const w = (p.v / tot) * 100; const r = `<rect class="${p.cls}" x="${f1(x)}" y="0" width="${f1(w)}" height="8"><title>${esc(p.label)}</title></rect>`; x += w; return r; }).join("");
  return `<svg class="bar" viewBox="0 0 100 8" preserveAspectRatio="none" role="img" aria-label="${esc(aria)}">${rects}</svg>`;
}
const pctTxt = (v) => { const n = toNum(v); return n === null ? null : `${(n * 100).toFixed(2)}%`; };

function portfolio({ ov, orders }) {
  const r = ov.run, eq = ov.equity, last = eq.last || {}, m = r.metrics || {}, pts = eq.points || [];
  const positions = last.positions || [];
  const costBasis = positions.reduce((a, p) => (a === null ? null : toNum(p.quantity) === null || toNum(p.avg_cost) === null ? null : a + toNum(p.quantity) * toNum(p.avg_cost)), 0);
  const ddNow = pts.length ? toNum(pts[pts.length - 1].drawdown) : null, ddMax = pts.length ? Math.max(...pts.map((p) => toNum(p.drawdown)).filter((x) => x !== null)) : null;
  const fills = ((orders && orders.items) || []).flatMap((o) => (o.fills || []).map((f) => ({ ...f, side: o.side, instrument_id: o.instrument_id })));
  const tile = (label, valueHtml, { d = null, sub = "", big = false } = {}) => `<div class="pk${big ? " pk-big" : ""}${d ? ` pk-${d}` : ""}"><dt>${esc(label)}</dt><dd>${valueHtml}</dd>${sub ? `<small>${esc(sub)}</small>` : ""}</div>`;
  const pnlCell = (v, label, sub) => tile(label, fmtNum(v), { d: dir(v), sub });
  const unavailable = `<p class="empty" role="status">Unavailable: ${esc(eq.reason || "no equity curve recorded for this run")}</p>`;
  const kpis = eq.available ? `<dl class="pks">${tile("EQUITY", fmtNum(last.equity), { big: true, sub: `as of ${last.timestamp ? String(last.timestamp).slice(0, 10) : "unknown"}` })}${tile("AVAILABLE CASH", fmtNum(last.cash))}${tile("MARKET VALUE", fmtNum(last.market_value))}
${tile("INVESTED (COST BASIS)", costBasis === null ? unknown("Unavailable") : esc(num(costBasis)), { sub: "derived: qty \u00d7 avg cost" })}${tile("ACTIVE POSITIONS", esc(positions.length))}
${pnlCell(m.realized_pnl_gross, "REALISED P&L (GROSS)", "")}${pnlCell(m.unrealized_pnl_gross, "UNREALISED P&L (GROSS)", "mark-to-market")}${pnlCell(m.net_pnl, "NET P&L", "after estimated costs")}
${tile("TRANSACTION COSTS", fmtNum(last.cumulative_costs ?? m.total_transaction_costs), { sub: "simulated-schedule estimate" })}
${tile("DRAWDOWN NOW / MAX", ddNow === null ? unknown("Unavailable") : esc(`${pctTxt(ddNow)} / ${pctTxt(ddMax)}`), { sub: "from recorded equity curve" })}</dl>` : unavailable;

  const cash = toNum(last.cash); const slices = positions.map((p) => ({ k: p.instrument_id, v: toNum(p.quantity) !== null && toNum(p.avg_cost) !== null ? toNum(p.quantity) * toNum(p.avg_cost) : null })).filter((s) => s.v !== null);
  if (cash !== null) slices.push({ k: "CASH", v: cash });
  const tot = slices.reduce((a, s) => a + s.v, 0);
  const alloc = eq.available && tot > 0 ? `${barSvg(slices.map((x, i) => ({ v: x.v, cls: `al al${i % 6}`, label: `${x.k} ${((x.v / tot) * 100).toFixed(1)}%` })), "Allocation by cost basis plus cash")}
<ul class="alloc-key">${slices.map((x, i) => `<li><i class="sw al${i % 6}"></i><code>${esc(short(x.k, 16))}</code> ${esc(((x.v / tot) * 100).toFixed(1))}%</li>`).join("")}</ul><p class="foot">Allocation = cost basis of open positions plus cash, as recorded. Not a market-value weighting.</p>` : `<p class="empty">Allocation unavailable.</p>`;

  const posTable = positions.length ? `<table class="compact"><caption>Open positions (last recorded point)</caption><thead><tr><th scope="col">Instrument</th><th scope="col">Qty</th><th scope="col">Avg cost</th><th scope="col">Cost basis</th></tr></thead><tbody>${positions.map((p) => `<tr><td data-label="Instrument"><code>${esc(p.instrument_id)}</code></td><td data-label="Qty">${esc(p.quantity)}</td><td data-label="Avg cost">${fmtNum(p.avg_cost, { dp: 4 })}</td><td data-label="Cost basis">${toNum(p.quantity) !== null && toNum(p.avg_cost) !== null ? esc(num(toNum(p.quantity) * toNum(p.avg_cost))) : unknown("Unavailable")}</td></tr>`).join("")}</tbody></table>` : `<p class="empty" role="status">No open positions recorded at the last equity point.</p>`;
  const sorted = [...fills].sort((a, b) => String(b.timestamp).localeCompare(String(a.timestamp))).slice(0, 8);
  const tx = sorted.length ? `<table class="compact"><caption>Transaction history (latest ${sorted.length} of ${fills.length} recorded fills)</caption><thead><tr><th scope="col">Time</th><th scope="col">Side</th><th scope="col">Instrument</th><th scope="col">Qty @ price</th><th scope="col">Est. charges</th></tr></thead><tbody>${sorted.map((f) => `<tr><td data-label="Time">${ts(f.timestamp)}</td><td data-label="Side">${statusBadge(f.side)}</td><td data-label="Instrument"><code>${esc(f.instrument_id)}</code></td><td data-label="Qty @ price">${esc(f.quantity)} @ ${esc(f.price)}</td><td data-label="Est. charges">${f.total_charges ? esc(f.total_charges) : unknown("Not recorded")}</td></tr>`).join("")}</tbody></table>` : `<p class="empty" role="status">${orders ? "No fills are recorded for this run." : "Fills are unavailable (orders could not be loaded)."}</p>`;

  return `<section class="panel capital" aria-labelledby="h-cap"><header class="panel-h"><h3 id="h-cap">CAPITAL / PORTFOLIO</h3><span class="panel-sub">${r.evidence && r.evidence.synthetic ? '<span class="syn-tag">SYNTHETIC VALUES</span> ' : ""}recorded values; currency not recorded</span></header>
${kpis}
<div class="chartbox"><h4>Equity curve <small>recorded points; triangles are recorded fills</small></h4>${eq.available ? equityChart(pts, fills) : unavailable}
<h4>Drawdown <small>from recorded points</small></h4>${eq.available ? drawdownStrip(pts) : ""}
<p class="foot">Per-instrument price series are not persisted, so no instrument charts are shown. Benchmark comparison: ${unknown("Unavailable")}.</p></div>
<h4>Capital allocation</h4>${alloc}${posTable}${tx}</section>`;
}

// ------------------------------------------------------------ agent core
function agentCore({ ov, stages, selected, detail, order, runId, decisionId, switcher }) {
  const sel = stages.find((s) => s.key === selected) || stages[0];
  const hash = (k) => buildHash("/", { run: runId, decision: decisionId, stage: k });
  const cand = lastFact(detail, "candidate"), risk = lastFact(detail, "risk"), siz = lastFact(detail, "sizing"), dr = detail && detail.decision_record;
  const lastReached = [...stages].reverse().find((s) => REACHED.has(s.status));
  const hub = detail ? [detail.terminal_state ? "REPLAY" : "REPLAY \u00b7 OPEN", short((dr && dr.instrument_id) || "", 14), (cand && cand.action) || "NO CANDIDATE", detail.terminal_state || "NOT FINALIZED"] : ["RECORDED REPLAY", "no decision", "loaded", ""];
  const panels = stages.map((s) => {
    const raw = s.from.filter((n) => recorded(detail, n)).map((n) => { const st = jstage(detail, n); return `<details><summary>${esc(STAGE_TITLE[n] || n)} <small>raw recorded facts</small></summary>${st.facts.map((f) => factsHtml(f)).join("")}</details>`; }).join("");
    return `<section class="spanel spanel-${esc(s.status)}" data-stage-panel="${esc(s.key)}"${s.key === sel.key ? "" : " hidden"} aria-labelledby="sp-${esc(s.key)}">
<h4 id="sp-${esc(s.key)}">${STAGES_NO(s)} ${esc(s.label)} <span class="st st-${esc(s.status)}">${esc(STATUS_TEXT[s.status])}</span></h4><p>${esc(s.summary)}</p>${s.rows.length ? `<dl class="kv kv-tight">${s.rows.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join("")}</dl>` : ""}${raw}</section>`;
  }).join("");
  const legend = stages.map((s, i) => `<li><a class="lg lg-${esc(s.status)}${s.key === sel.key ? " is-selected" : ""}" href="${esc(hash(s.key))}" data-stage="${esc(s.key)}"><b>${i + 1}</b> ${esc(s.label)}<span>${esc(STATUS_TEXT[s.status])}</span></a></li>`).join("");
  const detailKv = detail ? `<dl class="kv kv-tight">${[
    ["Instrument", val(dr && dr.instrument_id)], ["Proposed action", val(cand && cand.action, { word: "No candidate" })], ["Recorded rationale", val(cand && cand.rationale, { word: "Not recorded" })],
    ["Input references", `${val(dr && dr.input_snapshot_id, { code: true })} ${val(detail.versions && detail.versions.data_snapshot_version, { code: true })}`], ["Confidence (only if recorded)", val(cand && cand.confidence, { word: "Not recorded" })],
    ["Risk outcome", risk ? statusBadge(risk.verdict) : unknown("Not evaluated")], ["Sized quantity", siz ? val(siz.quantity) : unknown("Not sized")], ["Order status", val(order && order.last_known_state, { word: "No order" })],
    ["Fill status", order ? val(order.filled_quantity, { word: "No fills" }) : unknown("No order")], ["Settlement", recorded(detail, "portfolio_settlement") ? badge("RECORDED", "ok") : unknown("Not recorded")]].map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join("")}</dl>` : `<p class="empty" role="status">No decision detail is loaded for this view.</p>`;
  const future = ["Files received", "Documents parsed", "Data validation results", "Research tasks", "Model / provider activity", "Tool invocations", "Candidate investment theses", "Proposed allocation (agent)", "Broker acknowledgement (real broker)"];
  return `<section class="panel core" aria-labelledby="h-core"><header class="panel-h"><h3 id="h-core">THE AGENT CORE</h3><span class="panel-sub">recorded replay \u00b7 deterministic strategy engine, not an AI agent</span></header>
<div class="core-grid"><div class="ring-wrap">${ring({ stages, hash, selected: sel.key, hub })}<p class="ring-cap">${lastReached ? `Last recorded stage: <strong>${esc(lastReached.label)}</strong>` : "No stage is recorded for this selection."}</p></div>
<div class="core-side"><ol class="legend">${legend}</ol></div></div>
<div class="spanels" aria-live="polite">${panels}</div>
<h4>Decision detail</h4>${detailKv}
${detail ? `<p>${link(buildHash("/decision/" + detail.decision_id, { run: runId }), "Open full decision timeline")}</p>` : ""}
${switcher}
<details class="future"><summary>Future runtime telemetry <small>not connected</small></summary><p class="note">A future agent runtime will report these as explicit structured events. Until then nothing below is available, and none of it is inferred from animation.</p>
<ul class="futlist"><li><span class="st st-NOT_CONNECTED">INTELLIGENCE PROVIDER: NOT CONNECTED</span></li>${future.map((f) => `<li>${esc(f)} <span class="st st-NOT_CONNECTED">NOT CONNECTED</span></li>`).join("")}</ul></details></section>`;
}
const STAGES_NO = (s) => `<span class="sno">${AGENT_STAGES.findIndex((x) => x.key === s.key) + 1}</span>`;

// ------------------------------------------------------------ session summary
function summary({ ov, orders, recon, rows }) {
  const r = ov.run, d = ov.decisions, integ = ov.integrity || {};
  const total = d ? d.total : null, incomplete = integ.incomplete_decisions ?? null, done = total !== null && incomplete !== null ? total - incomplete : null;
  const frac = total ? done / total : null; const C = 2 * Math.PI * 38;
  const gauge = frac === null ? "" : `<svg class="gauge" viewBox="0 0 100 100" role="img" aria-label="${esc(done)} of ${esc(total)} decisions finalized"><circle class="g-bg" cx="50" cy="50" r="38"/><circle class="g-fg${incomplete ? " g-warn" : ""}" cx="50" cy="50" r="38" pathLength="1" stroke-dasharray="${frac.toFixed(4)} 1"/><text x="50" y="49" text-anchor="middle" class="g-n">${esc(done)}</text><text x="50" y="63" text-anchor="middle" class="g-l">of ${esc(total)}</text></svg>`;
  const terms = d ? Object.entries(d.by_terminal_state) : [];
  const bar = terms.length && total ? `${barSvg(terms.map(([k, v], i) => ({ v, cls: `al al${i % 6}`, label: `${k} ${v}` })), "Decisions by terminal state")}<ul class="alloc-key">${terms.map(([k, v], i) => `<li><i class="sw al${i % 6}"></i>${esc(k)} ${esc(v)}</li>`).join("")}</ul>` : "";
  const cats = CATEGORIES.map((c) => [c, rows.filter((x) => x.cat === c).length]).filter(([, n]) => n);
  const errs = [...(integ.errors || []).map((e) => String(e.code || e)), ...(incomplete ? [`${incomplete} incomplete decision(s)`] : []), ...(ov.reconciliation && ov.reconciliation.blocked ? [`${ov.reconciliation.blocked} blocked reconciliation(s)`] : []), ...(ov.orders && ov.orders.flagged ? [`${ov.orders.flagged} flagged order(s)`] : [])];
  const verdict = !d ? badge("NO JOURNAL RECORDED", "warn") : errs.length ? badge("REPLAY COMPLETE WITH ERRORS", "bad") : integ.status === "VERIFIED" ? badge("REPLAY COMPLETE \u2014 JOURNAL VERIFIED", "ok") : badge(`JOURNAL ${integ.status || "UNKNOWN"}`, "warn");
  return `<section class="panel summary" aria-labelledby="h-sum"><header class="panel-h"><h3 id="h-sum">SESSION SUMMARY</h3><span class="panel-sub">recorded replay of ${esc(short(r.run_id, 26))}; not a live session</span></header>
<div class="sum-grid"><div class="sum-gauge">${gauge}<p>${verdict}</p></div>
<div><h4>Work recorded</h4><ul class="sumlist"><li>Decisions finalized: ${d ? esc(done ?? "Unknown") + " of " + esc(total) : unknown()}</li><li>Orders: ${ov.orders ? esc(ov.orders.total) : unknown("Unavailable")}${r.pipeline_summary ? `; fills ${esc(r.pipeline_summary.fills)}` : ""}</li><li>Reconciliations: ${ov.reconciliation ? esc(ov.reconciliation.total) + ", blocked " + esc(ov.reconciliation.blocked) : unknown("Unavailable")}</li><li>Journal events: ${val(integ.event_count)}</li></ul>${bar}</div>
<div><h4>Warnings <small>${esc((r.warnings || []).length)}</small></h4>${(r.warnings || []).length ? warnings(r.warnings) : `<p class="empty">None recorded.</p>`}<h4>Errors <small>${esc(errs.length)}</small></h4>${errs.length ? `<ul class="errlist">${errs.map((e) => `<li>${badge(e, "bad")}</li>`).join("")}</ul>` : `<p class="empty">None recorded.</p>`}</div>
<div><h4>Event categories <small>in the displayed chain</small></h4>${cats.length ? `<ul class="catlist">${cats.map(([c, n]) => `<li class="cat cat-${esc(c.toLowerCase())}"><span>${esc(c)}</span><b>${esc(n)}</b></li>`).join("")}</ul>` : `<p class="empty">No events displayed.</p>`}</div></div>
<p class="foot">Evidence class: ${evidenceBadge(r.evidence)} \u00b7 Run-wide events: ${val(integ.event_count)}. Completion of a replay is not evidence of profitability, broker compatibility or live readiness.</p></section>`;
}

// ------------------------------------------------------------ page
export function envChips({ ov, detail }) {
  const r = ov.run, ev = r.evidence || {}; const c = (t, k, title = "") => `<li class="chip chip-${esc(k)}"${title ? ` title="${esc(title)}"` : ""}>${esc(t)}</li>`;
  const out = [];
  out.push(ev.synthetic ? c("SYNTHETIC ENVIRONMENT", "syn", ev.label || "") : c(`EVIDENCE: ${(ev.label || "UNKNOWN").toUpperCase()}`, ev.label ? "dim" : "warn"));
  if (r.run_type === "SIMULATION_PIPELINE") out.push(c("SIMULATION", "cyan", "Simulated broker; no real orders"));
  else if (r.run_type) out.push(c(String(r.run_type).replace(/_/g, " "), "dim"));
  if (r.versions && r.versions.broker_config) out.push(c("BROKER: " + r.versions.broker_config, "dim", "Execution adapter configuration label recorded for the run"));
  const prov = detail && jstage(detail, "candidate") && lastFact(detail, "candidate") && lastFact(detail, "candidate").model_version_id;
  if (prov) out.push(c("MODEL RECORDED", "violet", String(prov)));
  return out.join("");
}

function kpis({ ov, orders, recon, tiles }) {
  const r = ov.run, ps = r.pipeline_summary || {}, integ = ov.integrity || {}, d = ov.decisions;
  const errCount = (integ.errors || []).length + (integ.incomplete_decisions || 0) + (ov.reconciliation ? ov.reconciliation.blocked : 0) + (ov.orders ? ov.orders.flagged : 0);
  const active = tiles.filter((t) => REACHED.has(t.status)).length;
  const k = (label, v, cls = "", sub = "") => `<li class="kpi ${cls}"><span class="kpi-l">${esc(label)}</span><strong class="kpi-v">${v}</strong>${sub ? `<small>${esc(sub)}</small>` : ""}</li>`;
  const U = unknown("Unavailable");
  return `<ul class="kpis" aria-label="Recorded operation counts">${k("DECISIONS", d ? esc(d.total) : U, "", "in journal")}${k("ORDERS", ov.orders ? esc(ov.orders.total) : U)}${k("FILLS", ps.fills != null ? esc(ps.fills) : U)}${k("RISK VETOES", ps.risk_vetoes != null ? esc(ps.risk_vetoes) : U, ps.risk_vetoes ? "kpi-warn" : "")}
${k("JOURNAL EVENTS", integ.event_count != null ? esc(integ.event_count) : U)}${k("WARNINGS", esc((r.warnings || []).length), (r.warnings || []).length ? "kpi-warn" : "")}${k("ERRORS", d || ov.reconciliation ? esc(errCount) : U, errCount ? "kpi-bad" : "", "integrity, incomplete, blocked")}${k("ROLES WITH RECORDS", `${esc(active)}/7`, "kpi-violet", "recorded activity, not live")}</ul>`;
}

/** Build the whole command-centre page body. All inputs come from the read-only API; auxiliary inputs may be null. */
/** Slice 11: read-only AI research-signal status. Shows only recorded facts; never an animated "thinking" state. */
export function aiPanel(ai) {
  if (!ai) return `<section class="panel ai-panel" aria-label="AI research signal"><h3>AI research signal <small class="badge">RESEARCH SIGNAL ONLY</small></h3><p class="state">Unavailable: the AI signal summary could not be read.</p></section>`;
  if (!ai.ai_used) return `<section class="panel ai-panel" aria-label="AI research signal"><h3>AI research signal <small class="badge">RESEARCH SIGNAL ONLY</small></h3><p><strong>${esc(ai.run_label)}</strong> \u00b7 provider ${esc(ai.provider)} \u00b7 disclosure source ${esc(ai.disclosure_source)}.</p><p class="state">${esc(ai.reason || "No AI signal was recorded for this run.")}</p></section>`;
  const sc = Object.entries(ai.status_counts || {}).map(([k, n]) => `<li>${esc(k)}: <strong>${esc(n)}</strong></li>`).join("");
  const tok = ai.tokens ? `${esc(ai.tokens.input)} in / ${esc(ai.tokens.output)} out` : "not reported";
  const cost = ai.estimated_cost_usd === null || ai.estimated_cost_usd === undefined ? "not computed (no verified pricing configured)" : `USD ${esc(ai.estimated_cost_usd)}`;
  const rows = (ai.rows || []).slice(0, 12).map((r) => `<tr><td><code>${esc(short(r.instrument_id || "", 18))}</code></td><td>${esc(r.provider_status)}</td><td>${esc(r.sentiment || "\u2014")}</td><td>${esc(r.materiality || "\u2014")}</td><td>${r.applied ? `${esc(r.original_confidence)} \u2192 ${esc(r.adjusted_confidence)}` : esc(r.outcome_reason || "no change")}</td></tr>`).join("");
  return `<section class="panel ai-panel" aria-label="AI research signal"><h3>AI research signal <small class="badge">RESEARCH SIGNAL ONLY</small></h3>
<p><strong>${esc(ai.run_label)}</strong> \u00b7 provider: ${esc(ai.provider)} \u00b7 models: ${esc((ai.models || []).join(", ") || "\u2014")}</p>
<p>Model version ${esc((ai.model_versions || []).join(", ") || "\u2014")} \u00b7 prompt ${esc((ai.prompt_hashes || []).map((h) => short(h, 10)).join(", ") || "\u2014")} \u00b7 schema ${esc((ai.output_schema_versions || []).join(", ") || "\u2014")}</p>
<p>${esc(ai.events)} signal events \u00b7 ${esc(ai.adjusted_confidence_events)} confidence adjustments \u00b7 ${esc(ai.no_signal_or_unknown)} no-signal/unknown/failed \u00b7 tokens ${tok} \u00b7 cost ${cost}</p>
<ul class="chips">${sc}</ul>
<table class="grid"><thead><tr><th>Instrument</th><th>Status</th><th>Sentiment</th><th>Materiality</th><th>Confidence</th></tr></thead><tbody>${rows}</tbody></table>
<p class="state">The AI may adjust only the confidence field. It cannot change BUY/SELL/HOLD, size, risk or orders.</p></section>`;
}

export function commandCentre({ ov, runs, health, aux = {}, selectedStage = null }) {
  const { orders = null, recon = null, ai = null, detail = null, decisionId = null, runId = ov.run.run_id } = aux;
  const order = orders && decisionId ? (orders.items || []).find((o) => (o.decision_ids || []).includes(decisionId)) || null : null;
  const stages = deriveStages({ ov, detail, order });
  const reached = [...stages].reverse().find((s) => REACHED.has(s.status));
  const selected = (selectedStage && stages.some((s) => s.key === selectedStage) ? selectedStage : reached ? reached.key : "data");
  const tiles = agentTiles({ ov, orders, recon, detail });
  const rows = detail && detail.events ? detail.events.map(streamRow).sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0)) : fallbackRows({ orders, recon });
  const picker = `<label for="run-select-cc">Run</label> <select id="run-select-cc" data-run-select>${runs.map((x) => `<option value="${esc(x.run_id)}"${x.run_id === runId ? " selected" : ""}>${esc(short(x.run_id, 26))} \u2014 ${esc(x.status)}</option>`).join("")}</select>`;
  const cands = [...((orders && orders.items) || []).flatMap((o) => o.decision_ids || []).slice(0, 6), ...((ov.decisions && ov.decisions.recent) || []).map((x) => x.decision_id).slice(0, 6)];
  const uniq = [...new Set(cands)];
  const switcher = uniq.length ? `<h4>Replay another recorded decision</h4><ul class="dchips">${uniq.map((id) => `<li><a class="dchip${id === decisionId ? " is-selected" : ""}" href="${esc(buildHash("/", { run: runId, decision: id }))}"${id === decisionId ? ' aria-current="true"' : ""}><code>${esc(short(id, 18))}</code></a></li>`).join("")}</ul>` : "";
  const title = detail ? `decision ${short(detail.decision_id, 22)} \u00b7 recorded replay` : "recorded replay \u00b7 order and reconciliation records";
  const note = detail ? "Source: the selected decision's persisted journal events." : "Decision detail was not available; showing order and reconciliation records instead.";
  return `<h2 class="cc-title">Command centre <small>${picker}</small></h2>${ov.integrity && ov.integrity.status !== "VERIFIED" ? `<div class="banner banner-bad" role="alert"><strong>Journal ${esc(ov.integrity.status)}.</strong> ${esc(ov.integrity.warning || ov.integrity.reason || "Integrity could not be established.")}</div>` : ""}
${kpis({ ov, orders, recon, tiles })}
<ul class="tiles" aria-label="Agent roles (architectural roles, not running AI models)">${tiles.map(tileHtml).join("")}</ul>
<div class="cc-grid"><div class="cc-left">${intake({ ov, detail })}${stream({ rows, title, sourceNote: note })}</div>
<div class="cc-right">${agentCore({ ov, stages, selected, detail, order, runId, decisionId, switcher })}${portfolio({ ov, orders })}</div></div>
${summary({ ov, orders, recon, rows })}
${aiPanel(ai)}
<details class="panel legacy"><summary>Full run overview, versions and provenance <small>unchanged read-only detail</small></summary>${overviewDetail({ ov })}</details>`;
}

/** Choose which decision to replay: explicit request, else the latest order's decision, else the latest recorded decision. */
export function pickDecision({ ov, orders, requested }) {
  if (requested) return requested;
  const items = (orders && orders.items) || [];
  const stamp = (o) => [...(o.state_history || []).map((h) => h.at), ...(o.fills || []).map((f) => f.timestamp)].filter(Boolean).sort().pop() || "";
  const withDecision = items.filter((o) => (o.decision_ids || []).length).sort((a, b) => stamp(b).localeCompare(stamp(a)));
  if (withDecision.length) return withDecision[0].decision_ids[0];
  const recent = (ov.decisions && ov.decisions.recent) || [];
  const withRisk = recent.filter((d) => d.risk_verdict);
  return (withRisk.length ? withRisk : recent).map((d) => d.decision_id).slice(-1)[0] || null;
}
