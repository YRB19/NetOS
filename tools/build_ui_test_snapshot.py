"""Record real read-API responses over the SYNTHETIC demo set into frontend/tests/fixtures/snapshot.json.

The frontend node tests render views from these recorded responses, so UI tests exercise the true API shapes.
Synthetic data only; regenerate with:  python tools/build_ui_test_snapshot.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import build_ui_demo_fixtures as demo  # noqa: E402
from console_api.server import route  # noqa: E402
from console_api.store import ArtifactStore  # noqa: E402
from observability.decision_log.redaction import sanitize  # noqa: E402


def key(path: str, params: dict) -> str:
    q = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v not in (None, ""))
    return f"{path}?{q}" if q else path


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "demo"
        ids = demo.build(out)
        store = ArtifactStore(out)
        snap: dict = {
            "_meta": {"synthetic": True, "scenarios": ids, "warning": "SYNTHETIC UI test snapshot"}
        }

        def rec(path: str, params: dict | None = None) -> dict:
            params = params or {}
            _, body = route(store, "/api" + path, {k: str(v) for k, v in params.items()})
            snap[key(path, params)] = json.loads(json.dumps(sanitize(body), default=str))
            return snap[key(path, params)]

        rec("/health")
        runs = rec("/runs", {"limit": 500})["items"]
        rec("/runs", {"limit": 50, "offset": 0})
        research_run = next(r["run_id"] for r in runs if r["run_type"] == "RESEARCH_HARNESS")
        for rid in (
            ids["success"],
            ids["partial_fill"],
            ids["risk_veto"],
            ids["incomplete_blocked"],
        ):
            rec(f"/runs/{rid}")
            rec(f"/runs/{rid}/overview")
            rec(f"/runs/{rid}/risk")
            rec(f"/runs/{rid}/orders")
            rec(f"/runs/{rid}/reconciliation")
            rec(f"/runs/{rid}/integrity")
            rec(f"/runs/{rid}/decisions", {"limit": 50, "offset": 0})
        rec(f"/runs/{research_run}")
        rec(f"/runs/{research_run}/integrity")
        # decision details: one of each interesting kind
        want = {
            "filled": (ids["success"], "FILLED"),
            "veto": (ids["risk_veto"], "REJECTED_AT_RISK"),
            "partial": (ids["partial_fill"], "CANCELLED"),
            "hold": (ids["success"], "HOLD"),
        }
        picked = {}
        for name, (rid, tag) in want.items():
            rows = snap[key(f"/runs/{rid}/decisions", {"limit": 50, "offset": 0})]["items"]
            full = [
                r
                for r in route(
                    store,
                    f"/api/runs/{rid}/decisions",
                    {"limit": "500", "tag": tag}
                    if tag != "FILLED"
                    else {"limit": "500", "terminal_state": "FILLED"},
                )[1]["items"]
            ]
            if not full:
                continue
            did = full[0]["decision_id"]
            picked[name] = {"run": rid, "decision": did}
            rec(f"/runs/{rid}/decisions/{did}")
            _ = rows
        inc = ids["incomplete_blocked"]
        did = snap[key(f"/runs/{inc}/decisions", {"limit": 50, "offset": 0})]["items"][0][
            "decision_id"
        ]
        picked["incomplete"] = {"run": inc, "decision": did}
        rec(f"/runs/{inc}/decisions/{did}")
        snap["_meta"]["picked"] = picked
        rec("/research/reports", {"limit": 100})
        rec("/research/protocols")
        rec("/research/trials", {"limit": 50, "offset": 0})
        rep = snap[key("/research/reports", {"limit": 100})]["items"][0]
        rec(f"/research/reports/{rep['run_id']}/{rep['report_id']}")
        dest = ROOT / "frontend" / "tests" / "fixtures" / "snapshot.json"
        dest.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {dest.relative_to(ROOT)} ({dest.stat().st_size} bytes, {len(snap)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
