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

Cost schedule `india-equity-v1-unverified` remains `verified=False`.
See `repository-integration.md`. Historical reports: `history/slice1..4/`.
