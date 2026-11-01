"""JSON/CSV export of already-read records. Pure serialisation; identifiers, timestamps, versions, evidence class
and source references are preserved; secrets are scrubbed by the shared redaction layer."""

from __future__ import annotations

import csv
import io
import json
import re


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, sort_keys=True, default=str)
    return v


def to_csv(rows: list[dict]) -> str:
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(cols)
    for r in rows:
        wr.writerow([_cell(_neutralise(r.get(c))) for c in cols])
    return buf.getvalue()


def _neutralise(v):
    """CSV-injection guard: spreadsheet formula prefixes are defused in text cells."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") and not _is_number(v):
        return "'" + v
    return v


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def flatten_fills(orders: list[dict]) -> list[dict]:
    return [
        {
            "order_key": o["order_key"],
            "order_id": o["order_id"],
            "decision_ids": o["decision_ids"],
            "instrument_id": o["instrument_id"],
            "side": o["side"],
            **f,
        }
        for o in orders
        for f in o["fills"]
    ]


def flatten_risk(risk: dict) -> list[dict]:
    return [
        {
            "run_id": risk["run_id"],
            "risk_rule_versions": risk["risk_rule_versions"],
            **{k: c[k] for k in ("check_id", "pass", "fail", "not_evaluable")},
        }
        for c in risk["checks"]
    ]


_ABS_PATH = re.compile(r"(?<![\w:.\-/])(?:[A-Za-z]:\\[^\s\"'<>|]+|/(?:[\w.\-@+~]+/)+[\w.\-@+~]*)")


def scrub_paths(obj):
    """Replace absolute filesystem paths in any string with [PATH]; recursive. Identifiers/timestamps are untouched."""
    if isinstance(obj, str):
        return _ABS_PATH.sub("[PATH]", obj)
    if isinstance(obj, dict):
        return {k: scrub_paths(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub_paths(v) for v in obj]
    return obj
