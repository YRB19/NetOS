"""Read-only artifact locator + cached journal access.

Artifact directory convention (documented in docs/operator-console.md):
    <root>/runs/<run_id>/...            research artifacts (+ pipeline/ sub-directory)  [Slice 5/6]
    <root>/journals/<run_id>/journal.jsonl   decision journal (also accepted: <root>/<run_id>/journal.jsonl)  [Slice 8]
    <root>/validity/<run_id>/report*.json    evaluation reports                          [Slice 9]
    <root>/protocols/, <root>/trials/ledger.jsonl, <root>/holdouts/                        [Slice 9]
    <root>/DEMO_MARKER.json             present only for the synthetic demo set
Nothing here writes, creates or repairs anything.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

from console_api.errors import ApiError, valid_id
from observability.decision_log.events import ErrorCode, JournalError, JournalEvent
from observability.decision_log.journal import VerificationReport, journal_path, read_journal_file
from observability.decision_log.query import JournalReader


@dataclass
class LoadedJournal:
    run_id: str
    reader: JournalReader | None
    report: VerificationReport | None
    error: dict | None  # explicit state when unreadable

    @property
    def verified(self) -> bool:
        return self.report is not None and self.report.ok and self.error is None


class ArtifactStore:
    def __init__(self, root: Path | str) -> None:
        p = Path(root)
        if not p.is_dir():
            raise ApiError(
                500, "ARTIFACT_ROOT_UNAVAILABLE", "artifact root is not an existing directory"
            )
        self.root = p.resolve()
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[tuple, LoadedJournal]] = {}
        marker = self.root / "DEMO_MARKER.json"
        self.demo = False
        self.demo_info: dict | None = None
        if marker.is_file():
            self.demo = True
            try:
                self.demo_info = json.loads(marker.read_text(encoding="utf-8"))
            except ValueError:
                self.demo_info = {"warning": "demo marker unreadable"}

    # ---- safe path helpers --------------------------------------------------
    def _safe(self, *parts: str) -> Path:
        p = self.root.joinpath(*parts).resolve()
        if p != self.root and self.root not in p.parents:
            raise ApiError(400, "INVALID_IDENTIFIER", "path escapes the artifact root")
        return p

    def run_dir(self, run_id: str) -> Path:
        return self._safe("runs", valid_id(run_id, "run_id"))

    def read_json(self, path: Path) -> dict | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (ValueError, OSError):
            return {"__unreadable__": True}

    def read_jsonl(self, path: Path, limit: int | None = None) -> tuple[list[dict], bool]:
        """(rows, ok). ok=False if any line is unparseable or the file is unreadable."""
        rows: list[dict] = []
        ok = True
        try:
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        ok = False
                    if limit is not None and len(rows) >= limit:
                        break
        except FileNotFoundError:
            return [], True
        except OSError:
            return [], False
        return rows, ok

    # ---- discovery ----------------------------------------------------------
    def journal_file(self, run_id: str) -> Path | None:
        rid = valid_id(run_id, "run_id")
        for base in (self.root / "journals", self.root):
            cand = journal_path(base, rid)
            if cand.is_file():
                return cand
        return None

    def run_ids(self) -> list[str]:
        ids: set[str] = set()
        for sub in ("runs",):
            d = self.root / sub
            if d.is_dir():
                ids.update(p.name for p in d.iterdir() if p.is_dir())
        jd = self.root / "journals"
        if jd.is_dir():
            ids.update(p.name for p in jd.iterdir() if (p / "journal.jsonl").is_file())
        vd = self.root / "validity"
        if vd.is_dir():
            ids.update(p.name for p in vd.iterdir() if p.is_dir())
        return sorted(i for i in ids if _ok_id(i))

    # ---- journal ------------------------------------------------------------
    def journal(self, run_id: str) -> LoadedJournal:
        path = self.journal_file(run_id)
        if path is None:
            return LoadedJournal(
                run_id,
                None,
                None,
                {"code": "JOURNAL_NOT_FOUND", "message": "no journal recorded for this run"},
            )
        st = path.stat()
        key = (st.st_mtime_ns, st.st_size)
        with self._lock:
            hit = self._cache.get(run_id)
            if hit and hit[0] == key:
                return hit[1]
        try:
            events, rep = read_journal_file(path)
            lj = LoadedJournal(run_id, JournalReader(events, rep, run_id), rep, None)
        except JournalError as e:
            lj = LoadedJournal(run_id, None, None, {"code": e.code.value, "message": e.message})
        except Exception as e:  # noqa: BLE001 - corrupt input must become an explicit state, never a 500
            lj = LoadedJournal(
                run_id,
                None,
                None,
                {
                    "code": ErrorCode.JOURNAL_CORRUPT.value,
                    "message": f"unreadable journal ({type(e).__name__})",
                },
            )
        with self._lock:
            self._cache[run_id] = (key, lj)
        return lj

    def verified_reader(self, run_id: str, allow_unverified: bool = False) -> LoadedJournal:
        lj = self.journal(run_id)
        if lj.reader is None:
            code = (lj.error or {}).get("code", "JOURNAL_NOT_FOUND")
            raise ApiError(
                404 if code == "JOURNAL_NOT_FOUND" else 422,
                code,
                (lj.error or {}).get("message", "journal unavailable"),
            )
        if not lj.verified and not allow_unverified:
            raise ApiError(
                422,
                "JOURNAL_UNVERIFIED",
                "journal failed integrity verification; contents are not shown "
                "unless allow_unverified=true is requested explicitly",
                {"errors": [list(e) for e in (lj.report.errors if lj.report else ())][:20]},
            )
        return lj


def _ok_id(s: str) -> bool:
    try:
        valid_id(s)
        return True
    except ApiError:
        return False


def event_dict(e: JournalEvent) -> dict:
    d = e.to_dict()
    d["event_type"] = e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type)
    return d
