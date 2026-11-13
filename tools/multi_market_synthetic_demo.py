"""Slice 13 engineering demo — SYNTHETIC data only. Proves wiring; proves NOTHING about markets.

Writes per-lane reports + a combined INDEX (links only, no combined performance) under --out.
Usage: python3 tools/multi_market_synthetic_demo.py --out /tmp/netos_mm
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.live.observation import LiveObservation  # noqa: E402
from data.live.quality import QualityPolicy  # noqa: E402
from markets.lane import DataProvenance, MarketLane  # noqa: E402
from markets.readiness import compute_lane_readiness, default_external_verification, default_source_verification  # noqa: E402
from prediction_ledger.models import Designation, Direction, PredictionRecord, PredictionStatus  # noqa: E402
from prediction_ledger.reader import LedgerReader  # noqa: E402
from research.prediction_eval.evaluator import (  # noqa: E402
    CoverageInputs, OutcomeEvaluator, coverage_report, evidence_class, summarize,
)  # fmt: skip
from risk_execution.external_paper.mirror import ExternalMirror  # noqa: E402
from risk_execution.external_paper.mock import MockExternalPaperAdapter  # noqa: E402
from simulation.multi_market.comparison import compare_execution  # noqa: E402
from simulation.multi_market.report import build_lane_report, combined_index, write_lane_report  # noqa: E402
from simulation.multi_market.sessions import Tier, build_session_matrix  # noqa: E402
from simulation.multi_market.shadow import LaneShadowSession, new_external_ledger  # noqa: E402

US, IN = MarketLane.US_EQUITIES, MarketLane.IN_EQUITIES
T0 = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)


def readiness(lane, integrated):
    return compute_lane_readiness(lane, default_source_verification(lane), default_external_verification(lane),
                                  internal_execution_integrated=integrated, cost_schedule_fully_verified=False)  # fmt: skip


def us_lane(root: Path) -> dict:
    rd = readiness(US, False)
    pol = QualityPolicy(US, "USD", frozenset({"AAA", "SPY"}), frozenset({"AAA", "SPY"}), timedelta(seconds=60),
                        timedelta(hours=2), 0.5, 1.0, timedelta(hours=1))  # fmt: skip
    s = LaneShadowSession(root, US, pol, rd)
    def o(i, t, c):  # noqa: E306
        return LiveObservation(US, "SYNTHETIC_FEED", i, "XTST", t, t, t, c, c, c, c, 100, "USD", DataProvenance.SYNTHETIC)
    t1, t2 = T0 + timedelta(minutes=1), T0 + timedelta(minutes=61)
    s.ingest([o("AAA", t1, 100.0), o("SPY", t1, 100.0), o("AAA", t2, 102.0), o("SPY", t2, 101.0)])
    rec = PredictionRecord(
        prediction_id="demo-1", correlation_id="demo", lane=US, instrument_id="AAA", universe_version="demo",
        session_id="demo", created_at=T0, input_available_at=T0, valid_from=t1, valid_until=t2, horizon_label="1h",
        forecast_target="DIRECTION_VS_BENCHMARK", status=PredictionStatus.ISSUED, benchmark_id="DEMO",
        benchmark_instrument_id="SPY", currency="USD", calendar_id="demo", protocol_id="demo",
        designation=Designation.EXPLORATORY, evidence_class="SYNTHETIC_ENGINEERING", direction=Direction.UP,
        outcome_definition={"price_field": "close", "flat_band_bps": 10, "max_ref_gap_seconds": 60, "max_end_gap_seconds": 60},
    )  # fmt: skip
    s.record_prediction(rec, T0 + timedelta(seconds=10))
    ev = OutcomeEvaluator(US, LedgerReader(root, US), s.reader())
    outs = ev.evaluate(T0 + timedelta(hours=3))
    return {
        "evidence_class": evidence_class(outs, source_verified=False),
        "data_quality": s.reader().verdict_counts(),
        "internal_execution": "BLOCKED: US cost model not integrated with the simulated broker (ADR-25)",
        "prediction_coverage": coverage_report(US, ev.ledger, outs, CoverageInputs(eligible_opportunities=1)),
        "prediction_summary": summarize(US, ev.ledger, outs, min_n=30),
        "external_branch": "MOCK_ONLY (not platform integration)",
    }


def india_lane(root: Path) -> dict:
    from tests.slice13.test_integration_boundaries import ASOF, india_session, runner  # engineering fixtures

    s = india_session(root)
    res = s.run_internal(Tier.TIER2, runner, ASOF)
    ad = MockExternalPaperAdapter(IN, fill_price_offset_bps=25)
    recs = s.mirror(s.intents_from(res.orders), ExternalMirror(ad, new_external_ledger(IN)))
    cmp = compare_execution(res.orders, res.broker_fills, recs)
    return {
        "evidence_class": "SYNTHETIC_ENGINEERING",
        "data_quality": s.reader().verdict_counts(),
        "internal_tier2_orders": len(res.orders),
        "execution_comparison": {k: v for k, v in cmp.items() if k != "rows"},
        "external_branch": "MOCK_ONLY (not platform integration)",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    root = Path(ap.parse_args().out)
    reports = [build_lane_report(US, readiness(US, False), us_lane(root)),
               build_lane_report(IN, readiness(IN, True), india_lane(root))]  # fmt: skip
    for r in reports:
        write_lane_report(root, r)
    matrix = [{"lane": m.lane.value, "tier": m.tier.value, "branch": m.branch.value, "status": m.status,
               "session_id": m.session_id} for m in build_session_matrix({US: readiness(US, False), IN: readiness(IN, True)})]  # fmt: skip
    (root / "combined_index.json").write_text(json.dumps({**combined_index(reports), "session_matrix": matrix}, indent=1))
    print(f"wrote lane reports + index under {root}")


if __name__ == "__main__":
    main()
