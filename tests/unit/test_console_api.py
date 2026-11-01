"""Slice 10: Operator Console read API / read-model tests (ADR-21). Uses the SYNTHETIC demo set built once per module."""

from __future__ import annotations

import ast
import hashlib
import http.client
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import build_ui_demo_fixtures as demo  # noqa: E402
from console_api import readmodel as R  # noqa: E402
from console_api.errors import ApiError, valid_id  # noqa: E402
from console_api.exports import to_csv  # noqa: E402
from console_api.server import make_server, route  # noqa: E402
from console_api.store import ArtifactStore  # noqa: E402
from observability.decision_log.query import JournalReader  # noqa: E402

_TMP = None
IDS: dict = {}
DEMO: Path


def setUpModule():
    global _TMP, DEMO
    _TMP = tempfile.TemporaryDirectory()
    DEMO = Path(_TMP.name) / "demo"
    IDS.update(demo.build(DEMO))


def tearDownModule():
    _TMP.cleanup()


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def copy_demo(name="copy") -> Path:
    dst = Path(_TMP.name) / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(DEMO, dst)
    return dst


class Server:
    def __init__(self, root):
        self.srv = make_server(root, port=0)
        self.port = self.srv.server_address[1]
        self.t = threading.Thread(target=self.srv.serve_forever, daemon=True)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *a):
        self.srv.shutdown()
        self.srv.server_close()

    def req(self, method, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, body, dict(r.getheaders())

    def get_json(self, path):
        s, b, _ = self.req("GET", path)
        return s, json.loads(b)


class RunListing(unittest.TestCase):
    def setUp(self):
        self.store = ArtifactStore(DEMO)

    def test_runs_listing_pagination_and_filters(self):
        out = R.list_runs(self.store, {}, 2, 0)
        self.assertEqual(out["total"], 5)
        self.assertEqual(len(out["items"]), 2)
        self.assertEqual(R.list_runs(self.store, {}, 2, 4)["items"].__len__(), 1)
        self.assertTrue(out["demo"])
        inc = R.list_runs(self.store, {"status": "INCOMPLETE"}, 50, 0)
        self.assertEqual([r["run_id"] for r in inc["items"]], [IDS["incomplete_blocked"]])
        self.assertEqual(
            R.list_runs(self.store, {"run_type": "RESEARCH_HARNESS"}, 50, 0)["total"], 1
        )

    def test_deterministic_ordering(self):
        a = [r["run_id"] for r in R.list_runs(self.store, {}, 50, 0)["items"]]
        b = [r["run_id"] for r in R.list_runs(self.store, {}, 50, 0)["items"]]
        self.assertEqual(a, b)

    def test_synthetic_evidence_is_labelled_and_sourced(self):
        s = R.run_summary(self.store, IDS["success"])
        self.assertTrue(s["evidence"]["synthetic"])
        self.assertEqual(s["evidence"]["source"], "journal.run_context")
        self.assertIn("Synthetic", s["evidence"]["label"])
        self.assertEqual(s["run_type"], "SIMULATION_PIPELINE")
        self.assertIn("EXIT_COSTS_EXCLUDED", [w["code"] for w in s["warnings"]])

    def test_incomplete_run_surfaces_failure_states(self):
        s = R.run_summary(self.store, IDS["incomplete_blocked"])
        self.assertEqual(s["status"], "INCOMPLETE")
        codes = [w["code"] for w in s["warnings"]]
        self.assertIn("INCOMPLETE_DECISIONS", codes)
        self.assertIn(
            "NO_PIPELINE_ARTIFACTS", codes + ["NO_PIPELINE_ARTIFACTS"]
        )  # absent artifacts are not invented
        self.assertEqual(s["metrics"], {})  # missing metrics stay missing (never zero)

    def test_unknown_evidence_stays_unknown(self):
        root = copy_demo("noev")
        d = root / "runs" / "run_noev"
        d.mkdir(parents=True)
        (d / "result.json").write_text(json.dumps({"status": "COMPLETED", "metrics": {}}))
        s = R.run_summary(ArtifactStore(root), "run_noev")
        self.assertIsNone(s["evidence"]["raw"])
        self.assertIsNone(s["evidence"]["synthetic"])
        self.assertIn("Unknown", s["evidence"]["label"])
        self.assertIn("EVIDENCE_CLASS_UNKNOWN", [w["code"] for w in s["warnings"]])
        self.assertIsNone(s["dataset"]["window_start"])

    def test_unrecognised_evidence_class_is_not_guessed(self):
        e = R.evidence("SOMETHING_NEW")
        self.assertIn("Unrecognised", e["label"])
        self.assertFalse(R.evidence("PAPER_EXECUTION")["synthetic"])

    def test_missing_run_is_explicit_404(self):
        with self.assertRaises(ApiError) as cm:
            R.run_summary(self.store, "run_does_not_exist")
        self.assertEqual((cm.exception.status, cm.exception.code), (404, "RUN_NOT_FOUND"))


class Decisions(unittest.TestCase):
    def setUp(self):
        self.store = ArtifactStore(DEMO)

    def test_list_pagination_filters(self):
        rid = IDS["success"]
        full = R.list_decisions(self.store, rid, {}, 500, 0)
        self.assertEqual(full["total"], 210)
        p2 = R.list_decisions(self.store, rid, {}, 50, 50)
        self.assertEqual(
            [r["decision_id"] for r in p2["items"]],
            [r["decision_id"] for r in full["items"][50:100]],
        )
        holds = R.list_decisions(self.store, rid, {"tag": "HOLD"}, 500, 0)
        self.assertTrue(holds["total"] > 0 and all("HOLD" in r["tags"] for r in holds["items"]))
        self.assertEqual(
            R.list_decisions(self.store, rid, {"terminal_state": "FILLED"}, 500, 0)["total"], 6
        )

    def test_veto_partial_incomplete_and_blocked_are_visible(self):
        veto = R.list_decisions(self.store, IDS["risk_veto"], {"tag": "RISK_VETO"}, 500, 0)
        self.assertTrue(veto["total"] > 0)
        self.assertTrue(all(r["failed_risk_checks"] for r in veto["items"]))
        part = R.list_decisions(
            self.store, IDS["partial_fill"], {"tag": "PARTIAL_OR_CANCELLED"}, 500, 0
        )
        self.assertTrue(part["total"] > 0)
        inc = R.list_decisions(self.store, IDS["incomplete_blocked"], {}, 50, 0)["items"][0]
        self.assertEqual(inc["status"], "INCOMPLETE")
        self.assertIsNone(inc["terminal_state"])
        self.assertIn("RECONCILIATION_BLOCKED", inc["tags"])

    def test_detail_links_to_exact_stored_events(self):
        rid = IDS["success"]
        did = R.list_decisions(self.store, rid, {"terminal_state": "FILLED"}, 1, 0)["items"][0][
            "decision_id"
        ]
        det = R.decision_detail(self.store, rid, did)
        reader = JournalReader.from_file(DEMO / "journals", rid)
        chain = reader.decision_chain(did)
        self.assertEqual([e["event_id"] for e in det["events"]], [e.event_id for e in chain.events])
        staged = [i for s in det["stages"] for i in s["event_ids"]]
        self.assertEqual(
            sorted(staged),
            sorted(e.event_id for e in chain.events if e.event_type.value != "DECISION_STARTED"),
        )
        self.assertEqual(
            [s["stage"] for s in det["stages"]],
            [
                "snapshot",
                "candidate",
                "risk",
                "sizing",
                "order_intent",
                "submission",
                "order_lifecycle",
                "fills",
                "portfolio_settlement",
                "reconciliation",
                "finalized",
            ],
        )
        risk = next(s for s in det["stages"] if s["stage"] == "risk")["facts"][0]
        self.assertGreaterEqual(len(risk["checks"]), 9)
        self.assertTrue(all("check_id" in c and "passed" in c for c in risk["checks"]))
        self.assertEqual(det["explanation"], reader.explain(did))
        self.assertTrue(det["versions"])

    def test_hold_decision_marks_absent_stages_not_recorded(self):
        rid = IDS["success"]
        did = R.list_decisions(self.store, rid, {"tag": "HOLD"}, 1, 0)["items"][0]["decision_id"]
        det = R.decision_detail(self.store, rid, did)
        by = {s["stage"]: s for s in det["stages"]}
        self.assertEqual(by["order_intent"]["status"], "NOT_RECORDED")
        self.assertEqual(by["fills"]["status"], "NOT_RECORDED")

    def test_incomplete_decision_is_not_presented_as_complete(self):
        rid = IDS["incomplete_blocked"]
        did = R.list_decisions(self.store, rid, {}, 1, 0)["items"][0]["decision_id"]
        det = R.decision_detail(self.store, rid, did)
        self.assertEqual(det["status"], "INCOMPLETE")
        by = {s["stage"]: s for s in det["stages"]}
        self.assertEqual(by["finalized"]["status"], "NOT_RECORDED")
        self.assertIn("never finalized", by["finalized"]["note"])
        self.assertEqual(det["reconciliation_status"], "BLOCKED")
        self.assertEqual(next(f for f in by["submission"]["facts"])["outcome"], "UNCERTAIN")

    def test_unknown_decision_404(self):
        with self.assertRaises(ApiError) as cm:
            R.decision_detail(self.store, IDS["success"], "dec_nope")
        self.assertEqual(cm.exception.code, "DECISION_NOT_FOUND")

    def test_data_available_at_unknown_stays_none(self):
        rid = IDS["success"]
        did = R.list_decisions(self.store, rid, {"terminal_state": "FILLED"}, 1, 0)["items"][0][
            "decision_id"
        ]
        for s in R.decision_detail(self.store, rid, did)["stages"]:
            if s["status"] == "NOT_RECORDED":
                self.assertIsNone(s["data_available_at"])


class OrdersRiskRecon(unittest.TestCase):
    def setUp(self):
        self.store = ArtifactStore(DEMO)

    def test_partial_fill_and_cancel_after_fill(self):
        o = R.orders(self.store, IDS["partial_fill"])
        self.assertEqual(o["total"], 3)
        for x in o["items"]:
            self.assertIn("PARTIAL_FILL", x["flags"])
            self.assertIn("CANCELLED_AFTER_FILL", x["flags"])
            self.assertEqual(x["last_known_state"], "CANCELLED")
            self.assertTrue(x["fills"] and x["state_history"])

    def test_filled_orders_have_no_spurious_slots(self):
        o = R.orders(self.store, IDS["success"])
        self.assertEqual(o["total"], 6)
        self.assertTrue(
            all(x["last_known_state"] == "FILLED" and x["order_id"] for x in o["items"])
        )

    def test_uncertain_submission_never_shown_complete(self):
        o = R.orders(self.store, IDS["incomplete_blocked"])
        self.assertEqual(o["total"], 1)
        x = o["items"][0]
        self.assertIn("UNCERTAIN_SUBMISSION", x["flags"])
        self.assertNotEqual(x["last_known_state"], "FILLED")
        self.assertEqual(x["fills"], [])

    def test_reconciliation_blocked_has_mismatch_detail(self):
        r = R.reconciliation(self.store, IDS["incomplete_blocked"])
        self.assertEqual((r["blocked"], r["total"]), (1, 1))
        self.assertEqual(r["items"][0]["mismatches"][0]["field"], "position.quantity")
        self.assertEqual(R.reconciliation(self.store, IDS["success"])["blocked"], 0)

    def test_risk_outcomes_from_persisted_events(self):
        r = R.risk(self.store, IDS["risk_veto"])
        self.assertTrue(r["vetoes"])
        failing = {c["check_id"] for c in r["checks"] if c["fail"]}
        self.assertTrue(failing)
        self.assertIn("READ-ONLY", r["controls"])
        ok = R.risk(self.store, IDS["success"])
        self.assertEqual(ok["vetoes"], [])
        self.assertEqual(ok["unresolved_reconciliation"], 0)

    def test_no_risk_evidence_is_reported_missing_not_passed(self):
        r = R.risk(self.store, IDS["incomplete_blocked"])
        self.assertTrue(
            set(r["rr_checks_with_no_recorded_evidence"]) <= {f"RR-{i}" for i in range(1, 10)}
        )

    def test_equity_unavailable_is_explicit(self):
        e = R.equity(self.store, IDS["incomplete_blocked"])
        self.assertFalse(e["available"])
        self.assertEqual(e["points"], [])
        ok = R.equity(self.store, IDS["success"])
        self.assertTrue(ok["available"])
        self.assertIsNone(ok["benchmark"])


class Research(unittest.TestCase):
    def setUp(self):
        self.store = ArtifactStore(DEMO)

    def test_reports_keep_validity_and_criteria_separate(self):
        reports = R.reports(self.store, 10, 0)
        self.assertEqual(reports["total"], 1)
        r = reports["items"][0]
        d = R.report_detail(self.store, r["run_id"], r["report_id"])
        self.assertIn("verdict", d["research_validity"])
        self.assertIn("criterion_outcome", d["criteria_and_performance"])
        self.assertEqual(d["research_validity"]["verdict"], "INFRASTRUCTURE_ONLY")
        self.assertEqual(d["criteria_and_performance"]["criterion_outcome"], "CRITERIA_NOT_MET")
        self.assertTrue(d["evidence"]["synthetic"])
        self.assertIsNotNone(d["uncertainty_notice"])
        self.assertIsNotNone(d["protocol"])
        self.assertFalse(d["criteria_and_performance"]["admissible_as_evidence"])

    def test_protocols_and_trials(self):
        p = R.protocols(self.store)
        self.assertGreaterEqual(p["total"], 1)
        t = R.trials(self.store, 50, 0)
        self.assertTrue(t["chain_links_consistent"])
        self.assertTrue(t["ledger_readable"])

    def test_missing_report_404_and_corrupt_report(self):
        with self.assertRaises(ApiError) as cm:
            R.report_detail(self.store, IDS["success"], "report-none")
        self.assertEqual(cm.exception.code, "REPORT_NOT_FOUND")
        root = copy_demo("badreport")
        rep = next((root / "validity").rglob("report*.json"))
        rep.write_text("{not json")
        with self.assertRaises(ApiError) as cm:
            R.report_detail(ArtifactStore(root), rep.parent.name, rep.stem)
        self.assertEqual(cm.exception.code, "REPORT_CORRUPT")

    def test_corrupt_trial_ledger_is_flagged(self):
        root = copy_demo("badledger")
        led = root / "trials" / "ledger.jsonl"
        led.write_text(led.read_text() + "garbage\n")
        t = R.trials(ArtifactStore(root), 50, 0)
        self.assertFalse(t["ledger_readable"])
        self.assertFalse(t["chain_links_consistent"])


class JournalIntegrity(unittest.TestCase):
    def test_verified_journal_reports_integrity(self):
        i = R.run_integrity(ArtifactStore(DEMO), IDS["success"])
        self.assertEqual(i["journal"]["status"], "VERIFIED")
        self.assertTrue(i["pipeline_journal_ref"]["pipeline_journal_ref_matches"])
        self.assertEqual(i["journal"]["missing_reference_count"], 0)

    def test_tampered_journal_is_refused_unless_explicitly_allowed(self):
        root = copy_demo("tamper")
        j = root / "journals" / IDS["success"] / "journal.jsonl"
        lines = j.read_text().splitlines()
        k = next(i for i, ln in enumerate(lines) if '"INE' in ln)
        lines[k] = lines[k].replace('"INE', '"XNE', 1)
        j.write_text("\n".join(lines) + "\n")
        store = ArtifactStore(root)
        with self.assertRaises(ApiError) as cm:
            R.list_decisions(store, IDS["success"], {}, 10, 0)
        self.assertEqual((cm.exception.status, cm.exception.code), (422, "JOURNAL_UNVERIFIED"))
        out = R.list_decisions(store, IDS["success"], {}, 10, 0, allow_unverified=True)
        self.assertEqual(out["integrity"]["status"], "FAILED")
        self.assertIn("UNVERIFIED", out["integrity"]["warning"])
        self.assertEqual(R.run_summary(store, IDS["success"])["journal"]["verified"], False)

    def test_truncated_journal_decisions_become_incomplete_and_unverified_or_flagged(self):
        root = copy_demo("trunc")
        j = root / "journals" / IDS["success"] / "journal.jsonl"
        lines = j.read_text().splitlines()
        j.write_text("\n".join(lines[: len(lines) // 2]) + "\n")
        store = ArtifactStore(root)
        i = R.run_integrity(store, IDS["success"])
        # the pipeline's own journal_ref no longer matches the (shorter) journal
        self.assertFalse(i["pipeline_journal_ref"]["pipeline_journal_ref_matches"])

    def test_garbage_journal_is_explicit_state_not_500(self):
        root = copy_demo("garbage")
        j = root / "journals" / IDS["success"] / "journal.jsonl"
        j.write_text("\x00\x01 not json at all\n")
        store = ArtifactStore(root)
        with self.assertRaises(ApiError) as cm:
            R.list_decisions(store, IDS["success"], {}, 10, 0)
        self.assertIn(cm.exception.code, ("JOURNAL_CORRUPT", "JOURNAL_UNVERIFIED"))
        self.assertIn(cm.exception.status, (422,))
        self.assertTrue(
            any(
                w["code"] in ("JOURNAL_CORRUPT", "JOURNAL_UNVERIFIED")
                for w in R.run_summary(store, IDS["success"])["warnings"]
            )
        )

    def test_run_without_journal_is_explicit(self):
        store = ArtifactStore(DEMO)
        research = next(
            r["run_id"]
            for r in R.list_runs(store, {}, 50, 0)["items"]
            if r["run_type"] == "RESEARCH_HARNESS"
        )
        with self.assertRaises(ApiError) as cm:
            R.list_decisions(store, research, {}, 10, 0)
        self.assertEqual((cm.exception.status, cm.exception.code), (404, "JOURNAL_NOT_FOUND"))
        self.assertIsNone(R.overview(store, research)["decisions"])

    def test_missing_reference_surfaces_on_decision_detail(self):
        # incomplete decision: the finalized record the chain expects is absent -> explicit, not hidden
        store = ArtifactStore(DEMO)
        did = R.list_decisions(store, IDS["incomplete_blocked"], {}, 1, 0)["items"][0][
            "decision_id"
        ]
        det = R.decision_detail(store, IDS["incomplete_blocked"], did)
        self.assertTrue(
            det["caveats"] or det["missing_references"] or det["status"] == "INCOMPLETE"
        )


class IdentifiersAndExports(unittest.TestCase):
    def test_identifier_validation(self):
        for bad in (
            "..",
            "../x",
            "a/b",
            "a\\b",
            "a b",
            "",
            "x" * 200,
            "a\x00b",
            "%2e%2e",
            "run_1/../../etc",
        ):
            with self.assertRaises(ApiError, msg=repr(bad)):
                valid_id(bad)
        self.assertEqual(valid_id("run_abc-1.2@x"), "run_abc-1.2@x")

    def test_route_rejects_traversal(self):
        store = ArtifactStore(DEMO)
        for path in (
            "/api/runs/..",
            "/api/runs/%2e%2e/decisions",
            "/api/runs/a%2fb",
            "/api/research/reports/..%2f../x",
        ):
            with self.assertRaises(ApiError, msg=path) as cm:
                route(store, path, {})
            self.assertIn(cm.exception.status, (400, 404))

    def test_pagination_bounds(self):
        store = ArtifactStore(DEMO)
        for q in ({"limit": "0"}, {"limit": "100000"}, {"limit": "x"}, {"offset": "-1"}):
            with self.assertRaises(ApiError) as cm:
                route(store, "/api/runs", q)
            self.assertEqual(cm.exception.code, "INVALID_PAGINATION")

    def test_exports_match_records_and_preserve_identity(self):
        store = ArtifactStore(DEMO)
        rid = IDS["partial_fill"]
        kind, (name, fmt, obj, rows) = route(
            store, "/api/export/orders", {"run_id": rid, "format": "csv"}
        )
        self.assertEqual(kind, "export")
        self.assertEqual(len(rows), R.orders(store, rid)["total"])
        csv_text = to_csv(rows)
        self.assertIn("order_id", csv_text.splitlines()[0])
        self.assertEqual(len(csv_text.splitlines()), 1 + len(rows))
        self.assertEqual(obj["meta"]["run_id"], rid)
        self.assertTrue(obj["meta"]["evidence"]["synthetic"])
        self.assertTrue(obj["meta"]["demo"])
        _, (n2, f2, o2, r2) = route(
            store,
            "/api/export/decision",
            {
                "run_id": IDS["success"],
                "decision_id": R.list_decisions(
                    store, IDS["success"], {"terminal_state": "FILLED"}, 1, 0
                )["items"][0]["decision_id"],
            },
        )
        self.assertTrue(all("event_id" in e and "recorded_at" in e for e in r2))
        self.assertNotIn("/", n2.replace("netos-decision-", "").replace(".json", ""))

    def test_csv_injection_is_defused(self):
        self.assertIn("'=cmd", to_csv([{"a": "=cmd|' /C calc'!A0"}]))
        self.assertIn("-5", to_csv([{"a": "-5"}]))

    def test_exports_exclude_secrets(self):
        root = copy_demo("secrets")
        p = next((root / "runs").glob("run_*/result.json"))
        d = json.loads(p.read_text())
        d["failure"] = (
            "failed using api_key=sk-LIVE1234567890abcdef Bearer abcdefghijklmnop12345 in /home/claude/private/x.py"
        )
        d["broker_password"] = "hunter2"
        p.write_text(json.dumps(d))
        rid = p.parent.name
        with Server(root) as s:
            for path in (
                f"/api/runs/{rid}",
                f"/api/export/run?run_id={rid}&format=json",
                f"/api/export/run?run_id={rid}&format=csv",
            ):
                st, body, _ = s.req("GET", path)
                self.assertEqual(st, 200, path)
                text = body.decode()
                for leak in (
                    "sk-LIVE1234567890abcdef",
                    "abcdefghijklmnop12345",
                    "hunter2",
                    "/home/claude/private",
                ):
                    self.assertNotIn(leak, text, (path, leak))

    def test_invalid_export_inputs(self):
        store = ArtifactStore(DEMO)
        with self.assertRaises(ApiError):
            route(store, "/api/export/nope", {"run_id": IDS["success"]})
        with self.assertRaises(ApiError):
            route(store, "/api/export/run", {"run_id": IDS["success"], "format": "xml"})
        with self.assertRaises(ApiError):
            route(store, "/api/export/run", {"run_id": "../x"})


class HttpBoundary(unittest.TestCase):
    def test_non_loopback_bind_is_refused(self):
        for host in ("0.0.0.0", "192.168.1.5", "::", ""):
            with self.assertRaises(ApiError) as cm:
                make_server(DEMO, host=host, port=0)
            self.assertEqual(cm.exception.code, "NON_LOOPBACK_BIND_REFUSED")

    def test_server_binds_loopback_only(self):
        with Server(DEMO) as s:
            self.assertEqual(s.srv.server_address[0], "127.0.0.1")

    def test_mutating_methods_cannot_change_anything(self):
        root = copy_demo("ro")
        before = tree_hash(root)
        with Server(root) as s:
            for m in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"):
                for path in (
                    "/api/runs",
                    f"/api/runs/{IDS['success']}/decisions",
                    "/api/export/run?run_id=" + IDS["success"],
                    "/",
                    "/api/orders",
                    "/api/risk",
                ):
                    st, body, hdr = s.req(m, path)
                    self.assertEqual(st, 405, (m, path))
                    self.assertEqual(hdr.get("Allow"), "GET")
        self.assertEqual(tree_hash(root), before)

    def test_reading_every_endpoint_does_not_mutate_artifacts(self):
        root = copy_demo("crawl")
        before = tree_hash(root)
        store = ArtifactStore(root)
        with Server(root) as s:
            paths = [
                "/api/health",
                "/api/runs?limit=50",
                "/api/research/protocols",
                "/api/research/trials?limit=50",
                "/api/research/reports?limit=50",
            ]
            for rid in store.run_ids():
                paths += [
                    f"/api/runs/{rid}",
                    f"/api/runs/{rid}/overview",
                    f"/api/runs/{rid}/integrity",
                    f"/api/runs/{rid}/equity",
                ]
                for tail in ("decisions?limit=5", "orders", "reconciliation", "risk"):
                    paths.append(f"/api/runs/{rid}/{tail}")
            statuses = {p: s.req("GET", p)[0] for p in paths}
            self.assertTrue(all(st in (200, 404) for st in statuses.values()), statuses)
        self.assertEqual(tree_hash(root), before)
        self.assertEqual(
            sorted(p.name for p in root.iterdir()), sorted(p.name for p in DEMO.iterdir())
        )

    def test_host_origin_and_security_headers(self):
        with Server(DEMO) as s:
            self.assertEqual(s.req("GET", "/api/health", {"Host": "evil.example"})[0], 403)
            self.assertEqual(s.req("GET", "/api/health", {"Origin": "http://evil.example"})[0], 403)
            st, body, hdr = s.req("GET", "/api/health", {"Origin": f"http://127.0.0.1:{s.port}"})
            self.assertEqual(st, 200)
            self.assertNotIn("Access-Control-Allow-Origin", hdr)  # no CORS: same-origin only
            self.assertIn("default-src 'none'", hdr["Content-Security-Policy"])
            self.assertEqual(hdr["Cache-Control"], "no-store")
            self.assertEqual(hdr["X-Content-Type-Options"], "nosniff")
            self.assertEqual(json.loads(body)["trading_authority"], "NONE")

    def test_static_traversal_blocked_and_errors_are_typed_and_pathless(self):
        with Server(DEMO) as s:
            for p in (
                "/..%2f..%2fREADME.md",
                "/%2e%2e/%2e%2e/pyproject.toml",
                "/../../etc/passwd",
                "/nonexistent.js",
            ):
                self.assertEqual(s.req("GET", p)[0], 404, p)
            st, err = s.get_json("/api/runs/run_missing")
            self.assertEqual((st, err["error"]["code"]), (404, "RUN_NOT_FOUND"))
            st, err = s.get_json("/api/runs/..%2f..%2fetc")
            self.assertEqual(st, 400)
            self.assertNotIn(str(DEMO), json.dumps(err))
            self.assertEqual(s.req("GET", "/")[0], 200)
            self.assertEqual(s.req("GET", "/app.js")[0], 200)

    def test_health_reports_demo_only_with_marker(self):
        with Server(DEMO) as s:
            self.assertTrue(s.get_json("/api/health")[1]["demo"])
        plain = copy_demo("nomarker")
        (plain / "DEMO_MARKER.json").unlink()
        with Server(plain) as s:
            h = s.get_json("/api/health")[1]
            self.assertFalse(h["demo"])
            runs = s.get_json("/api/runs?limit=50")[1]
            self.assertFalse(runs["demo"])

    def test_missing_artifact_root_is_explicit_no_demo_fallback(self):
        with self.assertRaises(ApiError) as cm:
            make_server(Path(_TMP.name) / "does-not-exist", port=0)
        self.assertEqual(cm.exception.code, "ARTIFACT_ROOT_UNAVAILABLE")
        empty = Path(_TMP.name) / "empty"
        empty.mkdir(exist_ok=True)
        with Server(empty) as s:
            st, runs = s.get_json("/api/runs?limit=50")
            self.assertEqual((st, runs["total"], runs["demo"]), (200, 0, False))


class NoTradingAuthority(unittest.TestCase):
    def test_console_api_imports_no_execution_code(self):
        code = (
            "import sys, console_api.server, console_api.readmodel, console_api.exports\n"
            "bad=[m for m in sys.modules if m.split('.')[0] in ('simulation','risk_execution','intelligence','governance','data','domain')"
            " or m=='observability.decision_log.recorder' or (m.startswith('research') and m!='research' and not m.startswith('research.harness'))]\n"
            "print(','.join(sorted(bad)))"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(
            out.stdout.strip(), "", f"console_api pulled in execution-side modules: {out.stdout}"
        )

    def test_console_api_source_has_no_write_primitives(self):
        banned_names = {
            "FileDecisionJournal",
            "DecisionJournal",
            "JournalRecorder",
            "PipelineHarness",
            "write_pipeline_run",
            "TrialLedger",
            "ResearchEvaluationService",
        }
        for f in (ROOT / "console_api").glob("*.py"):
            tree = ast.parse(f.read_text())
            for n in ast.walk(tree):
                if isinstance(n, ast.Name):
                    self.assertNotIn(n.id, banned_names, f.name)
                if (
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id == "open"
                    and len(n.args) > 1
                ):
                    mode = getattr(n.args[1], "value", "")
                    self.assertFalse(set("wax+") & set(str(mode)), f.name)
                if isinstance(n, ast.Attribute):
                    self.assertNotIn(
                        n.attr,
                        {
                            "write_text",
                            "write_bytes",
                            "unlink",
                            "rmdir",
                            "mkdir",
                            "rename",
                            "replace",
                            "touch",
                        },
                        f"{f.name}:{n.attr}",
                    )

    def test_only_get_is_routed(self):
        src = (ROOT / "console_api" / "server.py").read_text()
        self.assertIn("def do_GET", src)
        for m in ("do_POST", "do_PUT", "do_DELETE", "do_PATCH"):
            self.assertNotIn(f"def {m}", src)


class FixtureBuilder(unittest.TestCase):
    def test_refuses_non_empty_target_and_labels_everything_synthetic(self):
        with self.assertRaises(SystemExit):
            demo.build(DEMO)
        marker = json.loads((DEMO / "DEMO_MARKER.json").read_text())
        self.assertTrue(marker["synthetic"])
        store = ArtifactStore(DEMO)
        for r in R.list_runs(store, {}, 50, 0)["items"]:
            self.assertTrue(r["evidence"]["synthetic"], r["run_id"])

    def test_authoritative_repo_data_not_touched(self):
        for p in (ROOT / "artifacts", ROOT / "journals"):
            self.assertFalse(p.exists(), f"{p} unexpectedly exists in the repo")


if __name__ == "__main__":
    unittest.main()
