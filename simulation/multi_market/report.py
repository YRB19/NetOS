"""Per-lane reports. A combined index may LINK lane reports but never creates a combined performance claim."""

from __future__ import annotations

import json
from pathlib import Path

from markets.lane import LANE_SPECS, MarketLane
from markets.readiness import LaneReadiness

FORBIDDEN_COMBINED_KEYS = {"combined_pnl", "combined_return", "combined_performance", "total_pnl", "combined_value",
                           "combined_sharpe", "blended_return"}  # fmt: skip


def build_lane_report(lane: MarketLane, readiness: LaneReadiness, sections: dict) -> dict:
    spec = LANE_SPECS[lane]
    rep = {
        "lane": lane.value, "currency": spec.currency, "timezone": spec.timezone,
        "lane_spec_identity": spec.identity(),
        "readiness": {"overall": readiness.overall.value, "data": readiness.data_status.value,
                      "internal_execution": readiness.internal_execution_status.value,
                      "external_branch": readiness.external_branch_status.value,
                      "reasons": list(readiness.reasons)},
        "sections": sections,
        "claims": "NO profitability or alpha claim is made. Evidence class is stated per section.",
    }  # fmt: skip
    _assert_no_combined(rep)
    return rep


def _assert_no_combined(obj) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in FORBIDDEN_COMBINED_KEYS:
                raise ValueError(f"cross-lane combined performance key forbidden: {k}")
            _assert_no_combined(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _assert_no_combined(v)


def write_lane_report(root: Path | str, report: dict) -> Path:
    p = Path(root) / report["lane"] / "lane_report.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, sort_keys=True, indent=1, default=str))
    return p


def combined_index(reports: list[dict]) -> dict:
    """Links + per-lane status only. Deliberately has NO aggregate status or performance field."""
    idx = {"lanes": [{"lane": r["lane"], "currency": r["currency"], "readiness": r["readiness"]["overall"],
                      "report": f"{r['lane']}/lane_report.json"} for r in reports],
           "combined_performance_claim": None,
           "note": "Lanes are independent experiments; no lane's result is evidence for another."}  # fmt: skip
    _assert_no_combined(idx)
    return idx
