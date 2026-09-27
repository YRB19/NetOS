# Dependency Decisions

## Slice 3

No new third-party dependencies were added. Slice 3 (feature/context
formation + Tier-1 baseline) is implemented entirely with the Python
standard library (`dataclasses`, `enum`, `datetime`, `hashlib`, `json`,
`csv`, `io`, `uuid`, `ast`, `unittest`), consistent with the repository's
existing constraint (no network access in this sandbox, so `pytest`,
`ruff`, and `mypy` remain unavailable — `unittest` is used for all
tests, per prior-session findings preserved in project memory).

No dependency was considered and rejected for this slice specifically;
the slice's scope (deterministic data structures and a deterministic
strategy) does not call for anything beyond stdlib.
