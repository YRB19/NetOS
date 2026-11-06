"""Disclosure source interface (Slice 11, Plane 1).

A source yields RAW disclosure items (plain dicts) plus an honest status. No online exchange
source is verified for Slice 11, so the only implemented source is the operator local-file import
(`data.adapters.disclosure_local_import`). A real-time feed is reported `NOT_CONNECTED`; NetOS does
not invent an NSE/BSE API and does not scrape.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum
from typing import Protocol


class SourceStatus(str, Enum):  # noqa: UP042
    NOT_CONNECTED = "NOT_CONNECTED"
    LOCAL_IMPORT = "LOCAL_IMPORT"  # operator-supplied files, no live feed
    CONNECTED = "CONNECTED"  # reserved: only after a verified, terms-reviewed online source exists


class DisclosureSource(Protocol):
    source_id: str

    def status(self) -> SourceStatus: ...

    def read_raw(self) -> Iterable[dict]: ...


class NotConnectedSource:
    """The honest default for the real-time feed."""

    source_id = "EXCHANGE_FEED"

    def status(self) -> SourceStatus:
        return SourceStatus.NOT_CONNECTED

    def read_raw(self) -> Iterable[dict]:
        return ()
