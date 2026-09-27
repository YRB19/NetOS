# Implementation Log

Chronological record. Entries are appended, never rewritten (per the project's DOC-6
versioning discipline).

---

## Entry — Slice 0/1 (minimal reconstruction) + Slice 2 (historical data ingestion)

**Date:** this session (sandbox date not independently reliable; see note below on why no
external "current date" claim is made here).

**Stage:** Stage 3, Implementation.

**Slice:** Slice 0 (minimal reconstruction), Slice 1 (minimal reconstruction, scoped), Slice 2
(full).

**Objective:** Build Slice 2 — historical data ingestion — per the Slice 2 implementation
brief, using Stage 3 §5 as the authoritative spec.

**Starting-state finding (reported honestly, not glossed over):** This session's sandbox
contained no existing repository at `/home/claude/trading-system` or anywhere else searched.
The prior session's reported state ("Slice 0 and Slice 1 complete, 112 tests passing") could
not be located or verified. Per the project's standing epistemology (primary-source
verification, no fabricated claims of success), this was reported rather than silently
assumed away, and the minimum necessary Slice 0/1 foundation was rebuilt before Slice 2 began
— see `docs/slice-status.md` for exactly what was and was not reconstructed, and why.

**Data source selected:** NSE-bhavcopy-format historical CSV (documented format, not a
downloaded real archive — no network access in this sandbox). Full rationale in
`docs/data-ingestion.md`.

**Implementation:**
- Repository scaffold: full plane-based directory structure per Stage 3 §1.
- `scripts/check_import_graph.py`: AST-based import-graph/dependency-direction lint (ADR-6),
  with an enforced policy that `data/` may not import `intelligence`, `risk_execution`, or
  `research` (and, forward-looking, similar rules for `intelligence`/`research` ahead of those
  packages being built).
- Domain models (`domain/models/`): `Instrument`, `RawMarketObservation`, `MarketData`, each a
  frozen dataclass with `__post_init__` validation enforcing Stage 3 §2's field contracts.
- Shared utilities: `shared/time/clock.py` (UTC/IST conversion, freshness evaluation, no naive
  timestamp guessing), `shared/versioning/content_hash.py` (deterministic SHA-256-based
  hashing for raw files, JSON-stable structures, and composed data-snapshot versions).
- Data schema: `data/schemas/nse_bhavcopy_schema.py` (documented raw-input contract).
- Adapter: `data/adapters/nse_bhavcopy_csv.py` (CSV -> `RawMarketObservation`, one per row,
  source fields untouched; structural header validation; content-hash of the raw file).
- Validation: `data/validation/raw_validation.py` (required-field + series-scope check),
  `data/validation/market_data_validation.py` (numeric sanity + OHLC consistency, all
  violations accumulated), `data/validation/freshness.py` (SF-2 classification mechanism).
- Normalization: `data/normalization/pipeline.py` (orchestrates the full raw->canonical flow,
  including timestamp parsing with a documented IST-session-close assumption, duplicate/
  revision handling, and corporate-action adjustment hook), `data/normalization/
  corporate_actions.py` (split-adjustment math, tested synthetically; no live source wired up
  — see limitations), `data/normalization/persistence.py` (deterministic JSONL read/write
  stopgap).
- Fixtures: `tests/fixtures/historical_data/valid_sample.csv` (4 clean rows, 2 instruments),
  `tests/fixtures/historical_data/mixed_quality_sample.csv` (8 rows covering missing-field,
  negative-price, OHLC-inconsistency, negative-volume, exact-duplicate, and disallowed-series
  cases).

**Files changed:** all files under `governance/`, `data/`, `domain/`, `intelligence/`,
`risk_execution/`, `observability/`, `research/`, `shared/`, `tests/`, `scripts/`, `docs/`,
`deploy/` are new this session (fresh sandbox — see starting-state finding above). Directories
for planes not touched by Slice 2 (`intelligence/`, `risk_execution/`, `observability/`,
`research/`, `governance/`, `deploy/`) contain only `__init__.py` scaffolding, intentionally
empty of logic, per the instruction not to implement anything beyond Slice 2.

**Tests added:** 116 total, across:
- `tests/unit/` — domain models (23), shared time (14), shared versioning (10), market-data
  validation (10), raw validation (7), corporate actions (9), bhavcopy adapter (6)
- `tests/integration/` — full pipeline end-to-end on both fixtures, revision handling,
  determinism, persistence round-trip (14)
- `tests/fault_injection/` — SF-1 missing data (5), SF-2 stale data (5)
- `tests/contract/` — canonical MarketData interface guarantees (8)
- `tests/adversarial/` — import-graph isolation, including a deliberately planted violation to
  prove the checker actually detects problems, not just that it exists (4)

(Counts above are approximate per-file groupings; the authoritative total is what
`python3 run_tests.py` reports.)

**Test results (this session, actual command run):**
```
$ python3 run_tests.py
----------------------------------------------------------------------
Ran 116 tests in 0.028s

OK
```
Import-graph check, run standalone:
```
$ python3 scripts/check_import_graph.py .
IMPORT GRAPH CHECK: 0 violations.
```
`pytest`, `ruff`, and `mypy` were attempted and confirmed unavailable (no network access to
install them); stdlib `unittest` was used for all tests instead — see
`docs/dependency-decisions.md`.

**Known limitations:** see `docs/data-ingestion.md` "Known limitations" (complete list of six
items: no real downloaded dataset validated, no live corporate-action source, DR-3/DR-5/DR-6
unbuilt, JSONL persistence stopgap, single-source-format adapter, and a minimal Slice 0/1
domain-model reconstruction rather than the full Stage 3 §2 set).

**Decisions made:**
- Two-tier duplicate policy: exact-value duplicates rejected; same-identity-different-value
  records treated as revisions and both retained (Stage 3 §5's "corrections are new records"
  rule, made concrete).
- Bhavcopy dates assigned NSE's 15:30 IST session-close time before UTC conversion — a single,
  documented, one-place assumption.
- Corporate-action adjustment math implemented and tested; live sourcing explicitly deferred
  rather than faked.
- JSONL file persistence as an explicit Slice 2 stopgap, not a database.
- Minimal Slice 0/1 reconstruction scoped strictly to Slice 2's actual dependencies, rather
  than rebuilding the full Stage 3 §2 domain model speculatively.

**Decisions deferred:**
- Real historical-dataset acquisition and validation (needs network access).
- Corporate-action live data sourcing (DR-2 — unresearched).
- Fundamentals/order-book/regulatory-update data categories (DR-3/DR-5/DR-6).
- The relational persistence layer Stage 2 §18 specifies for later slices.
- The remaining ~17 Stage 3 §2 domain objects belonging to Plane 2/3/4 and Research.

**Problems discovered:**
- This sandbox has no network access at all (confirmed via failed `pip install pytest`),
  which affects both tooling availability (pytest/ruff/mypy) and the ability to download a
  real historical dataset. Both are documented as open items rather than worked around
  silently.
- The prior session's reported repository state was not present in this sandbox at session
  start (see starting-state finding above).
- An initial version of the "full pipeline determinism" integration test incorrectly asserted
  byte-identical output across two *independent* file loads; this was corrected once it
  surfaced that `ingestion_time` is legitimately wall-clock-dependent per file load (by
  design, per Stage 3 §5) — the test was rewritten to check the actually-correct determinism
  property (same raw batch -> byte-identical persisted output) plus a separate test for
  cross-load logical-content agreement. This is recorded here rather than silently fixed with
  no trace.

**Next slice:** Slice 3 — Feature/context formation + Tier-1 baseline (not started; per the
Slice 2 brief's explicit stop condition).
