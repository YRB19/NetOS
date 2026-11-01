"""python -m console_api --root <artifact dir> [--port 8765]   (stop with Ctrl-C)"""

from __future__ import annotations

import argparse
import sys

from console_api.errors import ApiError
from console_api.server import make_server


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="console_api", description="NetOS Operator Console (read-only, loopback-only)"
    )
    ap.add_argument(
        "--root",
        required=True,
        help="existing artifact directory (no silent fallback to demo data)",
    )
    ap.add_argument("--host", default="127.0.0.1", help="loopback only; anything else is refused")
    ap.add_argument("--port", type=int, default=8765)
    ns = ap.parse_args(argv)
    try:
        srv = make_server(ns.root, ns.host, ns.port)
    except ApiError as e:
        print(f"refused: {e.code}: {e.message}", file=sys.stderr)
        return 2
    port = srv.server_address[1]
    print(
        f"NetOS Operator Console (READ-ONLY, no trading authority) on http://127.0.0.1:{port}/  -- stop with Ctrl-C",
        file=sys.stderr,
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
