# Risk Engine (Slice 6)

`risk_execution/risk_engine/` — Stage 3 §7. A deterministic **hard veto**:
`evaluate(candidate, context) -> RiskDecision`, never raising. No strategy, LLM, broker, network, clock
or randomness; the import checker enforces this (`risk_engine` may not import sizing, broker, research,
simulation or intelligence).

```
CandidateTrade -> RiskEngine -> APPROVE (RiskVerdict.APPROVE) | VETO (RiskVerdict.REJECT)
```

Strategies emit candidates only. The pipeline cannot call sizing or the broker except with an APPROVE
(`simulation/runner.py`; tests patch sizing/broker to explode if reached after a veto).

## Rules (all always evaluated and recorded — no short-circuit)

| Rule | Check |
|---|---|
| RR-CONFIG | risk config valid (else every candidate is vetoed) |
| RR-1 exposure | BUY: `size_hint` <= `max_position_fraction`; projected gross (positions + pending orders + the increase needed to reach the hinted target) <= `max_gross_exposure_fraction` x equity; headroom for >= 1 share |
| RR-2 leverage | projected gross / equity <= `max_leverage`; headroom for >= 1 share. Research constraint only — no broker margin model |
| RR-3 drawdown | BUY vetoed when `(peak-equity)/peak >= max_drawdown_fraction` or when the halt is **latched**; the runner latches on first breach and never self-clears. SELLs are allowed |
| RR-4 universe | instrument must be in the permitted universe. SELL of a *held, removed* instrument is allowed only if `allow_exit_of_removed_instruments=True` (operator choice, versioned) |
| RR-5 order rate | count of orders submitted in `(t - window, t]` must be < `max_orders_per_window`; orders already created earlier in the same cycle count |
| RR-6 account scope | context scope must equal `permitted_account_scope`; candidates have no account field, so a strategy cannot choose one |
| RR-7 attribution | strategy version, snapshot id (must equal this cycle's snapshot for the instrument), rationale, research run id, config version id, matching timestamp |
| RR-8 kill switch | only `INACTIVE` passes; `ACTIVE`, `UNKNOWN` and *missing* veto everything incl. SELLs |
| RR-9 boundary | engine config hash re-verified on every call (tamper => veto); `expected_risk_rule_version_id` must equal the engine's; any `ChangeRequest` targeting risk rules, kill switch, operator constraints, execution authority or autonomy level => veto |

HOLD is not an execution request: the engine answers `RR-NO-EXECUTION` (reject); the pipeline never sends HOLDs.

## RiskDecision and the quantity ceiling

Existing `RiskDecision` contract preserved. It requires `approved_qty` on an APPROVE while Stage 3 puts
sizing *after* risk. Smallest compatible reading (no contract change): on APPROVE, `approved_qty` is the
risk layer's **quantity ceiling** — headroom under RR-1/RR-2 for BUY, the sellable holding for SELL.
Sizing may never exceed it and is the only place an executable quantity/`OrderRequest` is produced.
Every decision lists each check (id, pass/fail, detail with numbers), the failing rules as
`"RR-x: reason"`, `risk_rule_version_id`, and a deterministic `risk_decision_id`.

## Fail closed

Missing/invalid portfolio, equity, peak, prices, universe, scope, kill switch, order history, snapshot
ids, run id, config version, risk-rule version, non-finite `size_hint`, non-`CandidateTrade` input,
invalid config, or any internal exception => VETO (`RR-FAILSAFE` as last resort). Each is tested.

## Configuration and versioning

`RiskConfig` is a frozen dataclass with **no default thresholds** (all are operator decisions, Stage 1
§12.2); test values are labelled examples. `rule_set_hash()` -> `RiskRuleVersion`; `configuration_version()`
-> existing `ConfigurationVersion` (deterministic id `riskcfg_<hash>`). Changing any value changes the
version and the experiment identity; historical results are never mutated.

## Known behaviours to be aware of

* Strategy `size_hint` is read for RR-1 (strict reject if the hinted target breaches a limit). Equal
  weights `1/k` therefore must fit `max_position_fraction`.
* A BUY re-issued for an already-held name at exactly a gross/leverage cap has zero headroom and is
  vetoed even though no purchase is needed (pinned by a test; harmless — no order results).
* RR-4's exit exception is an interpretation of "hard veto": with it `False`, a position in a removed
  instrument can never be sold by the pipeline. **Operator decision required before live use.**
* The kill switch is an explicit input here; `governance/killswitch/` is not wired (later slice).
* A passing Risk Engine is not regulatory approval.
