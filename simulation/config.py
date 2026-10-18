"""Pipeline configuration bundle (Slice 6, Stage 3 §16).

Four separate configuration groups, kept apart on purpose:
  strategy   -> lives on the strategy object (version id embeds its config hash)
  risk       -> RiskConfig   (operator-owned; strategy code has no handle to it)
  sizing     -> SizingConfig
  simulation -> SimulatedBrokerConfig (+ account scope, kill-switch state)
All of it is folded into the experiment identity, so no hidden configuration exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from data.features.builders import FeatureBuilder
from risk_execution.broker.adapters.simulated import SimulatedBrokerConfig
from risk_execution.risk_engine.config import KillSwitchState, RiskConfig
from risk_execution.sizing.sizer import SizingConfig


@dataclass(frozen=True)
class PipelineConfig:
    risk: RiskConfig
    sizing: SizingConfig
    broker: SimulatedBrokerConfig
    feature_builder: FeatureBuilder
    account_scope: str
    kill_switch: KillSwitchState  # explicit, NO default: unknown must never mean "off"

    def validate(self) -> list[str]:
        errs: list[str] = []
        for name, obj in (("risk", self.risk), ("sizing", self.sizing), ("broker", self.broker)):
            try:
                errs += [f"{name}: {e}" for e in obj.validate()]
            except Exception as e:  # noqa: BLE001
                errs.append(f"{name}: not a valid config object ({type(e).__name__}: {e})")
        if not isinstance(self.account_scope, str) or not self.account_scope.strip():
            errs.append("account_scope must be a non-empty string")
        if not isinstance(self.kill_switch, KillSwitchState):
            errs.append(f"kill_switch must be a KillSwitchState, got {self.kill_switch!r}")
        if not callable(getattr(self.feature_builder, "build", None)):
            errs.append("feature_builder must implement build(...)")
        return errs

    def payload(self) -> dict:
        return {
            "risk": self.risk.payload(),
            "risk_rule_version_id": self.risk.risk_rule_version().version_id,
            "sizing": self.sizing.payload(),
            "broker": self.broker.payload(),
            "feature_builder": self.feature_builder.identity(),
            "account_scope": self.account_scope,
            "kill_switch": self.kill_switch.value if isinstance(self.kill_switch, KillSwitchState) else repr(self.kill_switch),
            "pipeline": "strategy>risk>sizing>order>simulated_broker>portfolio",
        }  # fmt: skip


def capital_matches(config_capital: Decimal, broker: SimulatedBrokerConfig) -> bool:
    return Decimal(broker.initial_cash) == config_capital
