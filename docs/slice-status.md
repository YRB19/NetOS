# Cumulative slice status

Slice 5 has NOT been started. Distinction used below: **historically reported** = a past
session's claim; **verified now** = executed in the Slice 4.5A session on this tree.

| Slice | Historically reported | Verified now (4.5A) | Origin |
| --- | --- | --- | --- |
| 0 | complete | arch check: 0 violations | restored |
| 1 | 112 tests | domain surface complete (Stage 3 §2) | restored |
| 2 | 116 tests | pipeline + persistence tests pass | restored |
| 3 | 81 tests | context + Tier-1 tests pass | restored |
| 4 | 43 tests | cost tests pass; schedule still unverified | restored |
| 4.5A | n/a | 369 passed (pytest); 366 (unittest, 3 need pytest fixtures); 14 new integration/guard tests; 0 violations | verification + minimal fix |
| 4.5B | n/a | 381 passed (pytest); 378 (unittest); +12 new tests; 0 violations | primary-source rate verification |

Cost schedule `india-equity-v1-unverified` remains `verified=False`, preserved unchanged
for reproducibility.

## Slice 4.5B — India equity cost schedule verification

**New schedule:** `india-equity-v2-2026-03-verified` (`verified=True` for its statutory/
regulatory/exchange components — brokerage remains an unverified assumption within it; see
`docs/cost-model.md`'s Rate Verification Status table).

**Verified against primary sources (2026-09-29):** STT (NSE, updated 17/04/2026), SEBI
turnover fee (same), GST rate (same), stamp duty (NSE, updated 03/10/2023), exchange
transaction charge (NSE circular NSE/FA/73061, effective 2026-03-01 — this one component's
rate actually changed from V1's ₹297/crore to ₹307/crore, a genuine regulatory update V1
predated).

**Still unverified:** brokerage (both schedule versions — deliberate, not a statutory rate).
**Documented gap, not fixed:** GST base composition is standard practice, not itemised by
the primary source; exchange identity (NSE vs BSE) is not modeled — NSE-specific rate used.

**Tests:** +12 (hand-calculated fixtures for both trade legs/types, SEBI and exchange-charge
unit-conversion tests, V1 preserved-and-reproducible tests). Full suite: 381 passed (pytest),
378 (unittest), 0 import-graph violations.

See `repository-integration.md`, `cost-model.md`, `cost-rate-verification.md`.
Historical reports: `history/slice1..4/`.
