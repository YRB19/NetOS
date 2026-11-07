# Slice 11 — AI Candidate-Signal Research Adapter v1

**Label: RESEARCH SIGNAL ONLY.** Passing this slice does not show that the AI signal improves returns. Evidence class: synthetic infrastructure only. No real disclosure documents were ingested and no real provider call was made in this slice.

## 1. First (and only) use case
Classification of recent, company-specific official corporate announcements for instruments in the permitted NSE universe: status, sentiment, materiality, event category, uncertainty, and whether enough information exists. It tests only the Stage 3 §13 hypothesis (an additional bounded input layered on the Tier-2 ranking). It is a hypothesis, not a finding. Not built: web research, stock picking, advisor chat, multi-agent debate, tool-using agents, broker access, allocation.

## 2. Where it sits (planes)
| Piece | Location | Rule |
|---|---|---|
| `DisclosureRecord`, `DisclosureContext` | `domain/models/disclosure.py` | pure immutable data |
| Source interface, `NotConnectedSource` | `data/disclosures/source.py` | real-time feed = `NOT_CONNECTED` |
| Operator local-file import | `data/adapters/disclosure_local_import.py` | no network; exact instrument mapping only |
| Store + point-in-time context builder | `data/disclosures/store.py` | append-only; bounded |
| Strict schema, prompt, provider protocol, stub | `intelligence/llm_component/{schema,prompt,provider}.py` | no network modules (Slice 6 invariant kept) |
| Signal service (provider call, retry, budget) | `intelligence/llm_component/signals.py` | outside `generate_candidate_trades` |
| Deterministic overlay + ModelVersion builder | `intelligence/llm_component/{overlay,model_version}.py` | pure; confidence only |
| Anthropic HTTPS adapter | `model_providers/anthropic_provider.py` | ADR-22 leaf package |
| Model-cutoff contamination check | `research/contamination/model_cutoff.py` | fail-closed |
| Smoke/composition script | `scripts/slice11_smoke.py` | manual, never run by tests |

## 3. Disclosure data contract
Every record keeps four separate times — `event_time`, `published_at`, `ingested_at`, `available_at` (>= both published and ingested) — plus content hash, duplicate-group id, status (VALID / VALID_WITH_WARNINGS / UNMAPPED / REJECTED), warnings, declared source id, source reference and retention note. Source ids are **declared by the operator, not verified by NetOS**.
- **Point-in-time rule (single gate):** usable only if `available_at <= decision_timestamp`. A document ingested after a decision never affects it, whatever its event date. A revision is a separate record (`revises_document_id`); the original is kept and only superseded in contexts where the revision is itself available.
- **Mapping:** exact ISIN or exact (exchange, symbol) from an operator-supplied `InstrumentMap`. No name matching. Conflicting ISIN/symbol => UNMAPPED. Unmapped/rejected records are stored (auditable) but never enter a context.
- **Context:** per instrument and decision time; at most `max_documents` (default 5, hard cap 20) within `lookback_days` (default 14, max 366); sorted by availability; duplicates collapsed; every exclusion counted (`excluded_counts`); hash-addressed (`context_hash`). An empty context is a valid explicit no-signal input.
- **Backtest consequence:** `ingested_at` defaults to the import clock, so a document imported today is correctly *not* available to a 2024 decision. Supply a verified original `ingested_at`/`available_at` per item only if you hold evidence of when it was actually available.

**FeatureSnapshot decision (ADR-23):** `FeatureSnapshot` is unchanged. Adding disclosure data there would change its identity and every stored fixture. Instead `DisclosureContext.input_snapshot_id` pairs the context with the snapshot, and the journal records both ids and the context hash. Old Tier-1/Tier-2 snapshots stay valid (tested).

## 4. Model output schema (`disclosure_interpretation_v1`)
Required fields only: `status` (SIGNAL/NO_SIGNAL/UNKNOWN), `sentiment`, `materiality` (HIGH/MEDIUM/LOW/NONE/UNKNOWN), `confidence` [0,1] (confidence in the *classification*, not a price forecast), `confidence_adjustment` (relative to a long thesis; must agree with sentiment), `uncertainty`, `event_category`, `source_document_refs` (must be input ids), `rationale` (<= 600 chars), `output_schema_version`. Any extra field (action, quantity, risk, broker, promotion…), missing field, unknown enum, out-of-range/boolean/NaN confidence, unreferenced document or inconsistent combination is a hard rejection; a rejection is never a positive signal. Source text is untrusted data; the component has no tools, browsing, shell or credentials. Only the validated structured output and a short rationale are stored (no hidden reasoning).

## 5. Confidence adjustment (`confidence_adjustment_v1`)
The only effect of the model. `delta = ± max_delta × materiality_weight × model_confidence`, clamped to [0,1], only when status is SIGNAL and model confidence >= `min_model_confidence`. Defaults (research parameters, **not tuned, no evidence behind them**): `max_delta=0.10`, `min_model_confidence=0.60`, weights HIGH 1.0 / MEDIUM 0.5 / LOW 0.25 / NONE 0. Direction follows the long-thesis adjustment for BUY and is inverted for SELL; HOLD is never adjusted. The model cannot set or widen any of these (config validated; `max_delta <= 0.5`). Unchanged cases return the **original candidate object**. Adjusted candidates get a new deterministic `candidate_id`, the `model_version_id`, and an appended rationale; action, size_hint, instrument, timestamp and snapshot id are untouched; `strategy_version_id` stays the baseline id (the pipeline requires it); the overlay's own identity (`overlay_version_id` = base + model version + config) is journaled.
**Known fact:** in the current Tier-2 / sizing / risk code, `confidence` is not an input to sizing or risk (verified by grep and by the integration test that orders/fills are identical with the overlay on). Slice 11 therefore changes recorded confidence, not simulated outcomes. Whether any downstream consumer should ever use confidence is a separate decision for a later slice.

## 6. Providers and configuration
- `StubProvider` (offline, deterministic, labelled STUB) is used by every test.
- `AnthropicProvider` (`model_providers/`): direct HTTPS Messages API via the standard library; `temperature=0`; no `tools` key. Env: `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (no default model is assumed). Needs **separately authorised Anthropic Console API credentials**; a Claude.ai Pro/Max subscription is not API access and Claude Code CLI is not used as the runtime. The key is never logged, printed, persisted, journaled or exposed to the frontend; `repr` redacts it; HTTP bodies are not echoed in errors. The journal's redactor masks any key containing "token", so usage is journaled as `usage_input_units`/`usage_output_units`.
- Runtime states: disabled => no call; enabled without credentials => `UNAVAILABLE`; timeout => `TIMEOUT`; HTTP 429 => bounded retry (default 2) then `RATE_LIMITED`; malformed output => `MALFORMED_OUTPUT`; request/token budget reached => `BUDGET_EXHAUSTED`; empty context => `EMPTY_CONTEXT` (no call). All preserve baseline behaviour.
- Cost is computed only when the operator supplies a `Pricing` object with a verified note; otherwise it is `None` ("not computed"). No price was assumed.
- Manual real call: `python3 scripts/slice11_smoke.py --provider anthropic ...` (one request by default). **Not performed in this slice.**

## 6a. Budget handling
`SignalConfig.max_requests` (default 50 per service instance) and optional `max_total_tokens` stop further provider calls. Set an Anthropic Console spend limit as the real control; the code limit is a second guard.

## 7. ModelVersion and contamination
`ModelVersion`'s default `version_id` hashes only (backbone, prompt hash) — two models with different cutoffs/parents would collide. Changing that default would re-identify old artifacts, so it is **left unchanged** (tested as legacy behaviour) and `build_model_version` passes an explicit id over provider+model, prompt hash, schema version, cutoff, cutoff basis and parent strategy. `CutoffDeclaration` requires a date **and a source note**; an unknown cutoff is stored as the far-future sentinel `9999-12-31`, so it fails closed. **No model cutoff date was invented or looked up in this slice**; the operator must take it from authoritative provider documentation. `research/contamination/model_cutoff.py`: a test window starting on/before the cutoff is `EXPLORATORY_ONLY`, and `enforce_confirmatory` raises `CONTAMINATION`.

## 8. Journal
New additive event `AI_SIGNAL_EVALUATED` (per candidate, only when the strategy exposes `provenance_for`). Records: candidate id, applied flag and reason, original/adjusted confidence, original action/size hint, baseline and overlay version ids, model version id, adjustment config, label, and the full signal record (context hash, snapshot id, document ids, provider/model/prompt/schema, timestamps, attempts, usage units, cost if any, response hash, validated interpretation, status/detail). No key or header is stored. If source terms forbid retaining text, store hashes/references only; replay then needs the operator's copy.

## 9. Console
`GET /api/runs/{id}/ai-signals` (read-only) derives everything from journal events; the command-centre run page shows an "AI research signal" panel labelled RESEARCH SIGNAL ONLY. A run with no AI events shows AI-DISABLED / provider DISABLED / source NOT_CONNECTED. A stub run is shown as "no real model was called". No thinking indicator, no buttons, no secrets.

## 10. Governance dependency (Slice 13)
Not implemented here. See `docs/slice-13-governance-adjustment.md`.

## 11. Known limitations
- No real disclosure source is connected (no verified, terms-reviewed online source exists to NetOS). Coverage of announcements is whatever the operator imports.
- No real provider call, no real documents, no live smoke test were run.
- The NSE bhavcopy adapter is still validated only against hand-authored fixtures; this slice says nothing about the price-history pipeline.
- Confidence is not consumed by sizing/risk, so the overlay cannot alter simulated P&L today.
- Default adjustment parameters are placeholders.
- Cutoff for any real model is operator-supplied and unverified by NetOS.


---
# Acceptance closure (2026-11-07) and NVIDIA provider

## A. Exact FeatureSnapshot provenance
`adjust_candidate` now requires `SignalRecord.input_snapshot_id == CandidateTrade.input_snapshot_id`. Absent on either side => `SNAPSHOT_REFERENCE_MISSING`; different => `SNAPSHOT_REFERENCE_MISMATCH`. In both cases the **original candidate object is returned unchanged** and the reason is journaled (`outcome_reason`). A snapshot is never inferred from instrument + timestamp. `SignalStore` still looks up by (instrument, timestamp); the overlay's check is the enforcement point (tested with two candidates sharing instrument and timestamp but different snapshots).

## B. Model-cutoff contamination is in the enforced evaluation path
`ResearchEvaluationService.evaluate(..., model_version=None, model_provenance=None)` now detects an AI-enabled strategy (it exposes `model_version`, `provenance_for`, or the caller supplies model metadata) and calls `research.contamination.model_cutoff.assess_ai_model`. The evaluation is `EXPLORATORY_ONLY` (added to the existing downgrade reasons, prefixed `AI_MODEL:`) when: the ModelVersion is unlinked; provenance is missing, for a different ModelVersion, or inconsistent with `knowledge_cutoff`; the cutoff basis is UNKNOWN/undeclared or lacks a date or source note; or the test window starts on/before the cutoff. Persisted in the report under `ai_model_provenance`: model version id, backbone identifier, cutoff basis, cutoff date, cutoff source note, ModelVersion cutoff, test start, evaluation class and reasons. Non-AI evaluations skip all of this: their reports contain no such key and their validity semantics are unchanged (all Slice 9 tests pass unmodified). No cutoff date is invented; the synthetic dates in tests are labelled SYNTHETIC.
Limitation: the declaration (`CutoffDeclaration`) is operator-supplied and its truth is not verified by NetOS.

## C. Prompt serialization hardening (`disclosure_classification_prompt_v2`)
Document text, titles, ids, the instrument id and the timestamp are HTML/XML-escaped (`& < > " '`) and control characters are dropped before rendering; truncation (4000 chars/document, 120 chars/title) is applied to the raw text first. A source document therefore cannot emit a raw `</document>`, open a new element, or forge a system/developer block (tested with closing delimiters, fake system/developer text, tags, JSON-like instructions and quantity/risk/broker requests). The system prompt states the escaping convention. Schema, limits, capabilities (no tools) and output validation are unchanged. The prompt hash (and therefore ModelVersion ids) changed with the template id; this is intended and distinguishable.

## D. Requested vs returned model identifier
`SignalRecord` keeps `model_identifier` (= requested/configured, possibly an alias) and `resolved_model_identifier` (what the provider returned) with `resolved_model_identifier_status` = `RETURNED` | `UNAVAILABLE` | `NOT_CALLED`. If the provider returns none, the resolved id is `None` and marked unavailable; the configured id is never copied into it. Both appear in the journal payload and in the console panel.

## E. NVIDIA hosted provider (`model_providers/nvidia_provider.py`)
- **Status: implemented and unit-tested against mocked transports only. No real call has been made. The endpoint and model ids below were supplied by the operator and are not verified by this build (no network/credentials).**
- Endpoint: `POST <NVIDIA_BASE_URL>/chat/completions`; default base `https://integrate.api.nvidia.com/v1` (https required, no credentials/query in the URL). Auth: `Authorization: Bearer $NVIDIA_API_KEY`, server-side only.
- Env: `NVIDIA_API_KEY` (required), `NVIDIA_MODEL` (default candidate `moonshotai/kimi-k2-instruct`; `moonshotai/kimi-k2-thinking` supported by setting it), `NVIDIA_BASE_URL`.
- Request: system+user messages, `temperature` 0, `stream` false, **no tools / tool_choice**. Same prompt, same schema validation, same `SignalService` timeout, bounded-retry, request/token-budget and failure-to-NO_SIGNAL handling, same journal provenance.
- Response: `choices[0].message.content`; returned `model` and `usage` (`prompt_tokens`/`completion_tokens`) retained. For thinking models a leading inline `<think>…</think>` block is discarded and a separate `reasoning_content` field is never read or stored. Thinking models may need a larger `max_output_tokens`; a truncated/invalid answer is rejected (MALFORMED_OUTPUT), never accepted.
- Cost: not computed unless the operator supplies verified `Pricing`. Limits, pricing, availability and terms are the operator's to confirm.
- **Selection is explicit** (`model_providers/factory.select_provider`): `stub` | `anthropic` | `nvidia`. There is no default real provider and no fallback; a missing key for the chosen provider stops with `UNAVAILABLE` and nothing else is tried. The signal service never switches providers.
- Smoke test (manual only): `python3 scripts/slice11_smoke.py --provider nvidia --confirm-live --disclosures <file> --instrument <id> --decision-time <iso> --isin-map ...` — exits 0 only if a schema-valid classification was returned (`classification_confirmed: true`); exits 1 on any failed call; 2 if not confirmed/configured. **Not run.**
