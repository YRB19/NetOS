# Cumulative slice status

Slices 1–4 have been integrated. Slice 5 has NOT been started.

| Slice | Included behavior |
| --- | --- |
| 0–1 | Package scaffold, architecture checks, full domain contracts, serialization and order transitions |
| 2 | Historical CSV ingestion, raw and canonical validation, split adjustments, JSONL and provenance |
| 3 | Versioned universe, feature snapshots, missing/stale handling, deterministic Tier-1 proposals |
| 4 | Decimal costs, explicit schedule registry, component rounding and cost tests |

See `slice-1-4-reconciliation.md` for contract resolutions, regression results,
and limitations. Original session reports are preserved under `history/slice1/`
through `history/slice4/`; those describe historical standalone states, not this tree.
