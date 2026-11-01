// Application controller. Pure of browser globals: takes {root, api}; root only needs an `innerHTML` property.
import { parseHash, esc } from "./format.js";
import { ApiFailure } from "./api.js";
import * as V from "./views.js";
import * as CC from "./command.js";

export function createApp({ root, api, setTitle = () => {} }) {
  let seq = 0;
  let healthCache = null;
  const state = { path: "/", run: null };

  async function health() { return (healthCache ||= await api.get("/health")); }

  async function pickRun(params) {
    if (params.run) return params.run;
    const runs = await api.get("/runs", { limit: 500 });
    return runs.items.length ? runs.items[0].run_id : null;
  }

  const noRuns = () => `<section class="state" role="status"><h2>No runs available</h2><p>The artifact directory contains no persisted runs. Nothing is shown rather than substituting synthetic data. To try the demo, build the explicit synthetic set (see docs/operator-console.md).</p></section>`;

  async function page(path, segments, params) {
    const unv = params.allow_unverified ? { allow_unverified: 1 } : {};
    const page_ = { limit: 50, offset: Number(params.offset || 0) };
    switch (path === "/" ? "/" : "/" + (segments[0] || "")) {
      case "/": {
        const runs = (await api.get("/runs", { limit: 500 })).items;
        if (!runs.length) return { title: "Overview", cur: "/", content: noRuns() };
        const run = params.run || runs[0].run_id; state.run = run;
        const unvq = params.allow_unverified ? { allow_unverified: 1 } : {};
        const ovr = await api.get(`/runs/${encodeURIComponent(run)}/overview`);
        // Auxiliary reads are best-effort: a failure shows "Unavailable" in that panel instead of failing the page.
        const settle = async (p) => { try { return await p; } catch { return null; } };
        const q = encodeURIComponent(run);
        const [orders, recon] = await Promise.all([settle(api.get(`/runs/${q}/orders`, unvq)), settle(api.get(`/runs/${q}/reconciliation`, unvq))]);
        const decisionId = CC.pickDecision({ ov: ovr, orders, requested: params.decision });
        const detail = decisionId ? await settle(api.get(`/runs/${q}/decisions/${encodeURIComponent(decisionId)}`, unvq)) : null;
        return { title: "Command centre", cur: "/", run, env: CC.envChips({ ov: ovr, detail }),
          content: CC.commandCentre({ ov: ovr, runs, health: healthCache, aux: { orders, recon, detail, decisionId, runId: run }, selectedStage: params.stage }) };
      }
      case "/runs": {
        const q = { ...params }; delete q.offset;
        return { title: "Runs", cur: "/runs", run: state.run, content: V.runsPage({ data: await api.get("/runs", { ...q, ...page_ }), params }) };
      }
      case "/run": { const run = segments[1]; state.run = run; return { title: "Run", cur: "/runs", run, content: V.runDetail({ run: await api.get(`/runs/${encodeURIComponent(run)}`) }) }; }
      case "/decisions": {
        const run = await pickRun(params); if (!run) return { title: "Decisions", cur: "/decisions", content: noRuns() }; state.run = run;
        const { run: _r, offset: _o, allow_unverified: _a, ...filters } = params;
        const data = await api.get(`/runs/${encodeURIComponent(run)}/decisions`, { ...filters, ...page_, ...unv });
        return { title: "Decisions", cur: "/decisions", run, content: V.decisionsPage({ runId: run, data, params, allowUnverified: !!unv.allow_unverified }) };
      }
      case "/decision": {
        const run = params.run; state.run = run;
        const d = await api.get(`/runs/${encodeURIComponent(run)}/decisions/${encodeURIComponent(segments[1])}`, unv);
        return { title: "Decision", cur: "/decisions", run, content: V.decisionDetail({ d }) };
      }
      case "/risk": {
        const run = await pickRun(params); if (!run) return { title: "Risk", cur: "/risk", content: noRuns() }; state.run = run;
        return { title: "Risk & safety", cur: "/risk", run, content: V.riskPage({ r: await api.get(`/runs/${encodeURIComponent(run)}/risk`, unv) }) };
      }
      case "/orders": {
        const run = await pickRun(params); if (!run) return { title: "Orders", cur: "/orders", content: noRuns() }; state.run = run;
        const [o, rec] = await Promise.all([api.get(`/runs/${encodeURIComponent(run)}/orders`, unv), api.get(`/runs/${encodeURIComponent(run)}/reconciliation`, unv)]);
        return { title: "Orders & reconciliation", cur: "/orders", run, content: V.ordersPage({ o, rec }) };
      }
      case "/research": {
        const [reports, protocols, trials] = await Promise.all([api.get("/research/reports", { limit: 100 }), api.get("/research/protocols"), api.get("/research/trials", page_)]);
        return { title: "Research", cur: "/research", run: state.run, content: V.researchPage({ reports, protocols, trials }) };
      }
      case "/report": {
        const rep = await api.get(`/research/reports/${encodeURIComponent(segments[1])}/${encodeURIComponent(segments[2])}`);
        return { title: "Evaluation report", cur: "/research", run: state.run, content: V.reportPage({ rep }) };
      }
      case "/health": {
        const run = await pickRun(params); const h = await health();
        if (!run) return { title: "Health", cur: "/health", content: noRuns() };
        state.run = run;
        const [integ, runSum] = await Promise.all([api.get(`/runs/${encodeURIComponent(run)}/integrity`), api.get(`/runs/${encodeURIComponent(run)}`)]);
        return { title: "Health & exports", cur: "/health", run, content: V.healthPage({ health: h, runId: run, integ, run: runSum }) };
      }
      default: return { title: "Not found", cur: "/", content: `<section class="state state-error" role="alert"><h2>Page not found</h2><p>${esc(path)}</p></section>` };
    }
  }

  /** Navigate to a hash route; resolves after the DOM string has been written. Stale responses are dropped. */
  async function go(hash) {
    const my = ++seq;
    const { path, segments, params } = parseHash(hash);
    root.innerHTML = V.shell({ health: healthCache, current: path === "/" ? "/" : "/" + (segments[0] || ""), run: state.run, content: V.loading("page") });
    let out, h;
    try {
      h = await health();
      out = await page(path, segments, params);
    } catch (e) {
      if (my !== seq) return;
      const f = e instanceof ApiFailure ? e : new ApiFailure("client", "CLIENT_ERROR", "The page could not be rendered.", 0);
      root.innerHTML = V.shell({ health: healthCache, current: "/" + (segments[0] || ""), run: state.run, content: V.errorView(f) });
      return { error: f };
    }
    if (my !== seq) return;
    root.innerHTML = V.shell({ health: h, current: out.cur, run: out.run || state.run, content: out.content, env: out.env || "" });
    setTitle(`${out.title} \u2014 NetOS Operator Console`);
    return { ok: true, title: out.title };
  }
  return { go, state };
}
