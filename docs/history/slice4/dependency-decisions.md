# Dependency Decisions

## Slice 4 — Cost Model

**No new external dependencies added.**

The Cost Model uses only Python standard library:
- `decimal` (Decimal, ROUND_HALF_UP) — monetary arithmetic
- `dataclasses` — immutable domain contracts
- `enum` — `TransactionSide`, `TradeType`
- `ast` (in `scripts/check_import_graph.py` and test independence checks) —
  static import analysis, no execution of scanned code

This is consistent with the project's established constraint (no network
access in this sandbox, confirmed in prior sessions via failed `pip`
installs) and with Stage 2 §18/Stage 3 §22's stated preference not to add a
dependency before a specific slice's need justifies it. `Decimal` in
particular was selected over a third-party money-handling library because
the stdlib type is sufficient for this slice's requirements (exact base-10
arithmetic, explicit quantization/rounding control) and introduces zero new
dependency-sprawl risk.

No decision here would change if network access became available — nothing
in Slice 4 was blocked or degraded by dependency unavailability.
