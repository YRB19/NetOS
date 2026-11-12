#!/usr/bin/env python3
"""Read-only diagnostic probe for Groww, ICICI Breeze and Upstox market data.

This script never places, modifies, cancels or simulates orders. It captures provider
responses for schema/field inspection and writes redacted JSON/NDJSON reports.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import struct
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

VERSION = "1.0.0"
DEFAULT_SYMBOLS = ["RELIANCE", "TCS", "INFY"]
DEFAULT_UPSTOX_KEYS = ["NSE_EQ|INE002A01018", "NSE_INDEX|Nifty 50"]
REDACT_KEYS = {
    "token", "access_token", "authorization", "api_key", "apikey", "api_secret",
    "secret", "secret_key", "sessiontoken", "session_token", "api_session",
    "x-sessiontoken", "x-appkey", "x-checksum", "checksum",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(value: Any, key: str = "") -> Any:
    """Redact secrets from nested provider responses before writing reports."""
    if key.lower().replace("-", "_") in REDACT_KEYS or key.lower() in REDACT_KEYS:
        return "<REDACTED>"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if isinstance(value, str):
        # Catch bearer tokens if an error message unexpectedly echoes one.
        value = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1<REDACTED>", value)
        return value
    return value


def safe_json_response(response: requests.Response) -> dict[str, Any]:
    result: dict[str, Any] = {
        "http_status": response.status_code,
        "response_headers": {
            k: v for k, v in response.headers.items()
            if k.lower() not in {"set-cookie", "authorization", "proxy-authorization"}
        },
    }
    try:
        result["body"] = redact(response.json())
    except Exception:
        result["body_text"] = redact(response.text[:100_000])
    return result


def request_json(
    session: requests.Session,
    provider: dict[str, Any],
    name: str,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    data: str | bytes | None = None,
    timeout: int = 15,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": name,
        "method": method,
        "url": url,
        "params": params or {},
        "request_headers": {
            k: ("<REDACTED>" if k.lower() in {"authorization", "x-appkey", "x-sessiontoken", "x-checksum"} else v)
            for k, v in (headers or {}).items()
        },
        "started_at": now_iso(),
    }
    try:
        response = session.request(
            method, url, params=params, headers=headers, json=json_body,
            data=data, timeout=timeout,
        )
        item.update(safe_json_response(response))
        body = item.get("body")
        app_status = body.get("status") if isinstance(body, dict) else None
        if isinstance(body, dict) and body.get("Error") not in (None, "", [], {}):
            app_failed = True
        else:
            app_failed = isinstance(app_status, str) and app_status.upper() in {"FAILURE", "FAILED", "ERROR"}
        item["application_status"] = app_status
        item["ok"] = bool(response.ok and not app_failed)
    except Exception as exc:
        item.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    item["finished_at"] = now_iso()
    provider.setdefault("requests", []).append(item)
    return item


def load_list(env_name: str, fallback: list[str]) -> list[str]:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return fallback
    return [x.strip() for x in raw.split(",") if x.strip()]


def provider_result(name: str, inputs_required: list[str]) -> dict[str, Any]:
    return {
        "provider": name,
        "probe_version": VERSION,
        "started_at": now_iso(),
        "inputs_required": inputs_required,
        "requests": [],
        "stream": {"status": "NOT_REQUESTED"},
        "notes": [],
        "status": "NOT_RUN",
    }


def gro_w_auth_token(session: requests.Session, result: dict[str, Any]) -> str | None:
    token = os.getenv("GROWW_ACCESS_TOKEN", "").strip()
    if token:
        result["notes"].append("Using GROWW_ACCESS_TOKEN supplied in local environment.")
        return token

    api_key = os.getenv("GROWW_API_KEY", "").strip()
    api_secret = os.getenv("GROWW_API_SECRET", "").strip()
    if not (api_key and api_secret):
        result["status"] = "MISSING_CREDENTIALS"
        result["notes"].append(
            "Provide GROWW_ACCESS_TOKEN, or GROWW_API_KEY + GROWW_API_SECRET. "
            "The API-key/secret flow may require daily approval in the Groww Cloud API Keys page."
        )
        return None

    timestamp = str(int(time.time()))
    checksum = hashlib.sha256((api_secret + timestamp).encode("utf-8")).hexdigest()
    started = now_iso()
    try:
        response = session.post(
            "https://api.groww.in/v1/token/api/access",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"key_type": "approval", "checksum": checksum, "timestamp": timestamp},
            timeout=15,
        )
        try:
            body = response.json()
        except Exception:
            body = {"body_text": response.text[:10000]}
        token_value = body.get("token") if isinstance(body, dict) else None
        # Persist only token metadata, never the token itself.
        safe_body = dict(body) if isinstance(body, dict) else body
        if isinstance(safe_body, dict) and "token" in safe_body:
            safe_body["token"] = "<REDACTED>"
        result.setdefault("requests", []).append({
            "name": "Generate daily Groww access token", "method": "POST",
            "url": "https://api.groww.in/v1/token/api/access",
            "request_body": {"key_type": "approval", "timestamp": timestamp, "checksum": "<REDACTED>"},
            "started_at": started, "finished_at": now_iso(),
            "http_status": response.status_code, "ok": response.ok, "body": safe_body,
        })
        if response.ok and token_value:
            result["notes"].append("Groww access token generated; token value intentionally not saved.")
            return str(token_value)
    except Exception as exc:
        result.setdefault("requests", []).append({
            "name": "Generate daily Groww access token", "method": "POST",
            "url": "https://api.groww.in/v1/token/api/access", "started_at": started,
            "finished_at": now_iso(), "ok": False, "error": f"{type(exc).__name__}: {exc}",
        })
    result["status"] = "AUTH_FAILED"
    result["notes"].append("Groww token generation failed. Check API subscription, daily key approval and credentials.")
    return None


def run_groww(symbols: list[str], result: dict[str, Any]) -> None:
    session = requests.Session()
    token = gro_w_auth_token(session, result)
    if not token:
        return
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "X-API-VERSION": "1.0",
    }
    result["notes"].append(
        "The public Groww docs expose REST live-data snapshots (quote/LTP/OHLC); "
        "this probe does not assume a Groww market-data WebSocket exists."
    )
    for symbol in symbols:
        request_json(
            session, result, f"Live quote: NSE {symbol}", "GET",
            "https://api.groww.in/v1/live-data/quote",
            params={"exchange": "NSE", "segment": "CASH", "trading_symbol": symbol},
            headers=headers,
        )
    exchange_symbols = ",".join(f"NSE_{s}" for s in symbols[:50])
    request_json(
        session, result, "Live LTP batch", "GET", "https://api.groww.in/v1/live-data/ltp",
        params={"segment": "CASH", "exchange_symbols": exchange_symbols}, headers=headers,
    )
    request_json(
        session, result, "Live OHLC batch", "GET", "https://api.groww.in/v1/live-data/ohlc",
        params={"segment": "CASH", "exchange_symbols": exchange_symbols}, headers=headers,
    )

    # Historical sample: last 2 calendar days, 5-minute bars. API limits are provider-defined.
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=2)
    for symbol in symbols[:2]:
        request_json(
            session, result, f"Historical candles sample: NSE {symbol}", "GET",
            "https://api.groww.in/v1/historical/candles",
            params={
                "exchange": "NSE", "segment": "CASH", "groww_symbol": f"NSE-{symbol}",
                "start_time": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "end_time": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "candle_interval": "5minute",
            }, headers=headers,
        )
    ok_count = sum(1 for x in result["requests"] if x.get("ok"))
    result["status"] = "SUCCESS" if ok_count else "REQUESTS_FAILED"


# --- ICICI Breeze ---

def run_icici(symbols: list[str], stream_seconds: int, result: dict[str, Any]) -> None:
    api_key = os.getenv("BREEZE_API_KEY", "").strip()
    secret = os.getenv("BREEZE_API_SECRET", "").strip()
    api_session = os.getenv("BREEZE_API_SESSION", "").strip()
    if not (api_key and secret and api_session):
        result["status"] = "MISSING_CREDENTIALS"
        result["notes"].append(
            "Set BREEZE_API_KEY, BREEZE_API_SECRET and BREEZE_API_SESSION. "
            "BREEZE_API_SESSION is the API_Session value obtained after browser login, "
            "not your password or TOTP."
        )
        return

    session = requests.Session()
    customer_payload = json.dumps(
        {"SessionToken": api_session, "AppKey": api_key}, separators=(",", ":")
    )
    cust_started = now_iso()
    try:
        cust_response = session.get(
            "https://api.icicidirect.com/breezeapi/api/v1/customerdetails",
            headers={"Content-Type": "application/json"}, data=customer_payload, timeout=15,
        )
        try:
            customer_body = cust_response.json()
        except Exception:
            customer_body = {"body_text": cust_response.text[:10000]}
        success = customer_body.get("Success") if isinstance(customer_body, dict) else None
        session_key = success.get("session_token") if isinstance(success, dict) else None
        safe_customer_body = redact(customer_body)
        result.setdefault("requests", []).append({
            "name": "Exchange Breeze API_Session for CustomerDetails session token",
            "method": "GET", "url": "https://api.icicidirect.com/breezeapi/api/v1/customerdetails",
            "request_body": {"SessionToken": "<REDACTED>", "AppKey": "<REDACTED>"},
            "started_at": cust_started, "finished_at": now_iso(),
            "http_status": cust_response.status_code, "ok": cust_response.ok,
            "body": safe_customer_body,
        })
        cust_ok = cust_response.ok
    except Exception as exc:
        cust_ok, session_key = False, None
        result.setdefault("requests", []).append({
            "name": "Exchange Breeze API_Session for CustomerDetails session token",
            "method": "GET", "url": "https://api.icicidirect.com/breezeapi/api/v1/customerdetails",
            "started_at": cust_started, "finished_at": now_iso(), "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        })
    if not (cust_ok and session_key):
        result["status"] = "AUTH_FAILED"
        result["notes"].append("Could not obtain Breeze CustomerDetails session_token; inspect redacted response and login flow.")
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    for symbol in symbols:
        payload = json.dumps({
            "stock_code": symbol,
            "exchange_code": "NSE",
            "product_type": "cash",
            "expiry_date": "",
            "right": "others",
            "strike_price": "0",
        }, separators=(",", ":"))
        checksum = hashlib.sha256((timestamp + payload + secret).encode("utf-8")).hexdigest()
        request_json(
            session, result, f"Breeze quote: NSE {symbol}", "GET",
            "https://api.icicidirect.com/breezeapi/api/v1/quotes",
            headers={
                "Content-Type": "application/json", "X-Checksum": "token " + checksum,
                "X-Timestamp": timestamp, "X-AppKey": api_key, "X-SessionToken": session_key,
            }, data=payload,
        )

    # Optional live OHLCV stream requires a provider script-code mapping (scrip ID).
    script_codes = load_list("BREEZE_SCRIPT_CODES", [])
    if not script_codes or stream_seconds <= 0:
        result["stream"] = {
            "status": "SKIPPED_NEEDS_SCRIPT_CODES" if not script_codes else "SKIPPED_BY_DURATION",
            "required_input": "BREEZE_SCRIPT_CODES, e.g. 4.1!1594; map the instrument via ICICI's StockScriptNew.csv",
            "channel": os.getenv("BREEZE_CHANNEL", "1SEC"),
        }
        result["notes"].append(
            "Breeze's documented Candle Stream requires the ICICI script code (ExchangeType.Qualifier!ScripId), "
            "the CustomerDetails session token and a Socket.IO connection."
        )
    else:
        try:
            import base64 as _base64
            import socketio

            decoded = _base64.b64decode(str(session_key)).decode("ascii")
            user_id, stream_token = decoded.split(":", 1)
            channel = os.getenv("BREEZE_CHANNEL", "1SEC").upper()
            frames: list[dict[str, Any]] = []
            sio = socketio.Client(reconnection=False, logger=False, engineio_logger=False)

            def on_ticks(data: Any) -> None:
                frames.append({"received_at": now_iso(), "data": redact(data)})

            sio.on(channel, on_ticks)
            sio.connect(
                "https://breezeapi.icicidirect.com/", socketio_path="ohlcvstream",
                headers={"User-Agent": "python-socketio[client]/socket"},
                auth={"user": user_id, "token": stream_token},
                transports=["websocket"], wait_timeout=10,
            )
            if sio.connected:
                sio.emit("join", script_codes)
                time.sleep(stream_seconds)
                sio.emit("leave", script_codes)
            sio.disconnect()
            result["stream"] = {
                "status": "SUCCESS" if frames else "CONNECTED_NO_TICKS",
                "endpoint": "https://breezeapi.icicidirect.com/ (Socket.IO path: ohlcvstream)",
                "channel": channel,
                "script_codes": script_codes,
                "frame_count": len(frames),
                "frames": frames,
            }
        except Exception as exc:
            message = str(exc)
            if "uri" in locals() and uri:
                message = message.replace(uri, "<REDACTED_ONE_TIME_WEBSOCKET_URL>")
            result["stream"] = {"status": "FAILED", "error": f"{type(exc).__name__}: {message}"}

    ok_count = sum(1 for x in result["requests"] if x.get("ok"))
    result["status"] = "SUCCESS" if ok_count else "REQUESTS_FAILED"


# --- Upstox V3 protobuf wire decoder ---
# The decoder intentionally retains unknown protobuf fields in the report, alongside
# decoded known fields. This protects the diagnostic capture if Upstox extends its schema.
ENUMS = {
    "type": {0: "initial_feed", 1: "live_feed", 2: "market_info"},
    "requestMode": {0: "ltpc", 1: "full_d5", 2: "option_greeks", 3: "full_d30"},
    "value": {0: "PRE_OPEN_START", 1: "PRE_OPEN_END", 2: "NORMAL_OPEN", 3: "NORMAL_CLOSE", 4: "CLOSING_START", 5: "CLOSING_END"},
}
SCHEMA: dict[str, dict[int, tuple[str, str]]] = {
    "LTPC": {1: ("ltp", "double"), 2: ("ltt", "int64"), 3: ("ltq", "int64"), 4: ("cp", "double")},
    "Quote": {1: ("bidQ", "int64"), 2: ("bidP", "double"), 3: ("askQ", "int64"), 4: ("askP", "double")},
    "MarketLevel": {1: ("bidAskQuote", "Quote[]")},
    "OHLC": {1: ("interval", "string"), 2: ("open", "double"), 3: ("high", "double"), 4: ("low", "double"), 5: ("close", "double"), 6: ("vol", "int64"), 7: ("ts", "int64")},
    "MarketOHLC": {1: ("ohlc", "OHLC[]")},
    "OptionGreeks": {1: ("delta", "double"), 2: ("theta", "double"), 3: ("gamma", "double"), 4: ("vega", "double"), 5: ("rho", "double")},
    "MarketFullFeed": {1: ("ltpc", "LTPC"), 2: ("marketLevel", "MarketLevel"), 3: ("optionGreeks", "OptionGreeks"), 4: ("marketOHLC", "MarketOHLC"), 5: ("atp", "double"), 6: ("vtt", "int64"), 7: ("oi", "double"), 8: ("iv", "double"), 9: ("tbq", "double"), 10: ("tsq", "double")},
    "IndexFullFeed": {1: ("ltpc", "LTPC"), 2: ("marketOHLC", "MarketOHLC")},
    "FullFeed": {1: ("marketFF", "MarketFullFeed"), 2: ("indexFF", "IndexFullFeed")},
    "FirstLevelWithGreeks": {1: ("ltpc", "LTPC"), 2: ("firstDepth", "Quote"), 3: ("optionGreeks", "OptionGreeks"), 4: ("vtt", "int64"), 5: ("oi", "double"), 6: ("iv", "double")},
    "Feed": {1: ("ltpc", "LTPC"), 2: ("fullFeed", "FullFeed"), 3: ("firstLevelWithGreeks", "FirstLevelWithGreeks"), 4: ("requestMode", "enum")},
    "MarketInfo": {1: ("segmentStatus", "map<string,enum>")},
    "FeedResponse": {1: ("type", "enum"), 2: ("feeds", "map<string,Feed>"), 3: ("currentTs", "int64"), 4: ("marketInfo", "MarketInfo")},
}


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(data) or shift >= 70:
            raise ValueError("Invalid/truncated protobuf varint")
        b = data[offset]
        offset += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            return value, offset
        shift += 7


def protobuf_fields(data: bytes):
    offset = 0
    while offset < len(data):
        start = offset
        key, offset = read_varint(data, offset)
        number, wire = key >> 3, key & 7
        if number == 0:
            raise ValueError("Invalid protobuf field number 0")
        if wire == 0:
            value, offset = read_varint(data, offset)
        elif wire == 1:
            if offset + 8 > len(data): raise ValueError("Truncated fixed64")
            value = struct.unpack_from("<d", data, offset)[0]
            offset += 8
        elif wire == 2:
            length, offset = read_varint(data, offset)
            if offset + length > len(data): raise ValueError("Truncated length-delimited field")
            value = data[offset:offset + length]
            offset += length
        elif wire == 5:
            if offset + 4 > len(data): raise ValueError("Truncated fixed32")
            value = struct.unpack_from("<f", data, offset)[0]
            offset += 4
        else:
            raise ValueError(f"Unsupported protobuf wire type {wire}")
        yield number, wire, value, data[start:offset]


def signed_int64(value: int) -> int:
    return value - (1 << 64) if value >= (1 << 63) else value


def decode_message(data: bytes, message_name: str) -> dict[str, Any]:
    schema = SCHEMA[message_name]
    out: dict[str, Any] = {}
    unknown: list[dict[str, Any]] = []
    for number, wire, value, raw in protobuf_fields(data):
        spec = schema.get(number)
        if not spec:
            unknown.append({"field_number": number, "wire_type": wire, "raw_hex": raw.hex()})
            continue
        name, kind = spec
        if kind == "map<string,Feed>" or kind == "map<string,enum>":
            entry = decode_map_entry(value, kind, message_name)
            out.setdefault(name, {}).update(entry)
            continue
        repeated = kind.endswith("[]")
        inner = kind[:-2] if repeated else kind
        if inner in SCHEMA:
            decoded = decode_message(value, inner)
        elif inner == "string":
            decoded = value.decode("utf-8", errors="replace")
        elif inner == "double":
            decoded = value
        elif inner == "int64":
            decoded = signed_int64(value)
        elif inner == "enum":
            decoded = ENUMS.get(name, {}).get(int(value), int(value))
        else:
            decoded = value
        if repeated:
            out.setdefault(name, []).append(decoded)
        else:
            out[name] = decoded
    if unknown:
        out["_unknown_fields"] = unknown
    return out


def decode_map_entry(data: bytes, kind: str, parent: str) -> dict[str, Any]:
    key = ""
    value: Any = None
    for number, wire, raw_value, _raw in protobuf_fields(data):
        if number == 1 and wire == 2:
            key = raw_value.decode("utf-8", errors="replace")
        elif number == 2:
            if kind == "map<string,Feed>":
                value = decode_message(raw_value, "Feed")
            else:
                value = ENUMS.get("value", {}).get(int(raw_value), int(raw_value))
    return {key: value} if key else {}


def decode_upstox_frame(payload: bytes) -> dict[str, Any]:
    return decode_message(payload, "FeedResponse")


def run_upstox(symbols: list[str], instrument_keys: list[str], stream_seconds: int, result: dict[str, Any], output_dir: Path) -> None:
    token = os.getenv("UPSTOX_ANALYTICS_TOKEN", "").strip() or os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if not token:
        result["status"] = "MISSING_CREDENTIALS"
        result["notes"].append("Set UPSTOX_ANALYTICS_TOKEN (recommended read-only, one-year token) or UPSTOX_ACCESS_TOKEN.")
        return
    session = requests.Session()
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    # Resolve plain trading symbols to canonical instrument keys unless the operator
    # supplied exact keys. The instrument-search response is retained for inspection.
    if not instrument_keys:
        resolved: list[str] = []
        result["instrument_resolution"] = []
        for symbol in symbols:
            search_item = request_json(
                session, result, f"Resolve NSE equity instrument key: {symbol}", "GET",
                "https://api.upstox.com/v2/instruments/search",
                params={"query": symbol, "exchanges": "NSE", "segments": "EQ",
                        "instrument_types": "EQ", "page_number": 1, "records": 20},
                headers=headers,
            )
            search_body = search_item.get("body", {})
            matches = search_body.get("data", []) if isinstance(search_body, dict) else []
            exact = [m for m in matches if isinstance(m, dict)
                     and str(m.get("trading_symbol", "")).upper() == symbol.upper()
                     and m.get("segment") == "NSE_EQ"]
            chosen = exact[0] if exact else None
            if chosen and chosen.get("instrument_key"):
                resolved.append(str(chosen["instrument_key"]))
                result["instrument_resolution"].append({
                    "requested_symbol": symbol, "selected_instrument": chosen,
                    "selection_rule": "exact trading_symbol match in NSE_EQ segment",
                })
            else:
                result["instrument_resolution"].append({
                    "requested_symbol": symbol, "selected_instrument": None,
                    "note": "No exact NSE_EQ trading_symbol match found; supply an exact key manually if needed.",
                })
        instrument_keys = resolved
    else:
        result["instrument_resolution"] = [{"source": "UPSTOX_INSTRUMENT_KEYS/--upstox-keys", "instrument_key": k}
                                             for k in instrument_keys]

    result["resolved_instrument_keys"] = instrument_keys
    if not instrument_keys:
        result["status"] = "INSTRUMENT_RESOLUTION_FAILED"
        result["notes"].append("No Upstox instrument keys were available after resolution.")
        return

    # V3 market quote endpoints accept instrument_key query parameters.
    for key in instrument_keys:
        for label, endpoint, extra in [
            ("Full market quote", "quotes", {}),
            ("LTP quote", "ltp", {}),
            ("OHLC quote", "ohlc", {"interval": "1d"}),
        ]:
            params = {"instrument_key": key, **extra}
            request_json(
                session, result, f"{label}: {key}", "GET",
                f"https://api.upstox.com/v3/market-quote/{endpoint}", params=params, headers=headers,
            )

    if stream_seconds <= 0:
        result["stream"] = {"status": "SKIPPED_BY_DURATION"}
    else:
        try:
            from websockets.sync.client import connect
            auth_started = now_iso()
            auth_response = session.get(
                "https://api.upstox.com/v3/feed/market-data-feed/authorize",
                headers=headers, timeout=15,
            )
            try:
                auth_body = auth_response.json()
            except Exception:
                auth_body = {"body_text": auth_response.text[:10000]}
            uri = ((auth_body.get("data") or {}).get("authorized_redirect_uri")
                   if isinstance(auth_body, dict) else None)
            safe_auth_body = redact(auth_body)
            if isinstance(safe_auth_body, dict):
                safe_data = safe_auth_body.get("data")
                if isinstance(safe_data, dict) and "authorized_redirect_uri" in safe_data:
                    safe_data["authorized_redirect_uri"] = "<REDACTED_ONE_TIME_WEBSOCKET_URL>"
            result.setdefault("requests", []).append({
                "name": "Authorize Upstox Market Data Feed V3", "method": "GET",
                "url": "https://api.upstox.com/v3/feed/market-data-feed/authorize",
                "request_headers": {"Accept": "application/json", "Authorization": "<REDACTED>"},
                "started_at": auth_started, "finished_at": now_iso(),
                "http_status": auth_response.status_code, "ok": auth_response.ok,
                "body": safe_auth_body,
            })
            if not (auth_response.ok and uri):
                result["stream"] = {"status": "AUTH_FAILED", "detail": "No authorized_redirect_uri returned."}
            else:
                ws_file = output_dir / "upstox_market_data_v3.ndjson"
                frame_count = 0
                raw_byte_count = 0
                deadline = time.monotonic() + stream_seconds
                request = {
                    "guid": str(uuid.uuid4()),
                    "method": "sub",
                    "data": {"mode": "full", "instrumentKeys": instrument_keys},
                }
                with connect(uri, open_timeout=15, close_timeout=5, max_size=None) as ws, ws_file.open("a", encoding="utf-8") as fp:
                    ws.send(json.dumps(request).encode("utf-8"))
                    while time.monotonic() < deadline:
                        remaining = deadline - time.monotonic()
                        try:
                            message = ws.recv(timeout=max(0.1, min(2.0, remaining)))
                        except TimeoutError:
                            continue
                        if isinstance(message, str):
                            raw = message.encode("utf-8")
                            decoded: Any = {"text_frame": message}
                        else:
                            raw = bytes(message)
                            try:
                                decoded = decode_upstox_frame(raw)
                            except Exception as decode_exc:
                                decoded = {"decode_error": f"{type(decode_exc).__name__}: {decode_exc}"}
                        event = {
                            "received_at": now_iso(),
                            "frame_number": frame_count + 1,
                            "raw_payload_base64": base64.b64encode(raw).decode("ascii"),
                            "raw_payload_hex": raw.hex(),
                            "decoded": decoded,
                        }
                        fp.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
                        fp.flush()
                        frame_count += 1
                        raw_byte_count += len(raw)
                result["stream"] = {
                    "status": "SUCCESS" if frame_count else "CONNECTED_NO_FRAMES",
                    "mode": "full",
                    "instrument_keys": instrument_keys,
                    "duration_seconds": stream_seconds,
                    "frame_count": frame_count,
                    "raw_bytes_captured": raw_byte_count,
                    "capture_file": str(ws_file),
                    "decoded_schema_note": "Known V3 fields are decoded; unknown field numbers are retained in decoded._unknown_fields and complete original frames are preserved as base64/hex.",
                }
        except Exception as exc:
            message = str(exc)
            if "uri" in locals() and uri:
                message = message.replace(uri, "<REDACTED_ONE_TIME_WEBSOCKET_URL>")
            result["stream"] = {"status": "FAILED", "error": f"{type(exc).__name__}: {message}"}
    ok_count = sum(1 for x in result["requests"] if x.get("ok"))
    if result["status"] != "AUTH_FAILED":
        result["status"] = "SUCCESS" if ok_count else "REQUESTS_FAILED"


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only market-data probe: Groww, ICICI Breeze, Upstox")
    parser.add_argument("--providers", default="groww,icici,upstox", help="Comma-separated providers or 'all'")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="NSE stock trading symbols for Groww/Breeze")
    parser.add_argument("--upstox-keys", default=os.getenv("UPSTOX_INSTRUMENT_KEYS", ""), help="Optional comma-separated exact Upstox instrument keys; otherwise symbols are resolved via Upstox Instrument Search")
    parser.add_argument("--stream-seconds", type=int, default=20, help="WebSocket capture duration; 0 disables streaming")
    parser.add_argument("--output-dir", default="reports", help="Directory for JSON and NDJSON output")
    parser.add_argument("--print-payloads", action="store_true", help="Print full response payloads to stdout")
    args = parser.parse_args()
    if args.stream_seconds < 0 or args.stream_seconds > 600:
        parser.error("--stream-seconds must be between 0 and 600")

    providers = [p.strip().lower() for p in args.providers.split(",") if p.strip()]
    if providers == ["all"]:
        providers = ["groww", "icici", "upstox"]
    invalid = set(providers) - {"groww", "icici", "upstox"}
    if invalid:
        parser.error(f"Unknown providers: {', '.join(sorted(invalid))}")

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    upstox_keys = [s.strip() for s in args.upstox_keys.split(",") if s.strip()]
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "probe": "Indian market data provider comparison",
        "probe_version": VERSION,
        "generated_at": now_iso(),
        "safety": {
            "read_only": True,
            "orders_placed": False,
            "order_endpoints_called": False,
            "credentials_saved": False,
        },
        "test_configuration": {
            "symbols": symbols,
            "upstox_instrument_keys_requested": upstox_keys,
            "stream_seconds": args.stream_seconds,
        },
        "providers": {},
    }
    plans = {
        "groww": ("Groww", ["GROWW_ACCESS_TOKEN or GROWW_API_KEY + GROWW_API_SECRET", "Active Groww Trading API subscription"]),
        "icici": ("ICICI Breeze", ["BREEZE_API_KEY", "BREEZE_API_SECRET", "BREEZE_API_SESSION from browser login", "Optional BREEZE_SCRIPT_CODES for live candle stream"]),
        "upstox": ("Upstox", ["UPSTOX_ANALYTICS_TOKEN", "UPSTOX_INSTRUMENT_KEYS (exact keys)"]),
    }
    for provider in providers:
        name, required = plans[provider]
        result = provider_result(name, required)
        report["providers"][provider] = result
        print(f"\n[{name}] Starting read-only probe...")
        try:
            if provider == "groww":
                run_groww(symbols, result)
            elif provider == "icici":
                run_icici(symbols, args.stream_seconds, result)
            elif provider == "upstox":
                run_upstox(symbols, upstox_keys, args.stream_seconds, result, output_dir)
        except KeyboardInterrupt:
            result["status"] = "INTERRUPTED"
            result["notes"].append("Interrupted by user.")
        except Exception as exc:
            result["status"] = "FAILED"
            result["fatal_error"] = f"{type(exc).__name__}: {exc}"
        result["finished_at"] = now_iso()
        request_ok = sum(1 for r in result.get("requests", []) if r.get("ok"))
        print(f"[{name}] status={result['status']} | successful HTTP requests={request_ok}/{len(result.get('requests', []))} | stream={result.get('stream', {}).get('status')}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"provider_probe_{stamp}.json"
    report_path.write_text(json.dumps(redact(report), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nReport saved: {report_path}")
    print("No orders were placed. Credentials and session tokens were not written to the report.")
    if args.print_payloads:
        print(json.dumps(redact(report), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
