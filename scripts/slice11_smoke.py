#!/usr/bin/env python3
"""Slice 11 explicit smoke-test / composition script (NEVER run by the test suites).

Provider selection is EXPLICIT: --provider stub|anthropic|nvidia. There is no default real provider and no
fallback: if the chosen provider is not configured the script stops (exit 2) and calls nothing else.
A real provider additionally requires --confirm-live (an external, possibly paid call) and exits 1 unless
the call produced a validated classification (status OK + schema-valid output).

Imports operator-supplied disclosures, builds the bounded point-in-time context for one instrument at
one decision time, and asks a provider to classify it. Default provider is the OFFLINE stub (no network,
no cost). `--provider anthropic` makes ONE real API call and needs ANTHROPIC_API_KEY + ANTHROPIC_MODEL
from a separately authorised Anthropic Console account; a Claude.ai subscription is not API access.
`--provider nvidia` makes ONE real call to the NVIDIA hosted endpoint and needs NVIDIA_API_KEY
(NVIDIA_MODEL default moonshotai/kimi-k2-instruct; NVIDIA_BASE_URL default https://integrate.api.nvidia.com/v1).

  python3 scripts/slice11_smoke.py --disclosures docs.jsonl --instrument INE002A01018 \
      --decision-time 2026-04-06T10:00:00+00:00 --isin-map INE002A01018=INE002A01018 \
      [--provider stub|anthropic] [--cutoff-date 2025-01-31 --cutoff-source "<URL/title>"]

It prints the validated structured result and status. It never prints the key, headers or raw HTTP bodies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.adapters.disclosure_local_import import InstrumentMap, LocalDisclosureImport  # noqa: E402
from data.disclosures.store import ContextConfig, DisclosureStore  # noqa: E402
from intelligence.llm_component.model_version import CutoffBasis, CutoffDeclaration, build_model_version  # noqa: E402
from intelligence.llm_component.provider import ProviderError  # noqa: E402
from intelligence.llm_component.signals import SignalConfig, SignalService  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--disclosures", required=True, help="JSON/JSONL file of operator-supplied disclosures")
    ap.add_argument("--instrument", required=True)
    ap.add_argument("--decision-time", required=True, help="ISO-8601 with UTC offset")
    ap.add_argument("--isin-map", action="append", default=[], help="ISIN=instrument_id (exact; repeatable)")
    ap.add_argument("--provider", choices=("stub", "anthropic", "nvidia"), default="stub")
    ap.add_argument("--confirm-live", action="store_true", help="required for a real (external, possibly paid) provider")
    ap.add_argument("--max-requests", type=int, default=1)
    ap.add_argument("--cutoff-date", help="documented model knowledge cutoff (YYYY-MM-DD); omit if unknown")
    ap.add_argument("--cutoff-source", default="", help="where the cutoff date is documented (required with --cutoff-date)")
    a = ap.parse_args()

    decision = datetime.fromisoformat(a.decision_time)
    if decision.tzinfo is None:
        print("decision-time needs a UTC offset", file=sys.stderr)
        return 2
    store = DisclosureStore()
    imap = InstrumentMap(dict(x.split("=", 1) for x in a.isin_map), {})
    report = LocalDisclosureImport(a.disclosures).load_into(store, imap)
    ctx = store.build_context(a.instrument, decision.astimezone(UTC), ContextConfig())

    from model_providers.factory import select_provider  # composition-only import (ADR-22)

    if a.provider != "stub" and not a.confirm_live:
        print("refusing: a real provider makes an external, possibly paid call; pass --confirm-live", file=sys.stderr)
        return 2
    try:
        provider = select_provider(a.provider, os.environ)
    except ProviderError as e:  # missing configuration; no network was attempted and nothing else is tried
        print(f"{a.provider} provider unavailable: {e}", file=sys.stderr)
        return 2
    cutoff = (CutoffDeclaration(CutoffBasis.PROVIDER_DOCUMENTED, datetime.fromisoformat(a.cutoff_date).replace(tzinfo=UTC), a.cutoff_source)
              if a.cutoff_date else CutoffDeclaration(CutoffBasis.UNKNOWN))  # fmt: skip
    mv = build_model_version(provider.provider_name, provider.model_identifier, cutoff, "smoke-test-no-parent")
    svc = SignalService(provider, SignalConfig(enabled=True, max_requests=a.max_requests))
    rec = svc.evaluate(ctx)
    ok = rec.provider_status.value == "OK" and rec.interpretation is not None
    print(json.dumps({
        "import_report": report, "context_documents": len(ctx.documents), "context_hash": ctx.context_hash,
        "excluded": dict(ctx.excluded_counts), "model_version_id": mv.version_id,
        "cutoff_basis": cutoff.basis.value, "confirmatory_eligible": cutoff.confirmatory_eligible,
        "real_provider": provider.is_real_provider, "classification_confirmed": ok, "record": rec.to_payload(),
    }, indent=2, default=str))
    if provider.is_real_provider and not ok:
        print(f"smoke test FAILED: provider_status={rec.provider_status.value} ({rec.detail})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
