"""Evaluation artifact + human-readable report (Slice 12)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from research.harness.jsonio import jsonable
from shared.versioning.content_hash import hash_json_stable

ARTIFACT_SCHEMA = "ai-vs-baseline-artifact-v1"
_SECRET_KEY = re.compile(r"(api[_-]?key|secret|authorization|bearer|password|credential)", re.I)
_SECRET_VAL = re.compile(r"(nvapi-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{12,})")


class SecretLeakError(RuntimeError):
    pass


def assert_no_secrets(obj: object, path: str = "$") -> None:
    """Fail closed if any key or value looks like a credential."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _SECRET_KEY.search(str(k)) and v not in (None, "", False, "REDACTED"):
                raise SecretLeakError(f"credential-like key at {path}.{k}")
            assert_no_secrets(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            assert_no_secrets(v, f"{path}[{i}]")
    elif isinstance(obj, str) and _SECRET_VAL.search(obj):
        raise SecretLeakError(f"credential-like value at {path}")


def finalize_artifact(a: dict) -> dict:
    a = jsonable(a)
    assert isinstance(a, dict)
    assert_no_secrets(a)
    a["__schema__"] = ARTIFACT_SCHEMA
    a["artifact_hash"] = hash_json_stable({k: v for k, v in a.items() if k != "artifact_hash"})
    return a


def write_artifact(a: dict, root: Path | str, name: str) -> tuple[Path, Path]:
    d = Path(root) / "ai_eval_reports"
    d.mkdir(parents=True, exist_ok=True)
    jp, mp = d / f"{name}.json", d / f"{name}.md"
    jp.write_text(json.dumps(a, indent=2, sort_keys=True, default=str), encoding="utf-8")
    mp.write_text(render_markdown(a), encoding="utf-8")
    return jp, mp


def _f(v, nd: int = 6) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


def render_markdown(a: dict) -> str:
    s, d = a["spec"], a["decision"]
    arms = a["arms"]
    L: list[str] = []
    w = L.append
    w(f"# AI vs Baseline Evaluation — {s['spec_id']} v{s['version']}\n")
    w("## 1. Executive summary\n")
    w(f"**Outcome {d['outcome']}: {d['label']}.**\n")
    w(f"Evidence class: `{a['evidence_class']}`. Effective confirmatory: **{a['effective_confirmatory']}**.\n")
    for line in a["headline_findings"]:
        w(f"- {line}")
    w("\n## 2. Experimental design\n")
    w(f"- Hypothesis: {s['hypothesis']}\n- Null: {s['null_hypothesis']}\n- Alternative: {s['alternative_hypothesis']}")
    w(f"- Primary metric: `{s['primary_metric']}`; secondary: {', '.join(s['secondary_metrics'])}")
    w(f"- Frozen spec hash: `{a['spec_hash']}`; decision rules `{d['rules_version']}`")
    w(f"- Windows: development {s['development_window']}, selection {s['configuration_selection_window']}, "
      f"confirmatory {s['confirmatory_window']}")
    w(f"- Cost schedule `{s['cost_schedule_version']}`; execution NEXT_BAR_OPEN; rebalance {s['rebalance_frequency']}")
    w(f"- AI: provider `{s['ai_provider']}`, requested model `{s['ai_model_requested']}`, prompt `{s['prompt_template_id']}`, "
      f"schema `{s['output_schema_version']}`; seed {s['random_seed']}")
    w(f"- Acceptance: min effect {s['min_economic_effect']}, max drawdown regression {s['max_drawdown_regression']}, "
      f"max cost increase {s['max_cost_increase_fraction']}, min coverage {s['min_signal_coverage']}, "
      f"min signals {s['min_valid_signals']}, min cycles {s['min_cycles']}\n")
    w("## 3. Data quality and coverage\n")
    for k, v in a["data_quality"].items():
        w(f"- {k}: {v}")
    w("\n## 4. Point-in-time validation\n")
    w("```json\n" + json.dumps(a["point_in_time"]["counts"], indent=2, sort_keys=True) + "\n```")
    w(f"Run-level findings: {a['point_in_time']['run_level_findings'] or 'none'}. "
      f"Applied-but-ineligible signals (integrity breaches): **{a['point_in_time']['integrity_breaches']}**.\n")
    w("## 5. Strategy comparison\n")
    w("| Arm | Net return | Net P&L | Costs | Turnover/capital | Trades | Max DD | Cycle Sharpe (not annualised) |")
    w("|---|---|---|---|---|---|---|---|")
    for n, m in arms.items():
        w(f"| {n} | {_f(m['net_return'])} | {_f(m['net_pnl'], 2)} | {_f(m['total_costs'], 2)} | "
          f"{_f(m['turnover_to_capital'])} | {m['transactions']} | {_f(m['max_drawdown'])} | {_f(m['cycle_sharpe'])} |")
    w("\n## 6. Performance after costs\n")
    w("All arms share one data snapshot, universe, window, capital, cost schedule and execution convention. "
      "Gross P&L, costs and net P&L per arm:\n")
    for n, m in arms.items():
        w(f"- {n}: gross {_f(m['gross_pnl'], 2)}, costs {_f(m['total_costs'], 2)}, net {_f(m['net_pnl'], 2)}, "
          f"cost drag {_f(m['cost_drag'])}")
    w("\n## 7. Risk comparison\n")
    for n, m in arms.items():
        w(f"- {n}: max DD {_f(m['max_drawdown'])}, DD duration {m['drawdown_duration_cycles']} cycles, "
          f"downside dev {_f(m['downside_deviation'])}, worst cycle {_f(m['worst_cycle_return'])}, "
          f"avg exposure {_f(m['average_exposure'])}, max position weight {_f(m['max_position_weight'])}, "
          f"risk vetoes {m['risk_vetoes']}, sector concentration {m['sector_concentration']}")
    w("\n## 8. AI signal quality and contribution\n")
    w("```json\n" + json.dumps(a["ai_metrics"], indent=2, sort_keys=True, default=str) + "\n```")
    w("Incremental trades vs Tier-2 (per AI arm):\n")
    w("```json\n" + json.dumps(a["incremental_trades"], indent=2, sort_keys=True) + "\n```")
    w("Information-content diagnostic (signal direction vs next-cycle return):\n")
    w("```json\n" + json.dumps(a["information_content"], indent=2, sort_keys=True, default=str) + "\n```")
    w("\n## 9. Statistical confidence and limitations\n")
    w("```json\n" + json.dumps(a["statistics"], indent=2, sort_keys=True, default=str) + "\n```")
    for lim in a["limitations"]:
        w(f"- {lim}")
    w("\n## 10. Robustness and ablation results\n")
    w("| Ablation arm | Net return | Δ vs Tier-2 | Identical path to Tier-2 |")
    w("|---|---|---|---|")
    for r in a["ablation"]:
        w(f"| {r['arm']} | {_f(r['net_return'])} | {_f(r['delta_vs_tier2'])} | {r['identical_path_to_tier2']} |")
    w("\nAuthority checks: " + json.dumps(a["authority_checks"], sort_keys=True))
    w("\n## 11. Failed experiments and exclusions\n")
    w(f"Trial-ledger attempts recorded this evaluation: {a['trial_ledger']['attempts']} "
      f"(terminal outcomes: {a['trial_ledger']['terminal_outcomes']}).")
    w(f"Signal exclusions ({len(a['point_in_time']['exclusion_log'])}):")
    for e in a["point_in_time"]["exclusion_log"][:50]:
        w(f"- {e['instrument_id']} @ {e['decision_timestamp']}: {', '.join(e['reasons'])}")
    w("\n## 12. Conclusion\n")
    w(f"**Outcome {d['outcome']}** — {d['label']}.\n")
    for step in d["rule_trace"]:
        w(f"- {step}")
    w("\n## 13. Recommendation for the next stage\n")
    w(a["recommendation"])
    w(f"\n---\nArtifact hash `{a.get('artifact_hash', 'pending')}`. Synthetic/offline-fixture results are infrastructure "
      "verification, not evidence about markets or about any AI model.\n")
    return "\n".join(L)
