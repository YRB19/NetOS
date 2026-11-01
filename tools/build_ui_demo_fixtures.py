"""Build the SYNTHETIC Operator Console demo artifact directory (Slice 10).

Everything written here is synthetic infrastructure data produced by the real Slice 5-9 code paths on
generated bars (plus two clearly-labelled hand-assembled journals for the incomplete / reconciliation-blocked
cases). It is NEVER written into an authoritative artifact root: the target directory must be new/empty and
a `DEMO_MARKER.json` is written so the console labels every page as DEMO / SYNTHETIC.

Usage:  python tools/build_ui_demo_fixtures.py --out ./.demo-artifacts
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from observability.decision_log.events import EventType as ET  # noqa: E402
from observability.decision_log.journal import FileDecisionJournal  # noqa: E402
from observability.decision_log.query import JournalReader  # noqa: E402
from observability.decision_log.recorder import JournalRecorder  # noqa: E402
from simulation import PipelineHarness  # noqa: E402
from simulation.artifacts import write_pipeline_run  # noqa: E402
from tests.unit._pipeline_helpers import (  # noqa: E402
    broker_config,
    config,
    pipeline,
    risk_config,
    tier2,
    universe,
    weekly_bars,
)

MARKER = "DEMO_MARKER.json"
FIXED = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)


def _pipeline_run(out: Path, *, fraction=0.3, pc_over=None) -> str:
    strat, builder = tier2(fraction)
    res = PipelineHarness().run(
        config(),
        strat,
        weekly_bars(),
        [universe()],
        pipeline(builder, **(pc_over or {})),
        journal_factory=lambda rid: FileDecisionJournal(out / "journals", rid, clock=lambda: FIXED),
        evidence_class="SYNTHETIC_INTEGRATION",
    )
    write_pipeline_run(res, out)
    return res.run.run_id


def _incomplete_and_blocked(out: Path, source_run: str) -> str:
    """Hand-assembled journal: one decision stops after submission (uncertain, never finalized) and one
    reconciliation is recorded as blocked. Built by re-recording real events of `source_run`; clearly synthetic."""
    reader = JournalReader.from_file(out / "journals", source_run)
    filled = next(s for s in reader.list_decisions(1000) if s.terminal_state == "FILLED")
    chain = reader.decision_chain(filled.decision_id)
    run_id = "run_demo_incomplete_blocked"
    j = FileDecisionJournal(out / "journals", run_id, clock=lambda: FIXED)
    rec = JournalRecorder(j, "demo-fixture-builder", "1")
    keep = {
        ET.DECISION_STARTED,
        ET.INPUT_SNAPSHOT_LINKED,
        ET.CANDIDATE_EMITTED,
        ET.RISK_EVALUATED,
        ET.SIZING_EVALUATED,
        ET.ORDER_INTENT,
        ET.SUBMISSION_RESULT,
    }
    for n, e in enumerate(chain.events):
        if e.event_type not in keep:
            continue
        payload = dict(e.payload)
        if e.event_type is ET.DECISION_STARTED:
            payload["run_context"] = {
                **payload.get("run_context", {}),
                "evidence_class": "SYNTHETIC_INTEGRATION",
            }
        if e.event_type is ET.SUBMISSION_RESULT:
            payload = {
                **payload,
                "outcome": "UNCERTAIN",
                "detail": "demo: broker response never arrived",
            }
        rec.emit(
            e.event_type,
            payload,
            decision_id=filled.decision_id,
            key=f"c{n}",
            links=dict(e.links),
            event_time=None if e.event_time is None else datetime.fromisoformat(e.event_time),
            data_available_at=None,
        )
    rec.emit(
        ET.RECONCILIATION_RESULT,
        {
            "ok": False,
            "mismatches": [
                {
                    "field": "position.quantity",
                    "internal": "120",
                    "broker": "0",
                    "detail": "demo: order submission outcome unknown; broker shows no position",
                }
            ],
        },
        decision_id=filled.decision_id,
        key="recon-blocked",
        links={"decision_ids": [filled.decision_id]},
    )
    return run_id


def _research_report(out: Path) -> None:
    from tests.unit.test_slice9_closure import RUN_TIME, Ctx  # noqa: PLC0415 - dev-only fixture reuse

    from research.protocol.protocol import AcceptanceCriterion, Comparator  # noqa: PLC0415

    ctx = Ctx(
        str(out),
        historical=False,
        acceptance_criteria=(
            AcceptanceCriterion(
                "max_drawdown", Comparator.GT, "0.0", "demo: any drawdown is adverse", adverse=True
            ),
            AcceptanceCriterion(
                "net_return", Comparator.GT, "0.50", "demo: unrealistically high bar", adverse=False
            ),
        ),
    )
    ctx.register()
    ctx.run(svc=ctx.service(at=RUN_TIME))


def build(out: Path) -> dict:
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"refusing to build demo fixtures into a non-empty directory: {out}")
    out.mkdir(parents=True, exist_ok=True)
    ids = {
        "success": _pipeline_run(out),
        "partial_fill": _pipeline_run(
            out,
            pc_over={
                "broker": broker_config(
                    max_fill_fraction_per_bar=Decimal("0.05"), label="sim_broker_partial"
                )
            },
        ),
        "risk_veto": _pipeline_run(
            out,
            pc_over={
                "risk": risk_config(
                    max_position_fraction=Decimal("0.004"), label="risk_rules_tight"
                )
            },
        ),
    }
    ids["incomplete_blocked"] = _incomplete_and_blocked(out, ids["success"])
    _research_report(out)
    (out / MARKER).write_text(
        json.dumps(
            {
                "synthetic": True,
                "purpose": "Operator Console demo fixtures (Slice 10)",
                "warning": "SYNTHETIC. Produced from generated bars. Not market evidence, not alpha, not live readiness.",
                "scenarios": ids,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return ids


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="NEW directory for the synthetic demo artifacts")
    ns = ap.parse_args(argv)
    print(json.dumps(build(Path(ns.out)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
