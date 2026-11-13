# Slice 13 — Market-data and external-paper feasibility record

**Method:** none of this was verified online. The Slice 13 build sandbox has no network access, so every
`SourceVerification` / `ExternalPlatformVerification` below is `UNVERIFIED` or `NOT_ESTABLISHED`. A record only
counts as `VERIFIED` when each required check cites a **primary source and an access date**
(`markets/readiness.py`). This file lists what an operator must verify; it does not assert answers.

## US market data — candidate: Alpaca (not approved)
Required before use as a strategy or outcome input: exact account entitlement and feed (a paper account's
documented IEX entitlement is **not** complete US coverage); API/stream access; symbol coverage; real-time vs
delayed; timestamp semantics and latency; corporate-action and symbol-change handling; outage behaviour;
data-use, storage/retention, derived-data and AI-processing rights; cost. If coverage is insufficient, a
second independently authorised source may be needed for outcome verification. Status: `UNVERIFIED` →
lane data `ENGINEERING_ONLY`.

## US external paper — candidate: Alpaca Paper (not approved)
Verify: paper-only eligibility, dedicated paper credentials, official paper endpoint, symbols, order types,
rate limits, lifecycle/ack semantics, partial fills, rejections, cancellation, status read-back,
idempotency limits, usage terms. Credentials only via a secure environment mechanism, never logged or
committed (`PaperCredentials.__repr__` is redacted; `PaperEndpointPolicy` has an empty default allowlist so
the branch is `NOT_CONFIGURED` until the operator lists the exact paper host). Status: `MOCK_ONLY`.

## India market data — no source established
Needs a separately verified source for NSE/BSE with exchange-qualified identifiers, symbol-change and
corporate-action mappings, and explicit rights for algorithmic research, AI processing, paper trading,
historical storage and outcome evaluation. No scraping or unauthorised extraction. Status: `NOT_ESTABLISHED`
→ lane data `BLOCKED`; synthetic/replay engineering tests only; no operational Indian live-data-shadow claim.

## India external paper — none approved
Browser simulators and scraping wrappers do not qualify. The NSE Test Market Facility is described for
exchange members/vendors testing trading software and is **not assumed** to be a personal paper-trading API.
Status: `NOT_ESTABLISHED` → `BLOCKED`; Indian paper execution uses the internal simulator only, which must not
be described as dual-platform validation.

## Prohibited
Unofficial Investopedia browser wrapper/automation; TradingView page scraping; reverse-engineered exchange
endpoints; undocumented APIs without permission; live broker endpoints. The repository's boundary test fails
if Slice 13 sources mention these or import network modules.
