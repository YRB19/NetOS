"""Paper-only endpoint policy and credential hygiene. Live endpoints are structurally unreachable."""

from __future__ import annotations

from dataclasses import dataclass
import re


class LiveEndpointRefused(Exception):  # noqa: N818
    pass


@dataclass(frozen=True)
class PaperEndpointPolicy:
    """Exact-host allowlist supplied by the operator. Default (empty) means NOT_CONFIGURED."""

    allowed_hosts: frozenset[str] = frozenset()

    def check(self, url: str) -> str:
        m = re.fullmatch(r"https://([A-Za-z0-9.-]+)(?::443)?(?:/[^\s@]*)?", url)
        if m is None:  # rejects http, userinfo (@), odd ports, whitespace, missing host
            raise LiveEndpointRefused("endpoint must be a plain https URL with a host")
        host = m.group(1).lower()
        if host not in {h.lower() for h in self.allowed_hosts}:
            raise LiveEndpointRefused(f"host {host!r} is not on the paper-endpoint allowlist")
        return url

    @property
    def configured(self) -> bool:
        return bool(self.allowed_hosts)


@dataclass(frozen=True)
class PaperCredentials:
    key_id: str
    secret: str

    def __repr__(self) -> str:  # never leak into logs/reports
        return "PaperCredentials(key_id=***, secret=***)"

    __str__ = __repr__
