"""Loopback-only, strictly read-only HTTP server (stdlib only; ADR-21).

Trust boundary: 127.0.0.1 / ::1 / localhost only. Non-loopback bind hosts are refused. Only GET is implemented; every
other method returns 405 and touches nothing. No endpoint launches strategy execution or writes any artifact."""

from __future__ import annotations

import json
import mimetypes
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

from console_api import exports, readmodel as R
from console_api.errors import ApiError, page_args, valid_id
from console_api.store import ArtifactStore
from observability.decision_log.redaction import sanitize

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend" / "public"


def _bool(q, k) -> bool:
    return str(q.get(k, "")).lower() in ("1", "true", "yes")


def route(store: ArtifactStore, path: str, q: dict):
    """Return ('json', obj) | ('export', (filename, kind, obj, rows))."""
    seg = [unquote(s) for s in path.strip("/").split("/")]
    if seg[:1] != ["api"]:
        raise ApiError(404, "NOT_FOUND", "unknown endpoint")
    seg = seg[1:]
    unv = _bool(q, "allow_unverified")
    lim, off = (None, None)
    n = len(seg)
    if seg == ["health"]:
        return "json", R.health(store)
    if seg == ["runs"]:
        lim, off = page_args(q)
        return "json", R.list_runs(store, q, lim, off)
    if n >= 2 and seg[0] == "runs":
        rid = valid_id(seg[1], "run_id")
        if n == 2:
            return "json", R.run_summary(store, rid)
        tail = seg[2:]
        if tail == ["overview"]:
            return "json", R.overview(store, rid)
        if tail == ["decisions"]:
            lim, off = page_args(q)
            return "json", R.list_decisions(store, rid, q, lim, off, unv)
        if len(tail) == 2 and tail[0] == "decisions":
            return "json", R.decision_detail(store, rid, tail[1], unv)
        if tail == ["orders"]:
            return "json", R.orders(store, rid, unv)
        if tail == ["reconciliation"]:
            return "json", R.reconciliation(store, rid, unv)
        if tail == ["risk"]:
            return "json", R.risk(store, rid, unv)
        if tail == ["integrity"]:
            return "json", R.run_integrity(store, rid)
        if tail == ["ai-signals"]:
            return "json", R.ai_signals(store, rid, unv)
        if tail == ["equity"]:
            return "json", R.equity(store, rid)
    if seg[:2] == ["research", "reports"]:
        if n == 2:
            lim, off = page_args(q)
            return "json", R.reports(store, lim, off, q.get("run_id"))
        if n == 4:
            return "json", R.report_detail(
                store, valid_id(seg[2], "run_id"), valid_id(seg[3], "report_id")
            )
    if seg == ["research", "protocols"]:
        return "json", R.protocols(store)
    if seg == ["research", "trials"]:
        lim, off = page_args(q)
        return "json", R.trials(store, lim, off)
    if seg[:1] == ["export"] and n == 2:
        return "export", _export(store, seg[1], q, unv)
    raise ApiError(404, "NOT_FOUND", "unknown endpoint")


def _export(store, kind, q, unv):
    rid = valid_id(q.get("run_id", ""), "run_id")
    fmt = q.get("format", "json")
    if fmt not in ("json", "csv"):
        raise ApiError(400, "INVALID_FORMAT", "format must be json or csv")
    meta = {
        "exported_from": "NetOS Operator Console (read-only)",
        "run_id": rid,
        "demo": store.demo,
        "evidence": R.run_summary(store, rid)["evidence"],
        "kind": kind,
    }
    if kind == "run":
        obj = R.run_summary(store, rid)
        rows = [
            {k: v for k, v in obj.items() if not isinstance(v, (dict, list))}
            | {"metrics": obj["metrics"], "evidence": obj["evidence"]}
        ]
    elif kind == "decisions":
        obj = R.list_decisions(store, rid, q, 500, 0, unv)
        rows = obj["items"]
    elif kind == "decision":
        did = valid_id(q.get("decision_id", ""), "decision_id")
        obj = R.decision_detail(store, rid, did, unv)
        rows = obj["events"]
    elif kind == "orders":
        obj = R.orders(store, rid, unv)
        rows = obj["items"]
    elif kind == "fills":
        obj = R.orders(store, rid, unv)
        rows = exports.flatten_fills(obj["items"])
        obj = {"items": rows}
    elif kind == "risk":
        obj = R.risk(store, rid, unv)
        rows = exports.flatten_risk(obj)
    elif kind == "reconciliation":
        obj = R.reconciliation(store, rid, unv)
        rows = obj["items"]
    elif kind == "report":
        obj = R.report_detail(store, rid, valid_id(q.get("report_id", ""), "report_id"))
        rows = [obj]
    else:
        raise ApiError(400, "INVALID_EXPORT_KIND", "unknown export kind")
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", f"netos-{kind}-{rid}.{fmt}")
    return name, fmt, {"meta": meta, "data": obj}, rows


class Handler(BaseHTTPRequestHandler):
    server_version = "NetOSConsole/1"
    store: ArtifactStore
    allowed_hosts: set[str]

    def log_message(self, fmt, *args):  # noqa: A003 - quiet, path-free access log
        sys.stderr.write("[console] %s\n" % (fmt % args if args else fmt))

    # ---- helpers ----
    def _headers(self, status, ctype, length, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _json(self, status, obj, extra=None):
        body = json.dumps(
            exports.scrub_paths(sanitize(obj)), default=str, ensure_ascii=False
        ).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body), extra)
        self.wfile.write(body)

    def _guard(self) -> None:
        if (self.headers.get("Host") or "").lower() not in self.allowed_hosts:
            raise ApiError(403, "FORBIDDEN_HOST", "unexpected Host header (loopback only)")
        origin = self.headers.get("Origin")
        if origin and origin.lower() not in {f"http://{h}" for h in self.allowed_hosts}:
            raise ApiError(403, "FORBIDDEN_ORIGIN", "cross-origin requests are not accepted")

    def _reject(self):
        self._json(
            405,
            ApiError(
                405,
                "METHOD_NOT_ALLOWED",
                "the Operator Console is read-only; only GET is supported",
            ).body(),
            {"Allow": "GET"},
        )

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _reject  # noqa: N815

    def do_GET(self):  # noqa: N802
        try:
            self._guard()
            u = urlsplit(self.path)
            q = dict(parse_qsl(u.query, keep_blank_values=False))
            if u.path.startswith("/api/"):
                kind, payload = route(self.store, u.path, q)
                if kind == "json":
                    return self._json(200, payload)
                name, fmt, obj, rows = payload
                if fmt == "csv":
                    body = (
                        exports.to_csv(exports.scrub_paths(sanitize(rows))) if rows else ""
                    ).encode("utf-8")
                    return self._headers_body(body, "text/csv; charset=utf-8", name)
                body = json.dumps(exports.scrub_paths(sanitize(obj)), default=str, indent=2).encode(
                    "utf-8"
                )
                return self._headers_body(body, "application/json; charset=utf-8", name)
            return self._static(u.path)
        except ApiError as e:
            self._json(e.status, e.body())
        except Exception:  # noqa: BLE001 - never leak internals/paths
            self._json(500, ApiError(500, "INTERNAL_ERROR", "unexpected server error").body())

    def _headers_body(self, body, ctype, filename):
        self._headers(
            200, ctype, len(body), {"Content-Disposition": f'attachment; filename="{filename}"'}
        )
        self.wfile.write(body)

    def _static(self, path: str):
        rel = "index.html" if path in ("/", "") else unquote(path).lstrip("/")
        base = STATIC_DIR.resolve()
        target = (base / rel).resolve()
        if base not in target.parents or not target.is_file():
            raise ApiError(404, "NOT_FOUND", "not found")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            ctype = "text/javascript"
        body = target.read_bytes()
        self._headers(
            200,
            ctype
            if "charset" in ctype
            else ctype + "; charset=utf-8"
            if ctype.startswith("text/")
            else ctype,
            len(body),
        )
        self.wfile.write(body)


def make_server(root: str | Path, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    if host not in LOOPBACK:
        raise ApiError(
            400,
            "NON_LOOPBACK_BIND_REFUSED",
            "the Operator Console binds to loopback only; network exposure requires a separate approved change",
        )
    host = "127.0.0.1" if host == "localhost" else host
    store = ArtifactStore(root)
    srv = ThreadingHTTPServer((host, port), Handler)
    p = srv.server_address[1]
    Handler.store = store
    Handler.allowed_hosts = {f"127.0.0.1:{p}", f"localhost:{p}", f"[::1]:{p}"}
    return srv
