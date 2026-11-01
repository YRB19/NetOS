// Pure view functions: (data) => HTML string. Every dynamic value is escaped. No network, no DOM.
import { esc, val, ts, badge, evidenceBadge, statusBadge, warnings, table, kv, buildHash, unknown } from "./format.js";

export const link = (hash, text) => `<a href="${esc(hash)}">${esc(text)}</a>`;
const runLink = (id) => link(buildHash("/run/" + encodeURIComponent(id)), id);
export const short = (s, n = 18) => (s && s.length > n ? s.slice(0, n) + "\u2026" : s);

export const NAV = [
  ["/", "COMMAND CENTRE", ["/"]],
  ["/runs", "RUNS & EXPERIMENTS", ["/runs", "/run"]],
  ["/decisions", "DECISION HISTORY", ["/decisions", "/decision"]],
  ["/risk", "RISK & EXECUTION", ["/risk", "/orders"]],
  ["/research", "RESEARCH", ["/research", "/report"]],
  ["/health", "SYSTEM / AUDIT", ["/health"]],
];
const SUBNAV = { "RISK & EXECUTION": [["/risk", "Risk & safety"], ["/orders", "Orders & reconciliation"]] };
const NEEDS_RUN = ["/decisions", "/risk", "/orders", "/health", "/"];

const chip = (text, kind = "dim", title = "") => `<li class="chip chip-${esc(kind)}"${title ? ` title="${esc(title)}"` : ""}>${esc(text)}</li>`;

export function shell({ health, current, run, content, env = "" }) {
  const demo = health && health.demo
    ? `<div class="banner banner-demo" role="status"><strong>DEMO MODE \u2014 SYNTHETIC DATA.</strong> ${esc(health.demo_warning || "Not market evidence.")}</div>` : "";
  const apiKind = !health ? "warn" : health.status === "ok" ? "ok" : "bad";
  const apiText = !health ? "CONSOLE API: STATUS UNKNOWN" : health.status === "ok" ? "CONSOLE API: OK" : "CONSOLE API: FAULT";
  // Provider status is read from /health only if a future backend reports it; today none exists, so it is NOT CONNECTED.
  const prov = health && health.intelligence_provider ? String(health.intelligence_provider) : "NOT CONNECTED";
  const groupOf = (cur) => NAV.find(([, , members]) => members.includes(cur)) || NAV[0];
  const grp = groupOf(current);
  const nav = NAV.map(([p, label, members]) => {
    const h = buildHash(p, NEEDS_RUN.includes(p) && run ? { run } : {});
    return `<li><a href="${esc(h)}"${members.includes(current) ? ' aria-current="page"' : ""}>${esc(label)}</a></li>`;
  }).join("");
  const sub = SUBNAV[grp[1]] ? `<nav aria-label="Section"><ul class="subnav">${SUBNAV[grp[1]].map(([p, l]) =>
    `<li><a href="${esc(buildHash(p, run ? { run } : {}))}"${p === current ? ' aria-current="page"' : ""}>${esc(l)}</a></li>`).join("")}</ul></nav>` : "";
  return `<a class="skip" href="#main">Skip to content</a>
<header class="top"><div class="brand-block"><svg class="logo" viewBox="0 0 32 32" role="img" aria-label="NetOS"><polygon class="logo-hex" points="16,2 28,9 28,23 16,30 4,23 4,9" fill="none" stroke-width="1.5"/><circle class="logo-core" cx="16" cy="16" r="4.2"/><path class="logo-arm" d="M16 2v6M28 9l-5.2 3M28 23l-5.2-3M16 30v-6M4 23l5.2-3M4 9l5.2 3" fill="none" stroke-width="1.2"/></svg>
<h1 class="brand">NETOS <span class="brand-sub">Operator Console</span></h1></div>
<ul class="sysbar" aria-label="System status">${chip(apiText, apiKind)}${chip("MODE: RECORDED REPLAY", "cyan", "This console only replays persisted artifacts. No live workflow is running.")}${run ? chip("RUN " + short(run, 22), "dim", run) : ""}${env}${chip("INTELLIGENCE PROVIDER: " + prov, prov === "NOT CONNECTED" ? "violet-off" : "violet")}${chip("EXECUTION: NONE FROM THIS CONSOLE", "dim", "This console cannot submit, modify or cancel orders.")}
<li class="chip chip-readonly" title="No order, risk, strategy or broker controls exist in this application">READ-ONLY \u2014 no trading authority</li></ul></header>
${demo}<nav aria-label="Primary"><ul class="nav">${nav}</ul></nav>${sub}
<main id="main" tabindex="-1">${content}</main>
<footer>Local-only (127.0.0.1). Passing checks here does not prove profitability, broker compatibility or live readiness.</footer>`;
}

export const loading = (what) => `<p class="state" role="status" aria-live="polite">Loading ${esc(what)}\u2026</p>`;

export function errorView(err) {
  const hints = {
    SERVER_UNREACHABLE: "The API server is not reachable. Check that it is still running (python -m console_api --root <dir>).",
    JOURNAL_UNVERIFIED: "The journal failed integrity verification, so its contents are withheld. You may explicitly view it as UNVERIFIED.",
    JOURNAL_NOT_FOUND: "No decision journal was recorded for this run.",
    RUN_NOT_FOUND: "No artifacts exist for this run.", DECISION_NOT_FOUND: "That decision is not in this run's journal.",
  };
  const unverifiedLink = err.code === "JOURNAL_UNVERIFIED" ? `<p><a href="#" data-allow-unverified="1">Show contents anyway (marked UNVERIFIED)</a></p>` : "";
  return `<section class="state state-error" role="alert"><h2>Unable to show this page</h2><p>${badge(err.code, "bad")} ${esc(err.message)}</p>
<p>${esc(hints[err.code] || "")}</p>${unverifiedLink}</section>`;
}

export const integrityBanner = (i) => !i ? "" : i.status === "VERIFIED" ? "" :
  `<div class="banner banner-bad" role="alert"><strong>Journal ${esc(i.status)}.</strong> ${esc(i.warning || i.reason || "Integrity could not be established.")}</div>`;

// ---------------------------------------------------------------- overview
export function sparkline(points) {
  const ys = points.map((p) => Number(p.equity)).filter((n) => Number.isFinite(n));
  if (ys.length < 2) return `<p class="empty">Not enough equity points to chart.</p>`;
  const lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
  const pts = ys.map((y, i) => `${((i / (ys.length - 1)) * 300).toFixed(1)},${(58 - ((y - lo) / span) * 54).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 300 60" role="img" aria-label="Equity curve from recorded points, ${ys.length} points, min ${lo}, max ${hi}"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>`;
}

export function overviewDetail({ ov }) {
  const r = ov.run, eq = ov.equity, last = eq.last || {};
  const m = r.metrics || {};
  const unliq = r.metrics_basis ? `<p class="note">Basis: <code>${esc(r.metrics_basis)}</code>. Reported P&amp;L is mark-to-market and unliquidated; exit costs are not included.</p>` : "";
  const dec = ov.decisions;
  const decBlock = dec ? `<h3>Decisions <small>(all decisions in this run's journal)</small></h3>
${kv([["Total decisions", esc(dec.total)], ["By terminal state", Object.entries(dec.by_terminal_state).map(([k, v]) => `${statusBadge(k)} ${esc(v)}`).join(" ") || unknown()],
    ["Outcome tags", Object.entries(dec.by_tag).map(([k, v]) => `${statusBadge(k)} ${esc(v)}`).join(" ") || "None"]])}
${table({ caption: "Most recent decisions", rows: dec.recent, columns: [
  { label: "Decision", render: (d) => link(buildHash("/decision/" + d.decision_id, { run: r.run_id }), short(d.decision_id, 20)) },
  { label: "Instrument", render: (d) => val(d.instrument_id) }, { label: "Time", render: (d) => ts(d.cycle_timestamp) },
  { label: "Outcome", render: (d) => d.tags.map((t) => statusBadge(t)).join(" ") || statusBadge(d.terminal_state) }] })}`
    : `<p class="empty" role="status">No decision journal is available for this run, so decision, risk and order aggregates are Unavailable.</p>`;
  const ordBlock = ov.orders ? kv([["Orders", esc(ov.orders.total)], ["By last known state", Object.entries(ov.orders.by_last_state).map(([k, v]) => `${statusBadge(k)} ${esc(v)}`).join(" ") || unknown()],
    ["Flagged (uncertain / partial / cancelled-after-fill)", esc(ov.orders.flagged)]]) : "";
  const rec = ov.reconciliation ? `<p>Reconciliation: ${ov.reconciliation.blocked ? badge(`${ov.reconciliation.blocked} BLOCKED of ${ov.reconciliation.total}`, "bad") : badge(`${ov.reconciliation.total} recorded, none blocked`, "ok")}</p>` : "";
  return `${integrityBanner(ov.integrity)}
<section aria-labelledby="h-run"><h3 id="h-run">Run ${esc(short(r.run_id, 28))} ${evidenceBadge(r.evidence)} ${statusBadge(r.status)}</h3>
${warnings(r.warnings)}
${kv([["Run type", val(r.run_type)], ["Strategy / version", val(r.strategy_version_id, { code: true })], ["Dataset snapshot", val(r.dataset.data_snapshot_version, { code: true })],
    ["Date range", `${ts(r.dataset.window_start)} \u2192 ${ts(r.dataset.window_end)}`], ["Cost-model version", val(r.versions.cost_schedule_version, { code: true })],
    ["Risk / broker config", `${val(r.versions.risk_config)} / ${val(r.versions.broker_config)}`], ["Evidence source", val(r.evidence.source)]])}</section>
<section aria-labelledby="h-port"><h3 id="h-port">Portfolio <small>(from the recorded equity curve, last point)</small></h3>
${eq.available ? kv([["As of", ts(last.timestamp)], ["Equity", val(last.equity)], ["Cash", val(last.cash)], ["Market value", val(last.market_value)],
    ["Open positions", esc((last.positions || []).length)], ["Cumulative costs", val(last.cumulative_costs)], ["Drawdown halt latched", val(String(last.drawdown_halt_latched))],
    ["Peak-to-current drawdown", val(eq.points.length ? eq.points[eq.points.length - 1].drawdown : null)], ["Benchmark comparison", unknown("Unavailable")]]) + sparkline(eq.points)
  : `<p class="empty" role="status">Unavailable: ${esc(eq.reason)}</p>`}
${kv([["Net P&L", val(m.net_pnl)], ["Gross P&L", val(m.gross_pnl)], ["Realized P&L (gross)", val(m.realized_pnl_gross)], ["Unrealized P&L (gross)", val(m.unrealized_pnl_gross)], ["Transaction costs", val(m.total_transaction_costs)]])}${unliq}</section>
<section aria-labelledby="h-act"><h3 id="h-act">Activity</h3>${decBlock}${ordBlock}${rec}</section>`;
}

export function overview({ ov, runs }) {
  const r = ov.run;
  const picker = `<label for="run-select">Selected run</label> <select id="run-select" data-run-select>${runs.map((x) =>
    `<option value="${esc(x.run_id)}"${x.run_id === r.run_id ? " selected" : ""}>${esc(short(x.run_id, 26))} \u2014 ${esc(x.status)}</option>`).join("")}</select>`;
  return `<h2>Overview</h2><p>${picker}</p>${overviewDetail({ ov })}`;
}

// ------------------------------------------------------------------- runs
export function runsPage({ data, params }) {
  const f = `<form class="filters" role="search" data-filter-form="/runs"><label>Search <input type="search" name="q" value="${esc(params.q || "")}"></label>
<label>Status <select name="status"><option value="">Any</option>${["COMPLETED", "FAILED", "INCOMPLETE", "JOURNAL_ONLY", "UNKNOWN"].map((s) => `<option${params.status === s ? " selected" : ""}>${s}</option>`).join("")}</select></label>
<label>Run type <select name="run_type"><option value="">Any</option>${["SIMULATION_PIPELINE", "RESEARCH_HARNESS", "JOURNAL_ONLY", "REPORT_ONLY"].map((s) => `<option${params.run_type === s ? " selected" : ""}>${s}</option>`).join("")}</select></label>
<button type="submit">Apply</button></form>`;
  return `<h2>Run explorer</h2>${f}<p class="note">Runs are listed by recorded window start. Nothing here ranks or implies proven alpha; synthetic runs are labelled.</p>
${table({ caption: "Persisted runs", rows: data.items, empty: "No runs found in this artifact directory (or none match the filters).", columns: [
  { label: "Run", render: (r) => runLink(r.run_id) }, { label: "Status", render: (r) => statusBadge(r.status) }, { label: "Type", render: (r) => val(r.run_type) },
  { label: "Evidence", render: (r) => evidenceBadge(r.evidence) }, { label: "Strategy", render: (r) => val(short(r.strategy_version_id, 34), { code: true }) },
  { label: "Window", render: (r) => `${ts(r.dataset.window_start)} \u2192 ${ts(r.dataset.window_end)}` },
  { label: "Cost model", render: (r) => val(r.versions.cost_schedule_version) }, { label: "Net P&L", render: (r) => val(r.metrics.net_pnl) },
  { label: "Warnings", render: (r) => r.warnings.length ? r.warnings.map((w) => badge(w.code, "warn")).join(" ") : "None" }] })}
${pager(data, "/runs", params)}`;
}

export function pager(data, path, params) {
  const { total, limit, offset } = data;
  if (total <= limit) return `<p class="note">${esc(total)} record(s).</p>`;
  const mk = (o) => buildHash(path, { ...params, offset: o });
  return `<nav class="pager" aria-label="Pagination"><span>${esc(offset + 1)}\u2013${esc(Math.min(offset + limit, total))} of ${esc(total)}</span>
${offset > 0 ? link(mk(Math.max(0, offset - limit)), "Previous") : ""} ${offset + limit < total ? link(mk(offset + limit), "Next") : ""}</nav>`;
}

export function runDetail({ run }) {
  const q = { run: run.run_id };
  return `<h2>Run ${esc(short(run.run_id, 32))}</h2><p>${evidenceBadge(run.evidence)} ${statusBadge(run.status)}</p>${warnings(run.warnings)}
${kv([["Run type", val(run.run_type)], ["Hypothesis", val(run.hypothesis)], ["Evaluation period", val(run.evaluation_period)], ["Strategy", val(run.strategy_version_id, { code: true })],
    ["Baselines", val((run.baseline_strategy_version_ids || []).join(", "), { code: true })], ["Data snapshot", val(run.dataset.data_snapshot_version, { code: true })],
    ["Window", `${ts(run.dataset.window_start)} \u2192 ${ts(run.dataset.window_end)}`], ["Cost schedule", val(run.versions.cost_schedule_version)], ["Feature set", val(run.versions.feature_set_version)],
    ["Harness", val(run.versions.harness_version)], ["Pre-registered criteria", val(run.criteria_assessment)], ["Metrics basis", val(run.metrics_basis, { code: true })]])}
<h3>Metrics <small>(as recorded; costs are simulated-schedule estimates)</small></h3>${kv(Object.entries(run.metrics).map(([k, v]) => [k, val(v)])) || ""}
<h3>Journal</h3>${kv([["Present", val(String(run.journal.present))], ["Verified", val(run.journal.verified === null ? null : String(run.journal.verified))],
    ["Decisions", val(run.journal.decisions)], ["Incomplete", val(run.journal.incomplete_decisions)]])}
<h3>Explore</h3><ul class="links"><li>${link(buildHash("/decisions", q), "Decisions")}</li><li>${link(buildHash("/risk", q), "Risk & safety")}</li>
<li>${link(buildHash("/orders", q), "Orders & reconciliation")}</li><li>${link(buildHash("/health", q), "Health, provenance & exports")}</li>
${run.reports.map((r) => `<li>${link(buildHash(`/report/${run.run_id}/${r.report_id}`), "Evaluation report " + r.report_id)}</li>`).join("")}</ul>`;
}

// -------------------------------------------------------------- decisions
export function decisionsPage({ runId, data, params, allowUnverified }) {
  const opt = (arr, cur) => arr.map((s) => `<option${cur === s ? " selected" : ""}>${s}</option>`).join("");
  const f = `<form class="filters" role="search" data-filter-form="/decisions" data-keep="run"><input type="hidden" name="run" value="${esc(runId)}">
<label>Outcome tag <select name="tag"><option value="">Any</option>${opt(["HOLD", "NO_TRADE", "NO_CANDIDATE", "RISK_VETO", "REJECTED_AT_RISK", "INCOMPLETE", "RECONCILIATION_BLOCKED", "PARTIAL_OR_CANCELLED", "CANCELLED", "SKIPPED_PENDING_ORDER"], params.tag)}</select></label>
<label>Status <select name="status"><option value="">Any</option>${opt(["FINALIZED", "INCOMPLETE"], params.status)}</select></label>
<label>Instrument <input name="instrument_id" value="${esc(params.instrument_id || "")}"></label><button type="submit">Apply</button></form>`;
  return `<h2>Decision explorer <small>${esc(short(runId, 26))}</small></h2>${integrityBanner(data.integrity)}${f}
${table({ caption: "Decisions (including HOLD, no-trade, vetoed, incomplete)", rows: data.items, empty: "No decisions recorded in this run (or none match the filters).", columns: [
  { label: "Decision", render: (d) => link(buildHash("/decision/" + d.decision_id, { run: runId, ...(allowUnverified ? { allow_unverified: 1 } : {}) }), short(d.decision_id, 20)) },
  { label: "Time", render: (d) => ts(d.cycle_timestamp) }, { label: "Instrument", render: (d) => val(d.instrument_id) },
  { label: "Action", render: (d) => val(d.action, { word: "No candidate" }) }, { label: "Status", render: (d) => statusBadge(d.status) },
  { label: "Terminal state", render: (d) => val(d.terminal_state, { word: "Not finalized" }) },
  { label: "Risk", render: (d) => d.risk_verdict ? statusBadge(d.risk_verdict) + (d.failed_risk_checks.length ? " " + esc(d.failed_risk_checks.join(", ")) : "") : unknown("Not evaluated") },
  { label: "Order / filled qty", render: (d) => `${val(d.last_order_state, { word: "No order" })} / ${val(d.filled_quantity, { word: "No fills" })}` },
  { label: "Reconciliation", render: (d) => statusBadge(d.reconciliation_status) }, { label: "Tags", render: (d) => d.tags.map((t) => statusBadge(t)).join(" ") || "\u2014" }] })}
${pager(data, "/decisions", { ...params, run: runId })}`;
}

export const STAGE_TITLE = { snapshot: "Data / feature snapshot", candidate: "Candidate", risk: "Risk evaluation", sizing: "Sizing", order_intent: "Order intent",
  submission: "Submission / status", order_lifecycle: "Order lifecycle & broker events", fills: "Fills", portfolio_settlement: "Portfolio settlement", reconciliation: "Reconciliation", finalized: "Finalized" };

export function factsHtml(f) {
  if (f.checks) return `<p>Verdict ${statusBadge(f.verdict)} \u2014 risk rule version ${val(f.risk_rule_version_id, { code: true })}, quantity ceiling ${val(f.approved_qty_ceiling)}</p>` +
    table({ caption: "Rule outcomes as recorded", rows: f.checks, columns: [{ label: "Check", render: (c) => esc(c.check_id) },
      { label: "Outcome", render: (c) => statusBadge(c.evaluable === false ? "NOT_EVALUABLE" : c.passed ? "OK" : "FAILED") }, { label: "Detail", render: (c) => val(c.detail) },
      { label: "Recorded inputs", render: (c) => val(c.evidence) }] });
  const skip = new Set(["event_id", "event_type", "sequence"]);
  return kv(Object.entries(f).filter(([k]) => !skip.has(k)).map(([k, v]) => [k, val(v, { word: "Not recorded" })]));
}

export function decisionDetail({ d }) {
  const stages = d.stages.map((s) => `<li class="stage stage-${s.status === "RECORDED" ? "yes" : "no"}"><h4>${esc(STAGE_TITLE[s.stage] || s.stage)} ${statusBadge(s.status)}</h4>
${s.status === "RECORDED" ? `<p class="times">Event time ${ts(s.event_time)} \u00b7 Recorded at ${ts(s.recorded_at)} \u00b7 Data available at ${s.data_available_at ? ts(s.data_available_at) : unknown("Unknown")}</p>
${s.facts.map((f) => `<details open><summary>${esc(f.event_type)} <code>${esc(short(f.event_id, 26))}</code></summary>${factsHtml(f)}</details>`).join("")}` : `<p class="empty">${esc(s.note || "Not recorded")}</p>`}</li>`).join("");
  const miss = d.missing_references.length ? `<section class="banner banner-bad" role="alert"><h3>Missing references</h3><ul>${d.missing_references.map((m) =>
    `<li>${esc(m.kind)} <code>${esc(m.expected_id)}</code> expected from ${esc(m.expected_source)}</li>`).join("")}</ul></section>` : "";
  const exp = ["json", "csv"].map((fmt) => `<a href="/api/export/decision?run_id=${encodeURIComponent(d.run_id)}&amp;decision_id=${encodeURIComponent(d.decision_id)}&amp;format=${fmt}">Export ${fmt.toUpperCase()}</a>`).join(" \u00b7 ");
  return `<h2>Decision <code>${esc(short(d.decision_id, 30))}</code></h2><p>${statusBadge(d.status)} ${val(d.terminal_state, { word: "Not finalized" })} \u00b7 last stage <code>${esc(d.last_stage)}</code> \u00b7 reconciliation ${statusBadge(d.reconciliation_status)}</p>
${integrityBanner(d.integrity)}${d.status === "INCOMPLETE" ? `<div class="banner banner-bad" role="alert"><strong>Incomplete decision.</strong> It was never finalized; later stages are unresolved, not successful.</div>` : ""}${miss}
<section><h3>Versions recorded</h3>${kv(Object.entries(d.versions || {}).map(([k, v]) => [k, val(v, { code: true })]))}</section>
<section><h3>Stored explanation <small>(from persisted facts only; the strategy is not re-run)</small></h3><ol>${d.explanation.map((l) => `<li>${esc(l)}</li>`).join("")}</ol></section>
${d.caveats.length ? `<section><h3>Caveats</h3><ul>${d.caveats.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></section>` : ""}
<section><h3>Timeline</h3><ol class="timeline">${stages}</ol></section><p>${exp} \u00b7 ${link(buildHash("/decisions", { run: d.run_id }), "Back to decisions")}</p>`;
}

// -------------------------------------------------------------------- risk
export function riskPage({ r }) {
  return `<h2>Risk &amp; safety <small>${esc(short(r.run_id, 26))}</small></h2><p class="banner banner-readonly">${esc(r.controls)}</p>${integrityBanner(r.integrity)}
${kv([["Risk rule version(s)", val(r.risk_rule_versions.join(", "), { code: true })], ["Kill switch at run", val(r.kill_switch_at_run)],
    ["Drawdown halt latched (end of run)", val(r.drawdown_halt_latched_at_end === null || r.drawdown_halt_latched_at_end === undefined ? null : String(r.drawdown_halt_latched_at_end))],
    ["Unresolved reconciliation results", val(r.unresolved_reconciliation)],
    ["Removed-instrument exit policy (config)", val(r.risk_config_recorded ? String(r.risk_config_recorded.allow_exit_of_removed_instruments) : null)],
    ["Risk config label", val(r.risk_config_recorded && r.risk_config_recorded.label)]])}
${table({ caption: "Recorded rule outcomes (RR-1 \u2026 RR-9 and others)", rows: r.checks, empty: "No risk evaluations recorded.", columns: [
  { label: "Check", render: (c) => esc(c.check_id) }, { label: "Pass", render: (c) => esc(c.pass) }, { label: "Fail", render: (c) => c.fail ? badge(c.fail, "bad") : esc(c.fail) },
  { label: "Not evaluable", render: (c) => c.not_evaluable ? badge(c.not_evaluable, "warn") : esc(c.not_evaluable) },
  { label: "Failure examples (recorded inputs)", render: (c) => c.examples.length ? c.examples.map((e) => `${val(e.detail)} ${val(e.evidence)}`).join("<br>") : "\u2014" }] })}
<p>${r.rr_checks_with_no_recorded_evidence.length ? badge("Missing risk evidence", "warn") + " RR checks with no recorded evidence in this run: " + esc(r.rr_checks_with_no_recorded_evidence.join(", ")) : "All RR-1 \u2026 RR-9 have recorded results."}</p>
${table({ caption: "Risk vetoes / execution blocks", rows: r.vetoes, empty: "No vetoes recorded.", columns: [
  { label: "Decision", render: (v) => link(buildHash("/decision/" + v.decision_id, { run: r.run_id }), short(v.decision_id, 20)) },
  { label: "Verdict", render: (v) => statusBadge(v.verdict) }, { label: "Failed checks", render: (v) => esc(v.failed.join(", ") || "\u2014") }] })}
<p class="note">${esc(r.note)}</p>`;
}

// ----------------------------------------------------------------- research
export function researchPage({ reports, protocols, trials }) {
  return `<h2>Research &amp; evaluation</h2><p class="note">Research <strong>validity</strong> (was the test sound?) and criteria/performance outcome are separate. A valid test with adverse results is not a success.</p>
${table({ caption: "Evaluation reports", rows: reports.items, empty: "No evaluation reports found.", columns: [
  { label: "Report", render: (r) => r.unreadable ? badge("UNREADABLE", "bad") : link(buildHash(`/report/${r.run_id}/${r.report_id}`), short(r.report_id, 30)) },
  { label: "Run", render: (r) => r.run_id ? runLink(r.run_id) : unknown() }, { label: "Research validity", render: (r) => val(r.research_validity_verdict || r.verdict) },
  { label: "Criteria outcome (separate)", render: (r) => val(r.criterion_outcome) }, { label: "Protocol", render: (r) => val(r.protocol && `${r.protocol.id} v${r.protocol.version}`) },
  { label: "Evidence", render: (r) => r.evidence_class ? esc(r.evidence_class) : unknown() }] })}
${table({ caption: "Registered protocols", rows: protocols.items, empty: "No protocols registered.", columns: [
  { label: "Protocol", render: (p) => esc(p.protocol_id) }, { label: "Version", render: (p) => val(p.version) }, { label: "Hash", render: (p) => val(short(p.hash, 20), { code: true }) },
  { label: "Mode", render: (p) => val(p.mode) }, { label: "Hypothesis", render: (p) => val(p.hypothesis) }, { label: "Registered", render: (p) => ts(p.registered_at) }] })}
<h3>Trial ledger</h3><p>${trials.ledger_readable ? "" : badge("LEDGER UNREADABLE", "bad")} Hash-chain link continuity: ${trials.chain_links_consistent ? badge("CONSISTENT", "ok") : badge("BROKEN OR UNREADABLE", "bad")} <small>${esc(trials.chain_note)}</small></p>
${table({ caption: "Trial events (append-only)", rows: trials.items, empty: "No trial ledger entries.", columns: [
  { label: "Attempt", render: (t) => val(short(t.attempt_id, 22), { code: true }) }, { label: "Protocol", render: (t) => val(t.protocol_id) }, { label: "Lifecycle", render: (t) => val(t.lifecycle) },
  { label: "Outcome", render: (t) => statusBadge(t.outcome) }, { label: "Holdout exposed", render: (t) => val(String(t.holdout_exposed)) }, { label: "Holdout reused", render: (t) => val(String(t.holdout_reused)) }] })}
${pager(trials, "/research", {})}`;
}

export function reportPage({ rep }) {
  const v = rep.research_validity, c = rep.criteria_and_performance;
  const metrics = Object.entries(c.metrics || {}).map(([k, m]) => ({ k, ...(m || {}) }));
  const dq = v.dataset_quality || {}, cont = v.contamination || {};
  return `<h2>Evaluation report <small>${esc(short(rep.report_id, 34))}</small></h2><p>${evidenceBadge(rep.evidence)} ${runLink(rep.run_id)}</p>
<p class="notice">${esc(rep.uncertainty_notice || "")}</p>
<div class="two-col"><section aria-labelledby="h-valid" class="card"><h3 id="h-valid">Research validity</h3><p>${statusBadge(v.verdict)}</p><p class="note">${esc(v.meaning || "")}</p>
${kv([["Verification problems", val((v.verification_problems || []).length ? v.verification_problems.join("; ") : "None recorded")], ["Contamination checks passed", val((cont.checks_passed || []).join(", "))],
    ["Point-in-time claim", val(cont.point_in_time && cont.point_in_time.status)], ["Dataset blocking errors", val(dq.blocking_errors)], ["Holdout", val(v.holdout && v.holdout.status)],
    ["Walk-forward", val(v.walk_forward, { word: "Not performed" })], ["CSCV / PBO", val(v.statistical_validation && v.statistical_validation.cscv_pbo, { word: "Not computed" })],
    ["Trials counted", val(v.trial_accounting && v.trial_accounting.trial_count)], ["Reasons / limitations", val((v.reasons || []).join("; "))]])}
<h4>Dataset warnings</h4>${table({ caption: "Dataset quality warnings", rows: dq.warnings || [], empty: "None recorded.", columns: [{ label: "Code", render: (w) => esc(w.code) }, { label: "Severity", render: (w) => statusBadge(w.severity) }, { label: "Detail", render: (w) => esc(w.detail) }] })}</section>
<section aria-labelledby="h-perf" class="card"><h3 id="h-perf">Criteria &amp; performance</h3><p>${statusBadge(c.criterion_outcome)} ${c.admissible_as_evidence === false ? badge("Not admissible as evidence", "warn") : ""}</p>
<p class="note">Profitability claim recorded: <strong>${esc(c.profitability_claim ?? "Unknown")}</strong>. This is not a statement that the strategy is profitable.</p>
${table({ caption: "Pre-registered criteria", rows: (c.criteria_assessment && c.criteria_assessment.criteria) || [], empty: "No criteria assessed.", columns: [{ label: "Metric", render: (x) => esc(x.metric) },
  { label: "Rule", render: (x) => `${esc(x.comparator)} ${esc(x.threshold)}${x.adverse ? " " + badge("adverse criterion", "warn") : ""}` }, { label: "Observed", render: (x) => val(x.observed) }, { label: "Satisfied", render: (x) => statusBadge(x.satisfied ? "OK" : "FAILED") }] })}
${table({ caption: "Metrics with definitions, units, sample counts", rows: metrics, empty: "No metrics recorded.", columns: [{ label: "Metric", render: (m) => esc(m.k) }, { label: "Value", render: (m) => val(m.value, { word: "Unavailable" }) },
  { label: "Status", render: (m) => statusBadge(m.status) }, { label: "Unit", render: (m) => val(m.unit) }, { label: "Definition", render: (m) => val(m.definition) }, { label: "Denominator", render: (m) => val(m.denominator) }, { label: "Reason", render: (m) => val(m.reason, { word: "\u2014" }) }] })}</section></div>
<section><h3>Protocol &amp; links</h3>${kv([["Protocol", val(rep.protocol && `${rep.protocol.id} v${rep.protocol.version} (${rep.protocol.mode})`)], ["Protocol hash", val(rep.protocol && rep.protocol.hash, { code: true })],
    ["Report hash", val(rep.report_hash, { code: true })], ["Strategy", val(rep.links && rep.links.strategy_version_id, { code: true })], ["Data snapshot", val(rep.links && rep.links.data_snapshot_version, { code: true })],
    ["Cost schedule", val(rep.links && rep.links.cost_schedule_version)]])}
<p><a href="/api/export/report?run_id=${encodeURIComponent(rep.run_id)}&amp;report_id=${encodeURIComponent(rep.report_id)}&amp;format=json">Export JSON</a></p></section>`;
}

// ------------------------------------------------------- orders / recon
export function ordersPage({ o, rec }) {
  return `<h2>Orders, fills &amp; reconciliation <small>${esc(short(o.run_id, 26))}</small></h2>${integrityBanner(o.integrity)}<p class="note">${esc(o.note)}</p>
${table({ caption: "Order lifecycle", rows: o.items, empty: "No orders recorded in this run.", columns: [
  { label: "Order", render: (x) => val(short(x.order_id || x.order_key, 22), { code: true }) }, { label: "Instrument / side", render: (x) => `${val(x.instrument_id)} ${val(x.side)}` },
  { label: "Qty / filled", render: (x) => `${val(x.quantity)} / ${esc(x.filled_quantity)}` }, { label: "Submission", render: (x) => val(x.submission_outcome, { word: "No submission result" }) },
  { label: "Last known stage", render: (x) => val(x.last_known_state, { word: "None recorded" }) },
  { label: "History", render: (x) => x.state_history.map((h) => `${esc(h.from)}\u2192${esc(h.to)}`).join(", ") || unknown("None") },
  { label: "Fills", render: (x) => x.fills.map((f) => `${esc(f.quantity)}@${esc(f.price)} (${esc(f.fill_type)}${f.total_charges ? ", charges " + esc(f.total_charges) + " est." : ""})`).join("<br>") || unknown("No fills") },
  { label: "Flags", render: (x) => x.flags.map((f) => badge(f, f === "UNCERTAIN_SUBMISSION" ? "bad" : "warn")).join(" ") || "\u2014" }] })}
<h3>Reconciliation</h3><p>${rec.blocked ? badge(`${rec.blocked} blocked of ${rec.total}`, "bad") : badge(`${rec.total} recorded; none blocked`, "ok")}
 Pipeline reconciliation rows: ${esc(rec.pipeline_reconciliation_rows)} (mismatching: ${esc(rec.pipeline_reconciliation_mismatching)})</p>
${table({ caption: "Reconciliation results (internal vs broker/simulator)", rows: rec.items, empty: "No reconciliation results recorded.", columns: [
  { label: "Result", render: (x) => statusBadge(x.ok ? "OK" : "BLOCKED") }, { label: "Event time", render: (x) => ts(x.event_time) },
  { label: "Decisions", render: (x) => x.decision_ids.map((d) => link(buildHash("/decision/" + d, { run: rec.run_id }), short(d, 16))).join(" ") || unknown() },
  { label: "Mismatches", render: (x) => x.mismatches.map((m) => `${esc(m.field)}: internal ${val(m.internal)} vs broker ${val(m.broker)} \u2014 ${esc(m.detail || "")}`).join("<br>") || "None" }] })}`;
}

// ------------------------------------------------------- health / exports
export function healthPage({ health, runId, integ, run }) {
  const ex = (k) => ["json", "csv"].map((f) => `<a href="/api/export/${k}?run_id=${encodeURIComponent(runId)}&amp;format=${f}">${k} (${f.toUpperCase()})</a>`).join(" \u00b7 ");
  const j = integ.journal;
  return `<h2>Health, provenance &amp; exports</h2>${kv([["Service", statusBadge(health.status === "ok" ? "OK" : "FAILED")], ["Mode", health.demo ? badge("DEMO / SYNTHETIC", "synthetic") : badge("Artifact directory", "neutral")],
    ["Trading authority", esc(health.trading_authority)], ["Network binding", esc(health.bind)], ["Runs found", esc(health.runs)]])}
<h3>Selected run <small>${esc(short(runId, 26))}</small></h3>${evidenceBadge(run.evidence)}${warnings(run.warnings)}
${kv([["Journal integrity", statusBadge(j.status)], ["Events", val(j.event_count)], ["Decisions / incomplete", `${val(j.decisions)} / ${val(j.incomplete_decisions)}`], ["Missing-reference count", val(j.missing_reference_count)],
    ["Head hash", val(j.head_hash, { code: true })], ["Content digest", val(j.content_digest, { code: true })],
    ["Pipeline journal reference matches", integ.pipeline_journal_ref ? statusBadge(integ.pipeline_journal_ref.pipeline_journal_ref_matches ? "OK" : "FAILED") : unknown("Not recorded")],
    ["Strategy", val(run.strategy_version_id, { code: true })], ["Data snapshot", val(run.dataset.data_snapshot_version, { code: true })], ["Cost schedule", val(run.versions.cost_schedule_version)],
    ["Data freshness", unknown("Unavailable (no ingestion-status artifact is persisted)")], ["Failed jobs", unknown("Unavailable (no job records are persisted)")]])}
${j.status === "FAILED" ? `<p class="banner banner-bad" role="alert">${esc(j.warning)}</p>` : ""}
<h3>Exports <small>(read-only; secrets excluded)</small></h3><ul class="links"><li>${ex("run")}</li><li>${ex("decisions")}</li><li>${ex("orders")}</li><li>${ex("fills")}</li><li>${ex("risk")}</li><li>${ex("reconciliation")}</li></ul>`;
}
