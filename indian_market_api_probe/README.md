# Indian Market Data Provider Probe

A **read-only diagnostic** for comparing the data returned by:

1. Groww Trading API
2. ICICI Direct Breeze API
3. Upstox Developer API V3

It does not place, modify, cancel or simulate orders. The goal is to capture what each API actually returns so the NetOS provider decision and roadmap can be based on observed responses.

## What it tests

| Provider | REST calls | Streaming capture |
|---|---|---|
| Groww | Full quote, LTP, OHLC, historical candles | No public market-data WebSocket is assumed; official docs reviewed for this probe document REST live-data endpoints |
| ICICI Breeze | CustomerDetails authentication exchange, equity quotes | Optional Socket.IO live OHLCV candle stream (requires scrip/script codes) |
| Upstox | V3 full quotes, LTP, OHLC, WebSocket authorize | V3 Protobuf WebSocket in `full` mode; stores decoded fields plus original frame bytes |

## 1. Setup

Use Python 3.10+ (Python 3.11/3.12 recommended).

```bash
cd indian_market_api_probe
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` locally. Do not commit it. The script never prints credentials and redacts token-like response fields before writing reports.

## 2. What credentials / inputs are required

### Groww

Choose one authentication method:

- `GROWW_ACCESS_TOKEN`: generate it from Groww account > Settings > Trading APIs. The docs say this token expires daily at 6:00 AM.
- OR `GROWW_API_KEY` + `GROWW_API_SECRET`: the script computes the documented SHA-256 checksum and calls the token endpoint. The API-key/secret approval flow may require daily approval in the Groww Cloud API Keys page.

Groww's current developer page says an active Trading API subscription is required. Its published API page currently lists ₹499/month plus taxes for access to the API package; verify the price in your account before subscribing.

### ICICI Direct Breeze

Create an ICICI Direct account and register an app in the Breeze API portal. Set:

- `BREEZE_API_KEY`
- `BREEZE_API_SECRET`
- `BREEZE_API_SESSION`: the `API_Session` value returned in the browser URL after completing Breeze's login flow. This is not your ICICI password, TOTP or the final CustomerDetails session token.

The script exchanges `API_Session` through CustomerDetails, then fetches NSE cash-equity quotes. The CustomerDetails-derived token is not saved in the report.

For streaming candles, additionally set `BREEZE_SCRIPT_CODES`. Breeze's docs require an exchange qualifier and scrip ID in the form `ExchangeType.Qualifier!ScripId`, such as the documented example format `4.1!1594`. Resolve the correct script ID for each stock from ICICI's `StockScriptNew.csv`; do not assume the sample ID is Reliance. Set `BREEZE_CHANNEL` to `1SEC`, `1MIN`, `5MIN` or `30MIN`.

### Upstox

Generate a read-only Analytics Token from the Upstox Developer Apps dashboard and set `UPSTOX_ANALYTICS_TOKEN`. The Analytics Token is documented as free, read-only and valid for one year; it supports market quote, historical data and WebSocket market-data access without static-IP whitelisting.

By default, the script takes the same symbols from `--symbols` (RELIANCE, TCS, INFY) and resolves them to exact NSE equity instrument keys using Upstox's Instrument Search API. The search results and selected instrument metadata are saved in the report.

Alternatively, set `UPSTOX_INSTRUMENT_KEYS` or pass `--upstox-keys` with exact keys such as `NSE_EQ|INE002A01018,NSE_INDEX|Nifty 50`. This is not the same as a plain trading symbol like `RELIANCE`.

## 3. Run the test

Run all providers:

```bash
python provider_probe.py --providers all --symbols RELIANCE,TCS,INFY --stream-seconds 20
```

Run one provider only:

```bash
python provider_probe.py --providers groww
python provider_probe.py --providers icici
python provider_probe.py --providers upstox
```

Disable WebSocket capture (REST-only diagnostics):

```bash
python provider_probe.py --providers all --stream-seconds 0
```

Override Upstox instrument keys (optional):

```bash
python provider_probe.py --providers upstox \
  --upstox-keys 'NSE_EQ|INE002A01018,NSE_INDEX|Nifty 50' \
  --stream-seconds 30
```

Print the full REST report to terminal as well as saving it:

```bash
python provider_probe.py --providers all --print-payloads
```

## 4. Output files

The script creates:

- `reports/provider_probe_<UTC timestamp>.json` — all REST responses, request metadata, status and configuration.
- `reports/upstox_market_data_v3.ndjson` — every captured Upstox WebSocket frame, including decoded known fields, unknown protobuf field identifiers, raw hexadecimal bytes and full raw Base64 payload.

The Upstox decoder covers the main V3 schema fields: LTPC, depth quotes, OHLC intervals, option Greeks, average traded price, volume, OI, IV, total buy/sell quantity, market status and timestamps. The V3 documentation also describes auction/CAS fields; any field not yet mapped by this decoder remains visible as an unknown protobuf field, while the complete original message is preserved as Base64 and hex. This means the capture does not discard bytes even if Upstox adds fields; we can extend the field-name decoder after inspecting the actual payload.

## 5. Safety and interpretation

- Only market-data and authentication endpoints are called.
- The script never calls an order, modify-order, cancel-order, portfolio-write or funds-write endpoint.
- Groww and Breeze credentials should belong to the account owner. Do not share tokens.
- Do not turn on public redistribution or persist/reuse raw data beyond the provider's permitted licence terms. Confirm the specific AI processing, internal paper-trading and local storage use with each provider.
- A successful HTTP response does not prove the provider authorises automated AI strategy ingestion or long-term storage.
- A connected WebSocket with zero ticks may mean the market is closed, the instrument key/script ID is invalid, the token is stale, or the stream did not deliver within the capture window.
- This is a connectivity/schema probe, not a market-data quality certification and not a trading system.

## Official documentation used

- Groww API introduction/authentication: https://groww.in/trade-api/docs/curl
- Groww live data: https://groww.in/trade-api/docs/curl/live-data
- Groww historical candles: https://groww.in/trade-api/docs/curl/backtesting
- Breeze API reference: https://api.icicidirect.com/breezeapi/documents/index.html
- Upstox Analytics Token: https://upstox.com/developer/api-documentation/analytics-token/
- Upstox Instrument Search: https://upstox.com/developer/api-documentation/instrument-search/
- Upstox Market Data Feed V3: https://upstox.com/developer/api-documentation/v3/get-market-data-feed/

## 6. Local self-tests (no credentials or network required)

```bash
python -m unittest discover -s tests -v
python -m py_compile provider_probe.py
```
