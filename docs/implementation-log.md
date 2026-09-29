# Implementation log

## 2026-09-27 — Cumulative Slices 1–4 reconciliation

Reconstructed one root-level project from the four user-supplied archives.
The archive contents are authoritative; existing local-only project contents
are preserved in the external recovery archive. Git history is retained.

See `slice-1-4-reconciliation.md` and `slice-1-4-file-audit.md` for the complete
reconciliation record. Original implementation logs are preserved verbatim in
`history/slice1/` through `history/slice4/`.

Slices 1–4 have been integrated. Slice 5 has NOT been started.

## Slice 4.5A — Repository verification and integration (session date 2026-09-28)
**Starting state:** uploaded NetOS.zip already contained an integrated tree (~30 commits) from
a prior reconciliation; original per-slice archives not supplied.
**Work:** independent verification (355 pytest tests passed; 352 via unittest; arch checker
0 violations x3 entry points); Stage 3 §2 surface checked (all present; Confidence is a
CandidateTrade field); scan for out-of-scope code (none; scaffolds empty).
**Reconciliation:** duplicate `NormalizationResult` renamed in Slice 3 alternate path;
`CostEstimate` split kept and allow-listed; two ingestion paths kept.
**Tests added:** `tests/integration/test_slice_4_5a_integration.py` (14): data->feature,
feature->Tier-1 (initial/unchanged/added/removed), provenance, cost independence (AST import
scan), unverified schedule guard, full chain determinism, duplicate-class guard.
**Failure/fix:** first determinism test failed — per-read `ingestion_time` provenance;
test corrected to fixed-raw-read semantics, behaviour documented, code unchanged.
**Final:** 369 passed (pytest), 366 (unittest), 0 violations.
**Limitations:** see repository-integration.md. **Next:** Slice 5 not started.

## Slice 4.5B — India equity cost schedule primary-source verification (session date 2026-09-29)
**Starting state:** 4.5A tree, 369/366 tests passing, 0 arch violations, schedule
`india-equity-v1-unverified` (`verified=False`).
**Work:** searched and fetched official primary sources for all six existing cost
components (NSE investor-education pages for STT/SEBI-fee/GST/stamp-duty; NSE circular
NSE/FA/73061 for exchange transaction charge; SEBI circular SEBI/HO/GSD/TAD/CIR/P/2022/0097
as GST corroboration). Compared each verified rate against the existing V1 constants.
**Finding:** five of six statutory/regulatory rates in V1 were already numerically correct
(STT, SEBI fee, GST rate, both stamp-duty legs) — now independently confirmed rather than
assumed. One component, the exchange transaction charge, was genuinely stale: V1's
₹297/crore predated NSE/FA/73061's revision to ₹307/crore, effective 2026-03-01 (before
today). Brokerage was deliberately left unverified (not a statutory rate; no single broker's
official rate card checked), consistent with the brief's explicit instruction.
**Code:** added `INDIA_EQUITY_SCHEDULE_V2_VERIFIED` (`india-equity-v2-2026-03-verified`,
`verified=True`) to `shared/costs/schedule.py`, registered additively in
`default_registry()`. `INDIA_EQUITY_SCHEDULE_V1_UNVERIFIED` left byte-for-byte unchanged.
No dataclass field added; per-component status recorded in the module docstring, the
schedule's `notes` dict, and `docs/cost-model.md`'s new Rate Verification Status table,
since a single schedule-level `verified` bool cannot itself distinguish "verified" from
"deliberately still an assumption" at component granularity.
**Tests added (12):** hand-calculated Decimal fixtures for delivery buy/sell and intraday
buy/sell against V2; a dedicated SEBI-fee unit-conversion test (₹10/crore → exact ₹10.00 at
₹1 crore turnover) and an equivalent exchange-charge test (₹307/crore); V1
preserved-and-still-selectable tests, including a fixed regression value proving V1's
exchange charge (74.25 on the standard fixture) did not drift when V2 was added.
**Verification:** 381 passed (pytest), 378 (unittest, historical +3 gap unchanged), 0
import-graph violations (both entry points).
**Docs:** `cost-model.md` (new Rate Verification Status table, rewritten
Provenance/Limitations), `cost-rate-verification.md` (new — full audit trail with sources,
URLs, effective dates), `slice-status.md`, this log.
**Limitations carried forward:** BSE's own exchange-transaction-charge rate not verified
(NSE-specific rate used; documented as a model gap, not fixed); GST base composition is
standard industry practice, not itemised by the primary source itself; brokerage remains
unverified in both schedule versions by design.
**Next:** Slice 5 not started (out of scope for this slice).
