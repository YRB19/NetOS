"""Typed, explicit API errors. Messages never contain local filesystem paths or secrets."""

from __future__ import annotations

import re

from observability.decision_log.redaction import sanitize_text

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-@=]{0,127}$")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: dict | None = None) -> None:
        self.status, self.code, self.detail = status, code, detail or {}
        self.message = sanitize_text(message)
        super().__init__(f"{code}: {self.message}")

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "detail": self.detail}}


def valid_id(value: str, kind: str = "id") -> str:
    """Identifiers are an allow-listed charset: no separators, no '..', no NUL, bounded length."""
    if not isinstance(value, str) or not _ID.match(value) or ".." in value:
        raise ApiError(400, "INVALID_IDENTIFIER", f"invalid {kind}")
    return value


def page_args(q: dict, default: int = 50, maximum: int = 500) -> tuple[int, int]:
    try:
        limit = int(q.get("limit", default))
        offset = int(q.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError(400, "INVALID_PAGINATION", "limit and offset must be integers") from None
    if limit < 1 or limit > maximum or offset < 0:
        raise ApiError(400, "INVALID_PAGINATION", f"limit must be 1..{maximum} and offset >= 0")
    return limit, offset
