"""Slice 8 — decision journal core. SYNTHETIC infrastructure tests; no trading evidence."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from observability.decision_log.events import (
    SCHEMA_VERSION,
    ErrorCode,
    EventType,
    JournalError,
    event_from_dict,
)
from observability.decision_log.journal import (
    FileDecisionJournal,
    InMemoryJournal,
    journal_path,
    read_journal_file,
)
from observability.decision_log.query import JournalReader
from observability.decision_log.redaction import REDACTED, sanitize, sanitize_text

T0 = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
CLOCK = lambda: T0  # noqa: E731


def put(j, i: int, payload: dict | None = None, et=EventType.OPERATIONAL_FAILURE, did="d1", **kw):
    return j.append(et, f"evt_{i}", payload or {"error_code": "X", "message": f"m{i}"}, decision_id=did,
                    correlation_id="c", producer="t", producer_version="1", event_time=T0, **kw)  # fmt: skip


class FailingFile(FileDecisionJournal):
    def __init__(self, *a, fail_on_n: int, **k):
        super().__init__(*a, **k)
        self.n, self.fail_on_n = 0, fail_on_n

    def _persist(self, line):
        self.n += 1
        if self.n == self.fail_on_n:
            raise OSError("disk full")
        super()._persist(line)


class AppendSemantics(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_chain_sequence_and_reopen(self):
        j = FileDecisionJournal(self.d, "run_a", CLOCK)
        for i in range(1, 4):
            put(j, i)
        self.assertEqual([e.sequence for e in j.events()], [1, 2, 3])
        j2 = FileDecisionJournal(self.d, "run_a", CLOCK)
        self.assertEqual(j2.head_hash, j.head_hash)
        put(j2, 4)
        self.assertEqual(j2.events()[-1].sequence, 4)
        self.assertTrue(j2.verify().ok)

    def test_same_id_same_payload_is_a_noop_and_recorded_time_is_ignored(self):
        t = [T0]
        j = InMemoryJournal("r", lambda: t[0])
        a = put(j, 1)
        t[0] = datetime(2027, 1, 1, tzinfo=UTC)
        b = put(j, 1)
        self.assertIs(a, b)
        self.assertEqual(len(j.events()), 1)

    def test_same_id_different_payload_is_a_conflict(self):
        j = InMemoryJournal("r", CLOCK)
        put(j, 1)
        with self.assertRaises(JournalError) as cm:
            put(j, 1, {"error_code": "X", "message": "different"})
        self.assertIs(cm.exception.code, ErrorCode.JOURNAL_EVENT_CONFLICT)
        self.assertEqual(len(j.events()), 1)

    def test_distinct_ids_with_identical_payloads_stay_distinct(self):
        j = InMemoryJournal("r", CLOCK)
        same = {"error_code": "X", "message": "same"}
        a, b = put(j, 1, same), put(j, 2, same)
        self.assertEqual(a.payload, b.payload)
        self.assertEqual(len(j.events()), 2)
        self.assertNotEqual(a.event_hash, b.event_hash)

    def test_deterministic_hashes_with_fixed_clock_and_material_change_changes_hash(self):
        a, b, c = (InMemoryJournal("r", CLOCK) for _ in range(3))
        for j in (a, b):
            put(j, 1), put(j, 2)
        put(c, 1), put(c, 2, {"error_code": "X", "message": "CHANGED"})
        self.assertEqual([e.event_hash for e in a.events()], [e.event_hash for e in b.events()])
        self.assertNotEqual(a.events()[1].event_hash, c.events()[1].event_hash)

    def test_required_payload_keys_enforced(self):
        j = InMemoryJournal("r", CLOCK)
        with self.assertRaises(JournalError) as cm:
            j.append(EventType.FILL_RECORDED, "e", {"fill_id": "f"}, correlation_id="c", producer="p", producer_version="1")
        self.assertIs(cm.exception.code, ErrorCode.JOURNAL_INVALID_EVENT)

    def test_times_are_distinct_and_unknown_stays_unknown(self):
        j = InMemoryJournal("r", lambda: datetime(2026, 2, 2, tzinfo=UTC))
        e = j.append(EventType.OPERATIONAL_FAILURE, "e", {"error_code": "X", "message": "m"},
                     correlation_id="c", producer="p", producer_version="1")  # no event_time / data_available_at
        self.assertIsNone(e.event_time)
        self.assertIsNone(e.data_available_at)
        self.assertTrue(e.recorded_at.startswith("2026-02-02"))
        e2 = put(j, 9)
        self.assertNotEqual(e2.event_time, e2.recorded_at)

    def test_correction_is_a_new_event_and_original_is_unchanged(self):
        j = FileDecisionJournal(self.d, "r", CLOCK)
        orig = put(j, 1)
        before = journal_path(self.d, "r").read_text().splitlines()[0]
        j.append(EventType.CORRECTION, "evt_c", {"corrects_event_id": orig.event_id, "reason": "typo"},
                 correlation_id="c", producer="t", producer_version="1")
        self.assertEqual(journal_path(self.d, "r").read_text().splitlines()[0], before)
        self.assertEqual(len(j.events()), 2)


class WriteFailure(unittest.TestCase):
    def test_failed_write_is_visible_and_journal_refuses_further_appends(self):
        d = tempfile.mkdtemp()
        j = FailingFile(d, "r", CLOCK, fail_on_n=2)
        put(j, 1)
        with self.assertRaises(JournalError) as cm:
            put(j, 2)
        self.assertIs(cm.exception.code, ErrorCode.JOURNAL_WRITE_FAILED)
        self.assertEqual(len(j.events()), 1)  # no fabricated success
        with self.assertRaises(JournalError) as cm2:
            put(j, 3)
        self.assertIs(cm2.exception.code, ErrorCode.JOURNAL_CLOSED_AFTER_FAILURE)
        self.assertEqual(j.append_failures, 1)


class CorruptionDetection(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        j = FileDecisionJournal(self.d, "r", CLOCK)
        for i in range(1, 5):
            put(j, i)
        self.path = journal_path(self.d, "r")
        self.lines = self.path.read_text().splitlines()

    def codes(self, text: str | bytes) -> set[str]:
        self.path.write_bytes(text if isinstance(text, bytes) else text.encode())
        return {c for c, _ in read_journal_file(self.path)[1].errors}

    def test_clean_journal_verifies(self):
        self.assertTrue(read_journal_file(self.path)[1].ok)

    def test_tampered_payload_fails_hash(self):
        bad = json.loads(self.lines[1])
        bad["payload"]["message"] = "forged"
        self.lines[1] = json.dumps(bad)
        self.assertIn("JOURNAL_HASH_MISMATCH", self.codes("\n".join(self.lines) + "\n"))

    def test_missing_event_is_a_sequence_gap(self):
        del self.lines[1]
        self.assertIn("JOURNAL_SEQUENCE_GAP", self.codes("\n".join(self.lines) + "\n"))

    def test_malformed_json_line(self):
        self.lines[2] = "{not json"
        self.assertIn("JOURNAL_CORRUPT", self.codes("\n".join(self.lines) + "\n"))

    def test_truncated_tail(self):
        raw = ("\n".join(self.lines) + "\n").encode()[:-25]
        self.assertIn("JOURNAL_CORRUPT", self.codes(raw))

    def test_duplicate_event_id(self):
        self.assertIn("JOURNAL_DUPLICATE_EVENT_ID", self.codes("\n".join(self.lines + [self.lines[0]]) + "\n"))

    def test_reopen_of_corrupt_journal_fails_closed_without_repair(self):
        raw = ("\n".join(self.lines) + "\n").encode()[:-25]
        self.path.write_bytes(raw)
        with self.assertRaises(JournalError):
            FileDecisionJournal(self.d, "r", CLOCK)
        self.assertEqual(self.path.read_bytes(), raw)  # not silently truncated/repaired
        with self.assertRaises(JournalError):
            JournalReader.from_file(self.d, "r")

    def test_unsupported_schema_version_is_a_clear_error(self):
        d = json.loads(self.lines[0])
        d["schema_version"] = 99
        with self.assertRaises(JournalError) as cm:
            event_from_dict(d)
        self.assertIs(cm.exception.code, ErrorCode.JOURNAL_UNSUPPORTED_SCHEMA)
        self.assertEqual(SCHEMA_VERSION, 1)


class VerifyCommand(unittest.TestCase):
    def test_cli_reports_ok_then_failure_without_repairing(self):
        import subprocess
        import sys

        d = tempfile.mkdtemp()
        j = FileDecisionJournal(d, "r", CLOCK)
        put(j, 1), put(j, 2)
        root = Path(__file__).resolve().parents[2]
        run = lambda: subprocess.run([sys.executable, "-m", "observability.decision_log.verify", d, "r"],  # noqa: E731
                                     capture_output=True, text=True, cwd=root)
        self.assertEqual(run().returncode, 0)
        p = journal_path(d, "r")
        p.write_bytes(p.read_bytes()[:-10])
        out = run()
        self.assertEqual(out.returncode, 1)
        self.assertIn("JOURNAL_CORRUPT", out.stdout)


class Redaction(unittest.TestCase):
    FAKE = ["sk-FAKEFAKEFAKE12345678", "Bearer abcdef1234567890XYZ", "hunter2-supersecret"]

    def test_secrets_never_reach_file_or_errors(self):
        d = tempfile.mkdtemp()
        j = FileDecisionJournal(d, "r", CLOCK)
        j.append(EventType.OPERATIONAL_FAILURE, "e1",
                 {"error_code": "X", "message": f"call failed with {self.FAKE[1]} and token={self.FAKE[0]}",
                  "api_token": self.FAKE[0], "nested": {"password": self.FAKE[2]}},
                 correlation_id="c", producer="p", producer_version="1")  # fmt: skip
        text = journal_path(d, "r").read_text()
        for s in self.FAKE:
            self.assertNotIn(s, text)
        self.assertIn(REDACTED, text)
        err = str(JournalError(ErrorCode.JOURNAL_WRITE_FAILED, f"boom {self.FAKE[1]}"))
        self.assertNotIn(self.FAKE[1].split()[1], err)

    def test_sanitize_is_bounded_and_pure(self):
        src = {"a": "x" * 5000}
        out = sanitize(src)
        self.assertLess(len(out["a"]), 2100)
        self.assertEqual(len(src["a"]), 5000)
        self.assertEqual(sanitize_text("Authorization: Bearer abcdefgh12345678"), REDACTED)


class QueryLayer(unittest.TestCase):
    def test_pagination_is_stable_and_bounded_and_missing_ids_are_explicit(self):
        j = InMemoryJournal("r", CLOCK)
        for i in range(5):
            j.append(EventType.DECISION_STARTED, f"s{i}", {"instrument_id": f"I{i}", "cycle_timestamp": T0, "run_context": {}},
                     decision_id=f"d{i}", correlation_id="c", producer="p", producer_version="1")  # fmt: skip
        r = JournalReader.from_journal(j)
        a = [x.decision_id for x in r.list_decisions(2, 0)] + [x.decision_id for x in r.list_decisions(2, 2)] \
            + [x.decision_id for x in r.list_decisions(2, 4)]  # fmt: skip
        self.assertEqual(a, [f"d{i}" for i in range(5)])
        self.assertEqual([x.status for x in r.list_decisions()], ["INCOMPLETE"] * 5)
        with self.assertRaises(JournalError):
            r.list_decisions(0)
        with self.assertRaises(JournalError) as cm:
            r.get_event("nope")
        self.assertIs(cm.exception.code, ErrorCode.JOURNAL_NOT_FOUND)
        with self.assertRaises(JournalError):
            r.decision_chain("nope")

    def test_reader_is_read_only_and_imports_no_execution_code(self):
        import subprocess
        import sys

        public = {n for n in dir(JournalReader) if not n.startswith("_")}
        self.assertFalse({n for n in public if n.startswith(("append", "write", "delete", "update", "set", "resolve", "submit"))})
        code = ("import sys; import observability.decision_log.query;"
                "bad=[m for m in sys.modules if m.split('.')[0] in ('risk_execution','simulation','intelligence','governance')];"
                "print(bad)")  # fmt: skip
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[2])
        self.assertEqual(out.stdout.strip(), "[]", out.stderr)


if __name__ == "__main__":
    unittest.main()
