# Roadmap adjustment — Governance folded into Slice 13 (owner decision)

**Source caveat (re-checked 2026-11-07):** the owner states `NetOS_Post_Slice_7_Roadmap(2).md` was supplied separately, but it is **not in this workspace and not in the repository** (only `NetOS_3.zip` was uploaded; a filesystem search found no such file). This is therefore an addendum, not a line-by-line reconciliation, and the roadmap is not claimed to be stored in the repo. Slice numbering is unchanged. Slice 12 (AI-vs-Baseline Evaluation) is **not** modified and may not be skipped.

## Slice 13 is now: **Governance & Promotion Prerequisites + Paper-Trading Harness**
Before any paper session can start, Slice 13 must implement and verify:
1. Operator-owned autonomy-level state and permissions.
2. Append-only autonomy transitions.
3. Explicit operator approval for promotion; no automatic or self-authorized promotion.
4. Research artifacts kept separate from the active strategy configuration.
5. Governance-owned configuration boundaries.
6. Operator-only kill-switch control with deterministic enforcement.
7. Paper-mode isolation and a startup preflight.
8. Tests proving no LLM or research process can modify risk settings, grant itself autonomy, or activate a promoted strategy without operator authorization.

These are prerequisites, **not** deferred to Slice 18. Slice 11 implements none of them; it only documents the dependency. Consequence for Slice 11 artifacts: `DisclosureOverlayStrategy`/`ModelVersion` have no promotion path today — nothing activates them except an explicit composition by the operator.
