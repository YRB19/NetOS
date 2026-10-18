"""SYNTHETIC fixtures for the Slice 6 pipeline tests.

Nothing here is real market data; every limit below is an EXAMPLE research value, not an
operator-approved risk limit. Results are infrastructure checks, never evidence of alpha.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from data.features.builders import ContextFeatureBuilder
from data.features.momentum import MomentumConfig, MomentumFeatureBuilder
from data.features.universe import make_permitted_universe
from domain.models.market_data import MarketData
from intelligence.baseline.tier2_momentum import Tier2Momentum12_1, Tier2MomentumConfig
from research.harness.config import EvaluationPeriod, ResearchConfig, two_way_split
from risk_execution.broker.adapters.simulated import SimulatedBrokerConfig
from risk_execution.risk_engine.config import KillSwitchState, RiskConfig
from risk_execution.sizing.sizer import SizingConfig
from simulation.config import PipelineConfig

V2 = "india-equity-v2-2026-03-verified"
HIST_START = datetime(2025, 3, 3, 10, 0, tzinfo=UTC)  # a Monday; weekly bars
TEST_START = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)  # after v2 schedule effective date
ISINS = tuple(f"INE{n:03d}X{n:05d}" for n in range(1, 11))
SCOPE = "research-account-1"
RISK_EFFECTIVE = datetime(2026, 1, 1, tzinfo=UTC)


def weekly_bars(
    isins=ISINS, weeks=78, growth=lambda i: 0.001 * (i + 1), override=None, start=HIST_START
) -> list[MarketData]:
    """close_i(w) = 100 * (1+g_i)^w ; open = 0.995*close. `override[(isin, w)] = close` edits one bar."""
    out: list[MarketData] = []
    for w in range(weeks):
        ts = start + timedelta(days=7 * w)
        for i, isin in enumerate(isins):
            c = 100.0 * (1.0 + growth(i)) ** w
            if override and (isin, w) in override:
                c = override[(isin, w)]
            o = round(c * 0.995, 4)
            c = round(c, 4)
            out.append(MarketData(isin, ts, o, round(max(o, c) * 1.01, 4), round(min(o, c) * 0.99, 4), c, 1000, "SYNTHETIC", start, "synthetic-v1"))
    return out


def universe(isins=ISINS, effective=TEST_START - timedelta(days=400)):
    return make_permitted_universe(list(isins), effective)


def config(**over) -> ResearchConfig:
    split = two_way_split(TEST_START - timedelta(days=30), TEST_START - timedelta(days=1),
                          TEST_START, TEST_START + timedelta(days=150))  # fmt: skip
    args = dict(
        hypothesis="SYNTHETIC: pipeline plumbing check, not a performance claim",
        pre_registered_criteria="SYNTHETIC: none; infrastructure verification only",
        initial_capital="1000000",
        cost_schedule_version=V2,
        split=split,
        evaluation_period=EvaluationPeriod.OUT_OF_SAMPLE,
    )
    args.update(over)
    return ResearchConfig(**args)


def risk_config(**over) -> RiskConfig:
    args = dict(
        label="risk_rules_v1", effective_from=RISK_EFFECTIVE,
        max_position_fraction=Decimal("0.40"), max_gross_exposure_fraction=Decimal("1.05"),
        max_leverage=Decimal("1.05"), max_drawdown_fraction=Decimal("0.30"),
        order_rate_window_seconds=86400, max_orders_per_window=100,
        permitted_account_scope=SCOPE, allow_exit_of_removed_instruments=True,
    )  # fmt: skip
    args.update(over)
    return RiskConfig(**args)


def sizing_config(**over) -> SizingConfig:
    args = dict(label="sizing_v1", cash_buffer=Decimal("0.01"), min_trade_notional=Decimal("0"))
    args.update(over)
    return SizingConfig(**args)


def broker_config(**over) -> SimulatedBrokerConfig:
    args = dict(label="sim_broker_v1", initial_cash=Decimal("1000000"), cost_schedule_version=V2)
    args.update(over)
    return SimulatedBrokerConfig(**args)


def pipeline(builder=None, **over) -> PipelineConfig:
    args = dict(
        risk=risk_config(), sizing=sizing_config(), broker=broker_config(),
        feature_builder=builder or ContextFeatureBuilder(), account_scope=SCOPE,
        kill_switch=KillSwitchState.INACTIVE,
    )  # fmt: skip
    args.update(over)
    return PipelineConfig(**args)


def tier2(fraction=0.3, **fcfg) -> tuple[Tier2Momentum12_1, MomentumFeatureBuilder]:
    mc = MomentumConfig(**fcfg)
    strat = Tier2Momentum12_1(Tier2MomentumConfig(selection_fraction=fraction, features=mc))
    return strat, MomentumFeatureBuilder(mc)
