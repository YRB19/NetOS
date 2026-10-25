"""Secret/privacy protection for journal payloads, logs and exception text (Slice 8).

Allow-list stance: producers build payloads from typed domain objects, never from raw provider
responses or request headers. This module is the second line of defence: it removes values stored
under sensitive KEYS and masks token-like substrings in free text, then bounds text length.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

REDACTED = "[REDACTED]"
MAX_TEXT = 500
_SENSITIVE_KEY = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|credential|cookie|private[_-]?key|"
    r"access[_-]?key|client[_-]?secret|totp|pin\b|session)", re.IGNORECASE)  # fmt: skip
_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?token|authorization)\s*[=:]\s*\S+"),
    re.compile(r"\b[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b"),  # JWT-shaped
    re.compile(r"\b(sk|pk|ak|tok|key)[-_][A-Za-z0-9]{12,}\b"),
)


def sanitize_text(text: object, limit: int = MAX_TEXT) -> str:
    s = str(text)
    for pat in _TEXT_PATTERNS:
        s = pat.sub(REDACTED, s)
    return s if len(s) <= limit else s[:limit] + "...[truncated]"


def sanitize(obj: object, _depth: int = 0) -> object:
    """Recursively redact sensitive keys and mask token-like text. Pure; returns a new structure."""
    if _depth > 20:
        return REDACTED
    if isinstance(obj, Mapping):
        return {str(k): (REDACTED if _SENSITIVE_KEY.search(str(k)) else sanitize(v, _depth + 1)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v, _depth + 1) for v in obj]
    if isinstance(obj, str):
        return sanitize_text(obj, 2000)
    return obj
