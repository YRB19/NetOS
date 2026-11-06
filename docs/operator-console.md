# Operator Console v1 (Slice 10)

A **private, local-only, strictly read-only** web application for inspecting persisted NetOS runs, decisions, risk and
reconciliation evidence, research reports and journal integrity. It has **no trading authority**: no order, risk-limit,
sizing, strategy-promotion, kill-switch or broker controls exist anywhere in the API or the UI.
Passing its tests proves nothing about profitability, broker compatibility or live readiness.

## 1. Architecture (ADR-21)

| Part | Location | Notes |
| --- | --- | --- |
| Read API | `console_api/` | Python stdlib `http.server`; GET only; no new dependency. Reuses `JournalReader` + `read_journal_file` (hash-chain verification). |
| Frontend | `frontend/public/` | Dependency-free ES modules, hash routing, no build step, no inline script/style (strict CSP). Pure view functions + a small controller. |
| Fixtures | `tools/build_ui_demo_fixtures.py`, `tools/build_ui_test_snapshot.py` | Synthetic only; built by the real Slice 5-9 code paths. |
| Tests | `tests/unit/test_console_api.py`, `frontend/tests/` | 51 Python tests, 39 node tests (28 original + 11 command-centre), 64 real-browser checks (optional script). |

`console_api` may not import `risk_execution`, `intelligence`, `governance`, `simulation`, `data`, `domain`, `research` or the journal
write path (`observability.decision_log.recorder`), and nothing may import `console_api` (import-graph rules, both checkers, plus a
subprocess `sys.modules` test). The frontend only speaks HTTP GET to `/api/...`.

## 2. Run it

Requirements: Python 3.12 (stdlib only). Node is **not** needed to run the console (only for the optional UI tests).

```bash
# A) Against your own persisted artifacts (explicit directory; no silent fallback to demo data)
python -m console_api --root /path/to/artifact-dir            # http://127.0.0.1:8765/
python -m console_api --root /path/to/artifact-dir --port 9000

# B) Explicit SYNTHETIC demo (writes only to a NEW, empty directory you name)
python tools/build_ui_demo_fixtures.py --out ./.demo-artifacts
python -m console_api --root ./.demo-artifacts
```

**Stop:** press `Ctrl-C` in the terminal running the server (or `kill <pid>` if backgrounded). There is no daemon, no state, nothing to clean up.

Artifact directory convention (what the API looks for):

```
<root>/runs/<run_id>/                 research artifacts + pipeline/ (result.json, experiment.json, equity_curve.jsonl, pipeline/*.json[l])
<root>/journals/<run_id>/journal.jsonl   decision journal (also accepted: <root>/<run_id>/journal.jsonl)
<root>/validity/<run_id>/report*.json    evaluation reports (schema v2)
<root>/protocols/<id>/v*.json, <root>/trials/ledger.jsonl, <root>/holdouts/
<root>/DEMO_MARKER.json                  only in the synthetic demo set -> every page shows DEMO MODE
```

Frontend tests: `cd frontend && node --test tests/console.test.mjs`. Real-browser check (needs Playwright + Chromium):
`NODE_PATH=<global node_modules> node frontend/tests/browser-check.mjs <artifact-root>`. Regenerate the test snapshot with
`python tools/build_ui_test_snapshot.py`.

## 3. Local trust boundary

* Binds `127.0.0.1` only. `--host` accepts loopback names only; any other host is **refused** (`NON_LOOPBACK_BIND_REFUSED`). No LAN or public hosting.
* `Host` must be `127.0.0.1:<port>` / `localhost:<port>` (DNS-rebinding guard); a foreign `Origin` is rejected (403). No CORS headers are emitted - the UI is served same-origin.
* Responses carry `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and a CSP of `default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'`.
* No credentials, API keys or broker endpoints exist in the frontend or the API. Output passes through the journal redaction layer and an absolute-path scrubber.
* No login screen is added on purpose: it would only simulate security. If the service ever becomes network-reachable, authentication, authorization and deployment hardening require a separate approved change **before** exposure.

## 4. Read API (all GET; JSON unless noted)

| Endpoint | Purpose |
| --- | --- |
| `/api/health` | status, demo flag, `trading_authority: NONE` |
| `/api/runs?limit&offset&q&status&run_type&evidence_class` | paginated run list (deterministic order: window start desc, run id) |
| `/api/runs/{run}` , `/overview`, `/equity`, `/integrity` | run summary, dashboard aggregates, recorded equity curve, journal integrity |
| `/api/runs/{run}/decisions?limit&offset&tag&status&terminal_state&action&instrument_id&reconciliation_status` | decision list |
| `/api/runs/{run}/decisions/{decision}` | full event chain, 11 ordered stages, versions, missing references, stored explanation |
| `/api/runs/{run}/risk`, `/orders`, `/reconciliation` | recorded rule outcomes, order lifecycle + fills, reconciliation results |
| `/api/research/reports`, `/reports/{run}/{report}`, `/protocols`, `/trials` | Slice 9 artifacts |
| `/api/export/{run,decisions,decision,orders,fills,risk,reconciliation,report}?run_id=&format=json\|csv` | audit export (identifiers, timestamps, versions, evidence class, source references; secrets excluded; CSV formula-injection defused) |

Errors are typed: `{"error": {"code", "message", "detail"}}` - e.g. `INVALID_IDENTIFIER`(400), `RUN_NOT_FOUND`/`DECISION_NOT_FOUND`/`JOURNAL_NOT_FOUND`/`REPORT_NOT_FOUND`(404),
`JOURNAL_UNVERIFIED`/`JOURNAL_CORRUPT`/`REPORT_CORRUPT`(422), `METHOD_NOT_ALLOWED`(405). Identifiers are allow-listed (`[A-Za-z0-9_.\-@=]`, <=128, no `..`).
A journal that fails hash-chain verification is **withheld** unless `allow_unverified=true` is requested explicitly, and then every payload carries an `UNVERIFIED` integrity banner.

## 5. Pages

Overview, Run explorer, Decision explorer (+ decision timeline), Risk & safety, Research (+ evaluation report), Orders & reconciliation, Health/provenance/exports.
Every page has loading, empty, missing-artifact, corrupt-journal, partial-data and server-failure states with plain status text.
A persistent **READ-ONLY** badge is shown; demo data shows a **DEMO MODE - SYNTHETIC** banner on every page.

## 6. Evidence and status semantics

* Evidence class is taken from recorded data only (journal `run_context.evidence_class`, else the validity report). Filenames and generic labels are never used. Unrecorded => **Unknown**.
* Recognised classes: synthetic infrastructure; historical replay (verified-for-stated-checks / unverified); paper execution; broker sandbox; live. Unrecognised strings are shown verbatim as "Unrecognised evidence class". Today only synthetic and historical-replay classes are produced by the code base.
* Unknown stays unknown (`Unknown` / `Unavailable`, never `0`). Costs on fills are labelled **estimates from the simulated schedule**, not broker contract notes.
* Research **validity** and **criteria/performance** are rendered as separate cards; a valid test with adverse results is not shown as success; `profitability_claim` is shown as recorded and explicitly disclaimed.
* Decisions never finalized, uncertain submissions and blocked reconciliations are flagged and never rendered as complete; absent stages read `NOT_RECORDED`.
* Nothing is re-computed from today's configuration and no strategy is re-run: explanations are the journal reader's persisted-fact explanations.

## 7. Known limitations

* **No React/Vite.** The build sandbox has no network, so those could not be installed or verified; ADR-21 records the zero-dependency choice and when to revisit.
* Data freshness, failed-job and data-ingestion status are **Unavailable**: no such artifacts are persisted today (shown as such).
* Benchmark comparison is **Unavailable** for pipeline runs (not recorded). Drawdown is derived from the recorded equity curve and labelled as such.
* Trial-ledger check on the Research page verifies hash-chain link continuity only; full re-verification stays in the research ledger.
* Existing repo limitations are surfaced, not fixed: unknown data-availability timestamps (shown `Unknown`), unliquidated terminal mark-to-market (warning `EXIT_COSTS_EXCLUDED`), separate lifecycle/portfolio persistence.
* Run discovery assumes the directory convention in section 2; journals produced elsewhere need to be placed accordingly.
* Large journals are indexed in memory per request cycle (cached by file mtime/size); fine for local inspection, not designed for multi-GB journals.
* Real-browser checks were run with Chromium via Playwright at 1440/768/360px in the build sandbox only; other browsers/devices were not exercised. No automated screen-reader audit was run.

## 9. Command-centre redesign (Slice 10 visual pass)

Frontend-only redesign: dark cyberpunk trading-terminal identity, no new dependency, no build step, no backend/API/CSP/test removal. Files: `frontend/public/command.js`
(new, pure view functions), `styles.css` (rewritten theme), `views.js` (new header/nav shell; `overview` split into `overviewDetail`), `app.js` (landing route), `main.js`
(display-only controls), `format.js` (additive number helpers). Screenshots: `docs/screenshots/`.

### Layout of the landing page (`#/`)
1. **System header** - NETOS mark, Console API health (from `/health`), `MODE: RECORDED REPLAY`, run id, environment chips (`SYNTHETIC ENVIRONMENT`, `SIMULATION`, broker config label),
   `INTELLIGENCE PROVIDER: NOT CONNECTED`, `EXECUTION: NONE FROM THIS CONSOLE`, `READ-ONLY`.
2. **KPI row** - recorded counts only: decisions, orders, fills, risk vetoes, journal events, warnings, errors (integrity + incomplete + blocked reconciliation + flagged orders), roles with records.
3. **Role tiles** - Orchestrator, Data Reader, Researcher, Investment Analyst, Deterministic Risk Engine, Execution Adapter, Portfolio Monitor. These are *architectural roles*, not seven running AI models.
4. **Left:** Input / Intelligence Intake, then the terminal-style **Activity Stream** (persisted journal events of the selected decision, with display-only category filters).
5. **Right:** **Agent Core** (8-stage ring, stage evidence panels, decision detail, decision switcher, future-telemetry list) above **Capital / Portfolio** (KPIs, equity curve with recorded-fill markers, drawdown, allocation, positions, transactions).
6. **Session Summary** - finalized-decision gauge, work recorded, warnings, errors, event-category totals. Full legacy overview remains in a collapsed panel.

Other areas keep their pages and routes under the same dark theme: RUNS & EXPERIMENTS, DECISION HISTORY, RISK & EXECUTION (Risk & safety / Orders & reconciliation), RESEARCH, SYSTEM / AUDIT.

### Actual vs planned
| Capability | Status |
| --- | --- |
| Replay of persisted decisions, orders, fills, settlement, reconciliation, equity points | **Actual** (read from artifacts / journal) |
| Deterministic strategy engine, deterministic risk engine, simulated broker | **Actual** (shown as deterministic / simulated, never as AI) |
| Claude / any intelligence provider, orchestrator, researcher agent, tool invocations, document parsing | **Planned - NOT CONNECTED** (shown dashed/violet; no activity is simulated) |
| Live NSE feed, filings/fundamentals, news/web research | **Planned - NOT CONNECTED** |
| Per-instrument price charts | **Unavailable** (not persisted) |
| Live event stream | **Planned.** Rows are built from explicit structured events (`streamRow`); a future runtime can feed the same shape. `data-live="1"` on a node is the only hook that enables the pulse animation, and nothing sets it today. |

### Honesty rules enforced in code and tests
Unknown values render `Unavailable`/`Unknown`, never 0. Stage status comes from recorded journal stages: ingestion is "dataset metadata only" (no ingestion events exist); analysis is "deterministic engine"
unless a model version is recorded; execution is never "executed" without a recorded fill; settlement needs a settlement event. Confidence appears only if recorded. No chain-of-thought is shown.
Allocation is cost basis plus cash (not market value). Currency is not recorded and is not assumed. Animations: one-shot draw-in of recorded arcs/equity line only, disabled by `prefers-reduced-motion`; no timers or random values.
The only buttons are display-only stream filters; stage selection is client-side show/hide. No API call other than GET.


## 10. Slice 11 — AI research-signal panel (read-only)
`GET /api/runs/{id}/ai-signals` summarises persisted `AI_SIGNAL_EVALUATED` events (provider, models, versions, status counts, adjustments, usage, cost only if a verified price was configured). The command-centre run page renders it with a `RESEARCH SIGNAL ONLY` label. No AI events => `AI-DISABLED`, provider `DISABLED`, disclosure source `NOT_CONNECTED`. Stub runs say "no real model was called". The panel has no controls and no secret material; there is no animated "thinking" state.
