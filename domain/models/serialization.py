"""Deterministic serialization for domain models (Stage 3 §2's "clear
deterministic serialization representation suitable for future database
persistence, JSON, DecisionRecord reconstruction, testing, and experiment
storage").

Design: a small, generic, recursive (de)serializer built directly on
`dataclasses` + `typing`, rather than a third-party schema/serialization
library — this is a deliberate "dependency-sprawl discipline" (Stage 2
Principle 1 / Stage 3 §22) choice appropriate to this slice's scope. It
covers every shape actually used by the domain models in this package:
dataclasses (frozen or not), Enums, timezone-aware datetimes, tuples,
plain dicts / MappingProxyType, and Optional[...] / X | None fields.

`to_serializable(obj)` produces plain JSON-safe Python primitives
(dict/list/str/float/int/bool/None) — suitable for `json.dumps` directly.

`from_serializable(cls, data)` reconstructs an instance of `cls` from that
same shape, driven by `cls`'s own dataclass field type hints — so a model
gains round-trip support automatically as long as it's a normal dataclass
with type-hinted fields, no per-model boilerplate required.
"""

from __future__ import annotations

import dataclasses
import typing
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from types import MappingProxyType, NoneType, UnionType

from shared.time.clock import ensure_utc


def to_serializable(obj: object) -> object:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return ensure_utc(obj).isoformat()
    if isinstance(obj, Mapping):
        return {k: to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_serializable(v) for v in obj]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        result: dict[str, object] = {"__type__": type(obj).__qualname__}
        for f in dataclasses.fields(obj):
            if f.name.startswith("_"):
                continue  # internal bookkeeping fields (e.g. Order._state_history's backing list)
            result[f.name] = to_serializable(getattr(obj, f.name))
        # Order.state_history is a computed property backed by the private
        # _state_history field skipped above; include it explicitly so
        # serialization doesn't silently lose the audit trail.
        if hasattr(obj, "state_history") and "state_history" not in result:
            result["state_history"] = to_serializable(obj.state_history)
        return result
    raise TypeError(f"Don't know how to serialize object of type {type(obj)!r}: {obj!r}")


def _unwrap_optional(tp: object) -> tuple[object, bool]:
    """Return (inner_type, was_optional) for `X | None` / `Optional[X]`."""
    origin = typing.get_origin(tp)
    if origin is UnionType or origin is typing.Union:
        args = [a for a in typing.get_args(tp) if a is not NoneType]
        if len(args) == 1:
            return args[0], True
    return tp, False


def _from_value(tp: object, value: object) -> object:
    tp, was_optional = _unwrap_optional(tp)
    if was_optional and value is None:
        return None

    origin = typing.get_origin(tp)

    if tp is datetime:
        assert isinstance(value, str)
        return ensure_utc(datetime.fromisoformat(value))

    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(value)

    if origin in (tuple, list):
        args = typing.get_args(tp)
        elem_type = args[0] if args else object
        assert isinstance(value, list)
        return tuple(_from_value(elem_type, v) for v in value)

    if origin is dict or tp in (dict, MappingProxyType) or origin is MappingProxyType:
        assert isinstance(value, Mapping)
        args = typing.get_args(tp)
        val_type = args[1] if len(args) == 2 else object
        return {k: _from_value(val_type, v) for k, v in value.items()}

    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        assert isinstance(value, Mapping)
        return from_serializable(tp, value)

    return value


def from_serializable(cls: type, data: Mapping) -> object:
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name.startswith("_"):
            continue
        if f.name not in data:
            continue  # let the dataclass's own default apply
        kwargs[f.name] = _from_value(hints[f.name], data[f.name])
    return cls(**kwargs)


def order_from_serializable(data: Mapping) -> object:
    """Reconstruct an `Order` from its serialized form.

    `Order` cannot go through the generic `from_serializable` path: its
    `__post_init__` deliberately forbids constructing anything other than
    a fresh CANDIDATE-state order (see order.py's docstring — this is what
    guarantees every transition is audit-trailed). Reconstruction therefore
    means: build a fresh Order, then replay its recorded transition history
    exactly, which both restores the correct final state AND proves the
    stored history is itself a legal transition sequence.
    """
    from domain.models.order import Order, StateTransitionRecord

    order = Order(order_request_id=data["order_request_id"], order_id=data["order_id"])
    if data.get("broker_order_id"):
        order.set_broker_order_id(data["broker_order_id"])
    for record_data in data.get("state_history", []):
        record = from_serializable(StateTransitionRecord, record_data)
        assert isinstance(record, StateTransitionRecord)
        order.transition_to(record.to_state, detail=record.detail, at=record.at)
    return order
