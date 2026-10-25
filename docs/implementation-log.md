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

## Slice 5 — Research Harness Core
**Start state:** repository as uploaded after Slice 4.5B (378 unittest tests passing, 0
import-graph violations; 3 fixture-based tests need pytest, unavailable here).
**Implemented:** `research/harness/` (config/identity, replay, runner, execution translation,
portfolio, metrics, comparison, result, failures, jsonio), `research/contamination/guards.py`,
`research/experiments/store.py`. Reused `Experiment`, `EvaluationRun`, `SplitSpec`,
`ContaminationCheckResult`, `DecisionRecord`, `Fill`, `CandidateTrade`, `FeatureSnapshot`,
`PermittedUniverse`, `CostModel`; no domain contract modified.
**Key decisions:** (1) fills at the next bar's OPEN, consumed lazily when the loop reaches
that bar, so no lookahead is possible by construction; (2) deterministic string identities
(`exp_`/`run_` + hash), wall-clock excluded; (3) fail-closed defaults (FAIL_RUN on rejected
orders; no forward-fill of held-position marks unless `carry_forward_marks`); (4) cost
schedule required, never defaulted; future-effective schedule needs explicit acknowledgement;
(5) `DecisionRecord` emitted for fills only — its enum cannot express HOLD-with-candidate or
simulated rejections (documented, not changed); (6) `EvaluationRun.passed_pre_registered_criteria
=False` means NOT ASSESSED (also `criteria_assessment` in result.json).
**Tests:** +93 → 471 (unittest): 41 unit, 18 lookahead/isolation adversarial, 25
fault-injection, 9 synthetic end-to-end. 3 pytest-fixture tests run manually: pass.
**Defects found while testing:** none in prior slices; two harness/test bugs fixed during
development (non-deterministic `Experiment.created_at` leaking into artifacts; a test helper
treating an empty universe list as "use default").
**Limitations:** see `research-harness.md` (ingestion_time not an availability gate, unliquidated
mark-to-market, no PBO/CSCV/regimes, per-cycle O(N) snapshot-version hashing).
**Next:** not started — Slice 6 (Tier-2 momentum / Risk Engine) per the Stage 3 sequence.

## Slice 6 — Tier-2 momentum + Risk Engine + deterministic sizing + simulated broker
**Start state (measured):** uploaded repo through Slice 5; 471 unittest tests OK; import checker 0 violations.
**Built:** `data/features/{calendar,momentum,builders}.py`; `intelligence/baseline/tier2_momentum.py`;
`risk_execution/risk_engine/{config,context,engine}.py`; `risk_execution/sizing/sizer.py`;
`risk_execution/broker/{interface.py,adapters/simulated.py}`; `simulation/{config,runner,reconcile,result,artifacts}.py`;
arch-lint rules for the new boundaries; three additive `FailureCategory` members.
**Design decisions:** (1) `simulation/` leaf package keeps research isolated from execution (ADR-9);
(2) `RiskDecision.approved_qty` on APPROVE is a quantity *ceiling*, sizing alone produces quantities/OrderRequests;
(3) rebalance = first observation of a calendar month, computed from visible data only, carried in
FeatureSnapshot features; (4) strategy version id embeds a hash of its full config; (5) risk config has no
default thresholds; (6) drawdown halt latches in the runner and never self-clears; (7) `DecisionRecord` also
emitted for risk vetoes (`REJECTED_AT_RISK`), broker rejections and reconciliation failures; (8) pipeline artifacts go
in a `pipeline/` subdirectory so the Slice 5 store is untouched.
**Defects found/fixed during development:** test fixture produced negative low prices; my first end-to-end test
file overwrote the pre-existing Slice 5 `tests/integration/test_pipeline_e2e.py` (2 tests) — caught by comparing
per-module counts against a pristine unzip; the Slice 5 file was restored and mine is
`test_execution_pipeline_e2e.py`; `RiskConfig` initially capped gross exposure at 1.0 (relaxed to positive).
Mid-session the sandbox was reset and the working tree was lost; it was rebuilt from the uploaded zip and
re-verified (593 tests, 0 violations).
**Tests:** 593 passed (471 + 122). Import checker: 0 violations.
**Limitations:** see each doc; synthetic data only; NEXT_BAR_OPEN no-slippage fills; no regulatory approval implied.
**Notion:** Slice 6 entry written and verified by re-fetching the page.

## 2026-10-20 — Slice 7: order state machine & reconciliation hardening
**Baseline (measured):** uploaded `NetOS.zip` checkout: 593 unittest tests OK, import checker 0 violations; Slices 0-6 present;
`tests/integration/test_pipeline_e2e.py` (Slice 5) intact. pytest/ruff/mypy unavailable offline; stdlib `unittest` + `compileall` used.
**Audit:** domain `Order` transition table printed and documented; `simulation/` is a valid leaf (ADR-9), unchanged; Slice 6 test
asserts ACKNOWLEDGED->CANCELLED is invalid, so the contract was left as is and the gap recorded as an open decision.
**Built:** `risk_execution/order_lifecycle/`, `risk_execution/reconciliation/`, ADR-10 rules, simulated-broker `find_order_by_client_key`
/ `order_statuses` / `inject_fault`, runner integration (lifecycle manager, idempotent fill booking, per-cycle execution reconciliation,
halt -> run failure). `simulation.reconcile` now delegates to the shared comparison (messages identical).
**Defects found/fixed:** the Slice 6 "only sizing constructs OrderRequest" guard caught my first `restore()` (it built requests) ->
restore now takes the caller's original requests; runner regression (RECON order row lost) fixed by only aborting at submit when the
broker order id is unknown; halt now surfaces at the next settlement so live order rows are finalized first.
**Tests:** 672 passed (593 + 79: lifecycle 44, reconciliation 18, architecture/safety 13, pipeline 4). Import checker: 0 violations.
**Limitations:** see `order-state-machine-reconciliation.md` section 8 and 10.

## 2026-10-21 — Slice 7 acceptance closure (gap remediation)
**Baseline:** extracted `NetOS-slice-7.zip` (no `.git` inside, so its commit cannot be verified from the archive; the working checkout I
edited has `.git` HEAD 54cdff28 with the Slice 7 work uncommitted): 672 unittest tests OK, import checker 0 violations. The roadmap file
`NetOS_Post_Slice_7_Roadmap.md` and the delta archive were not among the supplied files (the delta was my own earlier output); the
brief's own gap list and Stage 1/3 documents were used as the contract.
**Cancellation (ADR-11):** Stage 3 §9 prose/diagram, Stage 1 FR-3 and §10 read; edge `ACKNOWLEDGED -> CANCELLED` added for broker-confirmed
cancels only; Slice 6 broker test and a lifecycle test superseded with rationale; 8 cancel tests (request-only, timed-out request,
confirmed unfilled cancel, partial-then-cancel, fill-after-request, late fill after cancel, either-order cancel/fill, duplicates).
**Fees / average cost:** per-fill charges, components, schedule version, provenance and three-way average cost; policy documented
(exact money, 1e-9 average-cost tolerance); 12 tests. **Provenance (11 tests):** event/correlation/source/time fields, snapshot v2 + v1
migration, clipped free text; defect found by my own test and fixed (raw broker text was stored unclipped in history/last response).
**Recovery (ADR-12):** atomic checkpoint, write-ahead gating, validated restore, `recover_after_restart`; defect found by test and fixed
(`mark_portfolio_applied` was not checkpointed). 16 restart tests incl. a fresh-broker test documenting the external-state dependency.
**Tests:** 717 passed (672 + 45). `unittest discover`, `scripts/check_import_graph.py`, `python -m shared.arch_lint.cli .`, `compileall`.
pytest/ruff/mypy unavailable. **Status:** PARTIALLY COMPLETE (roadmap unavailable; crash windows in docs §12).

## 2026-10-23 — Slice 7 final closure: idempotent portfolio settlement (ADR-13)
**Baseline verified on the supplied tree (NetOS_2.zip):** 717 unittest tests OK; import checker and `shared.arch_lint.cli` 0 violations;
`compileall` clean; pytest not runnable here (the bundled `.venv` is a different interpreter), ruff/mypy unavailable.
**Audit:** runner called in-memory `buy/sell` then `mark_portfolio_applied`; the portfolio had no fill identity and no persistence, so a
replayed pending fill would double-book. **Change:** `ResearchPortfolio.apply_fill` (fill-id idempotency, fingerprint, conflict ⇒ fail closed),
`snapshot/restore/restore_from_store` with checksum + independent ledger replay, `research/harness/portfolio_checkpoint.py`,
`simulation/settlement.py`, runner switched to `apply_fill`, additive `FailureCategory.PORTFOLIO_CHECKPOINT_ERROR`; direct `buy/sell`
unchanged for non-checkpointed use. **Tests:** `tests/unit/test_portfolio_settlement.py` (+21). A first draft of one test used a purchase
that exactly exhausted cash as an "insufficient cash" case — a test error, fixed in the test; the code was correct. **Result:** 738 pass.
**Docs:** §12a and ADR-13 added; simulated-broker cancellation text corrected to ADR-11; status updated. ADR-11 still pending operator ratification.
Notion not updated (see delivery note); no Slice 8 work.

## 2026-10-25 — Slice 8: Decision Journal & Observability (ADR-14)
**Baseline (NetOS-slice-7-final.zip, no .git available - history/status unverifiable):** 738 unittest OK; import checker and arch_lint 0 violations; compileall clean.
**Audit findings:** artifacts-only decision export; HOLD/no-trade had no DecisionRecord; `RiskCheckResult` held prose only (inputs/limits not
recoverable); `observability/*` were scaffolds. **Changes:** `observability/decision_log/{events,journal,recorder,query,redaction,verify}.py`;
`simulation/journaling.py`; runner wiring; `RiskCheckResult.evidence/evaluable` populated for every Risk Engine check; four additive `TerminalState`
members; `FailureCategory.JOURNAL_FAILURE`; `OrderLifecycleManager.halt_external`; `journal_ref.json` artifact; existing pipeline tests use a
test-only `JournaledHarness` that injects an explicit in-memory double. **Found/fixed during build:** str-mixin enums were stringified as `Cls.MEMBER`
by redaction (normalisation now strips enums at every depth); reconciliation-required exits skipped the reconciliation event (now emitted).
**Tests:** +49 (`tests/unit/test_decision_journal.py`, `tests/integration/test_decision_journal_pipeline.py`); 787 pass. No Slice 9/10 work.
