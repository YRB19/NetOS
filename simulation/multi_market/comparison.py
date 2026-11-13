"""Internal-vs-external execution comparison. Disagreement is PRESERVED, never reconciled by overwriting."""

from __future__ import annotations

from collections.abc import Sequence

from risk_execution.external_paper.mirror import ExternalOrderRecord


def compare_execution(internal_orders: Sequence[dict], internal_fills: Sequence[dict],
                      external_records: Sequence[ExternalOrderRecord]) -> dict:  # fmt: skip
    ext_by_internal = {r.internal_order_id: r for r in external_records}
    rows, disagree = [], 0
    for o in internal_orders:
        fills = [f for f in internal_fills if f["order_id"] == o["order_id"]]
        q = sum(int(f["quantity"]) for f in fills)
        ipx = (sum(float(f["fill_price"]) * int(f["quantity"]) for f in fills) / q) if q else None
        e = ext_by_internal.get(o["order_id"])
        eq = e.filled_quantity if e else None
        epx = None
        if e and e.fills:
            tq = sum(f.quantity for f in e.fills)
            epx = sum(f.price * f.quantity for f in e.fills) / tq if tq else None
        differs = e is None or o["final_state"] != e.state.value or q != (eq or 0) or (
            ipx is not None and epx is not None and abs(ipx - epx) > 1e-9)  # fmt: skip
        disagree += int(differs)
        rows.append({
            "internal_order_id": o["order_id"], "instrument_id": o["instrument_id"], "side": o["side"],
            "approved_quantity": o["quantity"],
            "internal": {"state": o["final_state"], "filled_quantity": q, "avg_fill_price": ipx},
            "external": None if e is None else {"state": e.state.value, "filled_quantity": eq, "avg_fill_price": epx,
                                                "mode": e.mode, "resolution": e.resolution,
                                                "client_order_id": e.client_order_id},
            "differs": differs,
        })  # fmt: skip
    return {"rows": rows, "orders": len(rows), "disagreements": disagree, "reconciled_by_overwrite": False,
            "note": "both outcomes retained; neither is the market truth for AI-prediction scoring"}  # fmt: skip
