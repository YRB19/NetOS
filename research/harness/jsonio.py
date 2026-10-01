"""Deterministic JSON encoding for research artifacts (Decimal-safe, sorted keys)."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from enum import Enum

from shared.time.clock import ensure_utc


def jsonable(obj: object) -> object:
    if obj is None or isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        return repr(obj)  # exact & deterministic; floats only appear in domain objects
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return ensure_utc(obj).isoformat()
    if isinstance(obj, Mapping):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, frozenset, set)):
        items = sorted(obj, key=str) if isinstance(obj, (frozenset, set)) else obj
        return [jsonable(v) for v in items]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out = {"__type__": type(obj).__qualname__}
        for f in dataclasses.fields(obj):
            if not f.name.startswith("_"):
                out[f.name] = jsonable(getattr(obj, f.name))
        return out
    raise TypeError(f"cannot JSON-encode {type(obj)!r}")


def dumps(obj: object, *, indent: int | None = 2) -> str:
    return json.dumps(jsonable(obj), sort_keys=True, indent=indent, ensure_ascii=False) + "\n"
