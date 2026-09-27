# Source file audit

SHA-256 identities of every input file are retained in `slice-1-4-source-manifest.json`. All original archives are preserved externally; no input implementation is irrecoverable.

| Input path | Slices | Canonical disposition |
| --- | --- | --- |
| `.github/workflows/ci.yml` | 1 | .github/workflows/ci.yml; retained |
| `.gitignore` | 1 | .gitignore; retained |
| `README.md` | 1 | README.md; retained |
| `__init__.py` | 4 | shared/costs/__init__.py |
| `calculator.py` | 4 | shared/costs/calculator.py |
| `check_import_graph.py` | 4 | shared/arch_lint (rules merged; script wrapper) |
| `conftest.py` | 1 | conftest.py; retained |
| `cost-model.md` | 4 | docs/cost-model.md |
| `data/__init__.py` | 1, 2, 3 | data/__init__.py; retained |
| `data/adapters/__init__.py` | 1, 2, 3 | data/adapters/__init__.py; retained |
| `data/adapters/nse_bhavcopy_csv.py` | 2 | data/adapters/nse_bhavcopy_csv.py; retained |
| `data/adapters/nse_csv_adapter.py` | 3 | data/adapters/nse_csv_adapter.py; retained |
| `data/features/__init__.py` | 1, 2, 3 | data/features/__init__.py; retained |
| `data/features/context_builder.py` | 3 | data/features/context_builder.py; retained |
| `data/features/feature_sets.py` | 3 | data/features/feature_sets.py; retained |
| `data/features/universe.py` | 3 | data/features/universe.py; retained |
| `data/normalization/__init__.py` | 1, 2, 3 | data/normalization/__init__.py; retained |
| `data/normalization/corporate_actions.py` | 2 | data/normalization/corporate_actions.py; retained |
| `data/normalization/normalizer.py` | 3 | data/normalization/normalizer.py; retained |
| `data/normalization/persistence.py` | 2 | data/normalization/persistence.py; retained |
| `data/normalization/pipeline.py` | 2 | data/normalization/pipeline.py; retained |
| `data/schemas/__init__.py` | 1, 2, 3 | data/schemas/__init__.py; retained |
| `data/schemas/nse_bhavcopy_schema.py` | 2 | data/schemas/nse_bhavcopy_schema.py; retained |
| `data/validation/__init__.py` | 1, 2, 3 | data/validation/__init__.py; retained |
| `data/validation/freshness.py` | 2 | data/validation/freshness.py; retained |
| `data/validation/market_data_validation.py` | 2 | data/validation/market_data_validation.py; retained |
| `data/validation/raw_validation.py` | 2 | data/validation/raw_validation.py; retained |
| `data/validation/validators.py` | 3 | data/validation/validators.py; retained |
| `dependency-decisions.md` | 4 | docs/history/slice4/dependency-decisions.md |
| `docs/00-Project-Understanding-Report.md` | 1 | docs/00-Project-Understanding-Report.md; retained |
| `docs/01-Self-Improvement-Research-Report.md` | 1 | docs/01-Self-Improvement-Research-Report.md; retained |
| `docs/02-Self-Improvement-vs-Static-Strategy-Report.md` | 1 | docs/02-Self-Improvement-vs-Static-Strategy-Report.md; retained |
| `docs/03-Stage1-Requirements-Baseline-v0_2.md` | 1 | docs/03-Stage1-Requirements-Baseline-v0_2.md; retained |
| `docs/04-Stage2-System-Architecture-v0_1.md` | 1 | docs/04-Stage2-System-Architecture-v0_1.md; retained |
| `docs/05-Stage3-Detailed-Technical-Design-v0_1.md` | 1 | docs/05-Stage3-Detailed-Technical-Design-v0_1.md; retained |
| `docs/baseline-tier1.md` | 3 | docs/baseline-tier1.md; retained |
| `docs/data-ingestion.md` | 2 | docs/data-ingestion.md; retained |
| `docs/dependency-decisions.md` | 1, 2, 3 | docs/dependency-decisions.md; original versions in docs/history/ |
| `docs/feature-context.md` | 3 | docs/feature-context.md; retained |
| `docs/implementation-log.md` | 1, 2, 3 | docs/implementation-log.md; original versions in docs/history/ |
| `docs/slice-status.md` | 1, 2, 3 | docs/slice-status.md; original versions in docs/history/ |
| `domain/__init__.py` | 1, 2, 3 | domain/__init__.py; retained |
| `domain/models/__init__.py` | 1, 2, 3 | domain/models/__init__.py; retain full Slice 1 contract, merge required ingestion/context fields |
| `domain/models/_validators.py` | 1 | domain/models/_validators.py; retained |
| `domain/models/autonomy.py` | 1, 3 | domain/models/autonomy.py; retain full Slice 1 contract, merge required ingestion/context fields |
| `domain/models/candidate_trade.py` | 1 | domain/models/candidate_trade.py; retained |
| `domain/models/cost.py` | 1, 3 | domain/models/cost.py; retain full Slice 1 contract, merge required ingestion/context fields |
| `domain/models/decision_record.py` | 1, 3 | domain/models/decision_record.py; retain full Slice 1 contract, merge required ingestion/context fields |
| `domain/models/enums.py` | 1, 3 | domain/models/enums.py; retain full Slice 1 contract, merge required ingestion/context fields |
| `domain/models/feature_snapshot.py` | 1, 3 | domain/models/feature_snapshot.py; retain full Slice 1 contract, merge required ingestion/context fields |
| `domain/models/instrument.py` | 1, 2, 3 | domain/models/instrument.py; retain full Slice 1 contract, merge required ingestion/context fields |
| `domain/models/market_data.py` | 1, 2, 3 | domain/models/market_data.py; retain full Slice 1 contract, merge required ingestion/context fields |
| `domain/models/order.py` | 1, 3 | domain/models/order.py; retain full Slice 1 contract, merge required ingestion/context fields |
| `domain/models/order_request.py` | 1 | domain/models/order_request.py; retained |
| `domain/models/portfolio.py` | 1, 3 | domain/models/portfolio.py; retain full Slice 1 contract, merge required ingestion/context fields |
| `domain/models/promotion.py` | 1 | domain/models/promotion.py; retained |
| `domain/models/raw_observation.py` | 2 | domain/models/raw_observation.py; retained |
| `domain/models/research.py` | 3 | domain/models/research.py; re-exports canonical Slice 1 contracts |
| `domain/models/research_artifacts.py` | 1 | domain/models/research_artifacts.py; retained |
| `domain/models/risk.py` | 3 | domain/models/risk.py; re-exports canonical Slice 1 contracts |
| `domain/models/risk_decision.py` | 1 | domain/models/risk_decision.py; retained |
| `domain/models/serialization.py` | 1 | domain/models/serialization.py; retained |
| `domain/models/trade.py` | 3 | domain/models/trade.py; re-exports canonical Slice 1 contracts |
| `domain/models/versions.py` | 1, 3 | domain/models/versions.py; retain full Slice 1 contract, merge required ingestion/context fields |
| `governance/__init__.py` | 1, 2, 3 | governance/__init__.py; retained |
| `governance/autonomy/__init__.py` | 1, 2, 3 | governance/autonomy/__init__.py; retained |
| `governance/config/__init__.py` | 1, 2, 3 | governance/config/__init__.py; retained |
| `governance/killswitch/__init__.py` | 1, 2, 3 | governance/killswitch/__init__.py; retained |
| `implementation-log.md` | 4 | docs/history/slice4/implementation-log.md |
| `intelligence/__init__.py` | 1, 2, 3 | intelligence/__init__.py; retained |
| `intelligence/baseline/__init__.py` | 1, 2, 3 | intelligence/baseline/__init__.py; retained |
| `intelligence/baseline/tier1_equal_weight.py` | 3 | intelligence/baseline/tier1_equal_weight.py; retained |
| `intelligence/interface/__init__.py` | 1, 2, 3 | intelligence/interface/__init__.py; retained |
| `intelligence/interface/strategy.py` | 3 | intelligence/interface/strategy.py; retained |
| `intelligence/llm_component/__init__.py` | 1, 2, 3 | intelligence/llm_component/__init__.py; retained |
| `models.py` | 4 | shared/costs/models.py |
| `observability/__init__.py` | 1, 2, 3 | observability/__init__.py; retained |
| `observability/decision_log/__init__.py` | 1, 2, 3 | observability/decision_log/__init__.py; retained |
| `observability/reconciliation/__init__.py` | 1, 2, 3 | observability/reconciliation/__init__.py; retained |
| `observability/reporting/__init__.py` | 1, 2, 3 | observability/reporting/__init__.py; retained |
| `pyproject.toml` | 1 | pyproject.toml; retained |
| `research/__init__.py` | 1, 2, 3 | research/__init__.py; retained |
| `research/contamination/__init__.py` | 1, 2, 3 | research/contamination/__init__.py; retained |
| `research/experiments/__init__.py` | 1, 2, 3 | research/experiments/__init__.py; retained |
| `research/harness/__init__.py` | 1, 2, 3 | research/harness/__init__.py; retained |
| `research/promotion/__init__.py` | 1, 2, 3 | research/promotion/__init__.py; retained |
| `research/stats/__init__.py` | 1, 2, 3 | research/stats/__init__.py; retained |
| `risk_execution/__init__.py` | 1, 2, 3 | risk_execution/__init__.py; retained |
| `risk_execution/broker/__init__.py` | 1, 2, 3 | risk_execution/broker/__init__.py; retained |
| `risk_execution/broker/adapters/__init__.py` | 2 | risk_execution/broker/adapters/__init__.py; retained |
| `risk_execution/cost_model/__init__.py` | 1, 2, 3 | risk_execution/cost_model/__init__.py; retained |
| `risk_execution/order_state_machine/__init__.py` | 1, 2, 3 | risk_execution/order_state_machine/__init__.py; retained |
| `risk_execution/risk_engine/__init__.py` | 1, 2, 3 | risk_execution/risk_engine/__init__.py; retained |
| `risk_execution/sizing/__init__.py` | 1, 2, 3 | risk_execution/sizing/__init__.py; retained |
| `run_tests.py` | 2 | run_tests.py; retained |
| `schedule.py` | 4 | shared/costs/schedule.py |
| `scripts/__init__.py` | 2 | scripts/__init__.py; retained |
| `scripts/check_import_graph.py` | 2 | scripts/check_import_graph.py; retained |
| `shared/__init__.py` | 1, 2, 3 | shared/__init__.py; retained |
| `shared/arch_lint/__init__.py` | 1 | shared/arch_lint/__init__.py; retained |
| `shared/arch_lint/checker.py` | 1 | shared/arch_lint/checker.py; retained |
| `shared/arch_lint/cli.py` | 1 | shared/arch_lint/cli.py; retained |
| `shared/arch_lint/rules.py` | 1 | shared/arch_lint/rules.py; retained |
| `shared/config_loader/__init__.py` | 1, 2, 3 | shared/config_loader/__init__.py; retained |
| `shared/time/__init__.py` | 1, 2, 3 | shared/time/__init__.py; retained |
| `shared/time/clock.py` | 1, 2, 3 | shared/time/clock.py; reconcile compatible behavior, retain canonical implementation |
| `shared/versioning/__init__.py` | 1, 2, 3 | shared/versioning/__init__.py; retained |
| `shared/versioning/content_hash.py` | 2 | shared/versioning/content_hash.py; retained |
| `shared/versioning/identifiers.py` | 1 | shared/versioning/identifiers.py; retained |
| `shared/versioning/versioning.py` | 3 | shared/versioning/versioning.py; retained |
| `slice-status.md` | 4 | docs/history/slice4/slice-status.md |
| `test_costs.py` | 4 | tests/unit/test_costs.py |
| `tests/__init__.py` | 1, 2, 3 | tests/__init__.py; retained |
| `tests/adversarial/__init__.py` | 1, 2, 3 | tests/adversarial/__init__.py; retained |
| `tests/adversarial/test_import_graph_isolation.py` | 2 | tests/adversarial/test_import_graph_isolation.py; retained |
| `tests/adversarial/test_import_isolation.py` | 1 | tests/adversarial/test_import_isolation.py; retained |
| `tests/contract/__init__.py` | 1, 2, 3 | tests/contract/__init__.py; retained |
| `tests/contract/test_architecture.py` | 3 | tests/contract/test_architecture.py; retained |
| `tests/contract/test_market_data_contract.py` | 2 | tests/contract/test_market_data_contract.py; retained |
| `tests/fault_injection/__init__.py` | 1, 2, 3 | tests/fault_injection/__init__.py; retained |
| `tests/fault_injection/test_sf1_missing_data.py` | 2 | tests/fault_injection/test_sf1_missing_data.py; retained |
| `tests/fault_injection/test_sf1_sf2.py` | 3 | tests/fault_injection/test_sf1_sf2.py; retained |
| `tests/fault_injection/test_sf2_stale_data.py` | 2 | tests/fault_injection/test_sf2_stale_data.py; retained |
| `tests/fixtures/historical_data/mixed_quality_sample.csv` | 2 | tests/fixtures/historical_data/mixed_quality_sample.csv; retained |
| `tests/fixtures/historical_data/valid_sample.csv` | 2 | tests/fixtures/historical_data/valid_sample.csv; retained |
| `tests/integration/__init__.py` | 1, 2, 3 | tests/integration/__init__.py; retained |
| `tests/integration/test_normalization_pipeline.py` | 2 | tests/integration/test_normalization_pipeline.py; retained |
| `tests/integration/test_pipeline_e2e.py` | 3 | tests/integration/test_pipeline_e2e.py; retained |
| `tests/simulation/__init__.py` | 1, 2, 3 | tests/simulation/__init__.py; retained |
| `tests/unit/__init__.py` | 1, 2, 3 | tests/unit/__init__.py; retained |
| `tests/unit/_helpers.py` | 1 | tests/unit/_helpers.py; retained |
| `tests/unit/test_adapter_and_normalization.py` | 3 | tests/unit/test_adapter_and_normalization.py; retained |
| `tests/unit/test_bhavcopy_adapter.py` | 2 | tests/unit/test_bhavcopy_adapter.py; retained |
| `tests/unit/test_candidate_trade_safety.py` | 1 | tests/unit/test_candidate_trade_safety.py; retained |
| `tests/unit/test_context_builder.py` | 3 | tests/unit/test_context_builder.py; retained |
| `tests/unit/test_corporate_actions.py` | 2 | tests/unit/test_corporate_actions.py; retained |
| `tests/unit/test_domain_models.py` | 2, 3 | tests/unit/test_domain_models.py and test_domain_models_slice3.py; both retained |
| `tests/unit/test_immutability.py` | 1 | tests/unit/test_immutability.py; retained |
| `tests/unit/test_market_data_validation.py` | 2 | tests/unit/test_market_data_validation.py; retained |
| `tests/unit/test_order_state_machine.py` | 1 | tests/unit/test_order_state_machine.py; retained |
| `tests/unit/test_raw_validation.py` | 2 | tests/unit/test_raw_validation.py; retained |
| `tests/unit/test_required_field_validation.py` | 1 | tests/unit/test_required_field_validation.py; retained |
| `tests/unit/test_serialization.py` | 1 | tests/unit/test_serialization.py; retained |
| `tests/unit/test_shared_time.py` | 2 | tests/unit/test_shared_time.py; retained |
| `tests/unit/test_shared_versioning.py` | 2 | tests/unit/test_shared_versioning.py; retained |
| `tests/unit/test_tier1_baseline.py` | 3 | tests/unit/test_tier1_baseline.py; retained |
| `tests/unit/test_universe.py` | 3 | tests/unit/test_universe.py; retained |
| `tests/unit/test_valid_construction.py` | 1 | tests/unit/test_valid_construction.py; retained |
| `tests/unit/test_versioning.py` | 1 | tests/unit/test_versioning.py; retained |
| `tools/check_import_graph.py` | 3 | tools/check_import_graph.py; retained |
