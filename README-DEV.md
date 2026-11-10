# NetOS — Developer README (run it, test it, fix it)

Overview of the project: `README.md`. Everything below was checked against the real repo
(Python 3.12.3, macOS/Linux, stdlib only — no pip installs needed to run or to run the tests).

## 1. One-time setup

```bash
cd ~/Developer/NetOS                 # repo root (the folder containing console_api/, frontend/, tools/)
source .venv/bin/activate            # your existing venv (any Python >= 3.11 works)
```

No `pip install` is required to run the console or the unittest suite.
(`pytest` is optional; `python run_tests.py` needs it, `unittest` does not.)

## 2. Run the Operator Console (the UI)

The console is ONE process: the Python server serves both the UI and the `/api/...` data.
There is no `npm install`, no `npm start`, no build step.

### A) Demo data (first time / to see the UI working)

```bash
python tools/build_ui_demo_fixtures.py --out ./.demo-artifacts     # folder must not already exist / be empty
python -m console_api --root ./.demo-artifacts                     # serves on http://127.0.0.1:8765/
```

Open **http://127.0.0.1:8765/** in a browser. Stop with `Ctrl-C`.
Demo data is SYNTHETIC; every page shows a DEMO banner.

If you re-run the builder: `rm -rf ./.demo-artifacts` first.

### B) Your own run artifacts

```bash
python -m console_api --root /path/to/artifact-dir [--port 9000]
```

`--root` is mandatory and must be an existing directory (no silent fallback to demo data).
Expected layout inside it: `runs/<run_id>/`, `journals/<run_id>/journal.jsonl`,
`validity/<run_id>/report*.json`, `protocols/`, `trials/ledger.jsonl`.

### Sanity check that the right server is answering

```bash
curl -s http://127.0.0.1:8765/api/health
# expected: {"status": "ok", "read_only": true, ... "trading_authority": "NONE"}
```

## 3. Troubleshooting the console

### "UNABLE TO SHOW THIS PAGE — HTTP_404 Request failed" + "CONSOLE API: STATUS UNKNOWN"

Cause (reproduced): the page was loaded from something that is **not** the NetOS console server.
The NetOS server always answers errors with typed JSON (e.g. `RUN_NOT_FOUND`). The UI only shows the
generic `HTTP_404 Request failed` when the reply was a plain 404 page — which is exactly what a
static file server (`python -m http.server`, VS Code Live Server, `npx serve`, opening
`frontend/public/index.html` via a local server) returns for `/api/health`.

Fix:

1. Stop whatever is serving `frontend/public` by itself.
2. Start the real server (section 2) and open **its** URL, `http://127.0.0.1:8765/`.
3. Verify with `curl -s http://127.0.0.1:8765/api/health` — it must return JSON, not an HTML 404.

Other checks:

- Port busy / another app on 8765: `lsof -i :8765`, kill it, or use `--port 9000` and open that port.
- Use `127.0.0.1` or `localhost` with the same port as the server. Anything else is rejected (403).
- Server prints `refused: ...` and exits: `--root` doesn't exist, or `--host` is not loopback.
- Page says run not found: the run id isn't in `--root`; check the folder layout above.
- Browser cached an old state: hard refresh (Cmd-Shift-R).

## 4. Tests and checks (run all before calling anything done)

```bash
python -m unittest discover -s tests -t .          # backend: 1121 tests, ~2 min
python scripts/check_import_graph.py               # ADR-6 plane isolation: must say PASSED (0 violations)
cd frontend && node --test tests/console.test.mjs tests/command-centre.test.mjs tests/ai-panel.test.mjs   # 43 tests
# or: cd frontend && npm test
```

Verified on the Slice 12 tree: 1121 backend OK, 43 frontend OK, 0 import-graph violations.
Frontend tests need Node only for testing; running the console does not.

Regenerate the frontend test snapshot after API shape changes:
`python tools/build_ui_test_snapshot.py`.

## 5. Other tools

| Command | Purpose |
|---|---|
| `python scripts/slice11_smoke.py` | Slice 11 AI-signal smoke check |
| `python tools/ai_vs_baseline_synthetic.py` | AI vs Tier-2 baseline evaluation on synthetic data (see `docs/ai-vs-baseline-evaluation.md`; last outcome: Inconclusive, synthetic only) |
| `python tools/ai_vs_baseline.py` | Same evaluation entry point for non-synthetic inputs (read its `--help` first) |

## 6. Applying slice zips

```bash
cd ~/Developer/NetOS
unzip -o NetOS-<name>.zip      # -o (letter o) = overwrite existing files, add new ones, no prompts
```

Zips never delete files. Commit/stash first so `git diff` shows exactly what changed.

## 7. Ground rules

1. Never break plane isolation; fix import-lint violations, never weaken the lint.
2. Intelligence emits `CandidateTrade` only — no quantities, credentials or broker calls.
3. Fail closed: missing/stale/unverifiable = reject or hold.
4. The console is read-only by design (GET only, loopback only). Do not add write endpoints.
5. Markdown in `docs/` is the project record (Notion writes have been unreliable).
6. Version everything that influences a decision (strategy, model, config, risk rules, cost model, data).

## 8. Where things are

```
console_api/     read-only HTTP server + read model (stdlib)      frontend/public/   UI (no build)
tools/           demo fixtures, snapshot builder, AI-vs-baseline   scripts/           import-graph, smoke
docs/            stage docs 00-05, per-slice docs, slice-status.md, operator-console.md, implementation-log.md
```

Per-slice detail: `docs/slice-status.md`, `docs/implementation-log.md`. Console reference: `docs/operator-console.md`.

## 9. Known open items

- Pending operator decisions: risk thresholds, RR-4 exit policy, `approved_qty` as quantity ceiling, ADR-11 ratification.
- Brokerage cost is a configurable, unverified assumption.
- AI component: no real provider call and no real disclosures wired; Slice 12 evaluation was synthetic and Inconclusive.
- Slice 13+ (Governance, real broker adapter, live-gate work) not started.
- Regulatory gates in `README.md`.
