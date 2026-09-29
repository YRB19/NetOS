# Cost rate verification audit trail — Slice 4.5B

**Verification date:** 2026-09-29
**Verifier:** Claude (this session), primary-source search + direct fetch,
per this project's evidence-tiering discipline (see
`decisions-and-learnings.md`).
**Scope:** the six cost components represented in `shared/costs/schedule.py`
(`IndiaEquityCostSchedule`). No new component was added; see §5/§10 of the
Slice 4.5B brief and the "additional component" note at the end.

Secondary sources (broker blogs, comparison sites, tax-prep sites) were used
only to *locate* candidate primary sources, never as final provenance for a
statutory or exchange rate, per Slice 4.5B §2.

---

## 1. Brokerage — CONFIGURABLE (not verified, not claimed to be)

No official broker rate card was checked. The existing schedule represents
a generic, commonly-published discount-broker fee structure (₹0 delivery;
intraday = whichever is lower of a flat ₹20 or 0.03% of turnover). This is
**not** a statutory Indian rate and this session did not attempt to verify
it against one named broker's current, official rate card, per the brief's
explicit instruction not to mark brokerage verified on that basis. Kept as
an explicit assumption in both schedule versions.

## 2. STT (Securities Transaction Tax)

- **Source:** NSE, "SEBI Turnover Fees, STT and Other levies"
  (`nseindia.com/invest/first-time-investor-sebi-turnover-fees-stt-other-levies`),
  an official NSE investor-education page. Page footer states
  "Updated on: 17/04/2026" (after this project's Stage-0 research window,
  and current relative to today, 2026-09-29).
- **Rates found:** Delivery — 0.100% of turnover, charged on **both** the
  buy and sell legs. Intraday — 0.025% of turnover, charged on the **sell**
  leg only (buy leg: nil). The page tabulates these identically for the
  "up to 31 March 2026" and "w.e.f. 1 April 2026" columns — i.e. no rate
  change spans the current date.
- **Statutory basis:** STT is levied under the Finance (No. 2) Act, 2004,
  as subsequently amended; NSE's table is the operative restatement used
  industry-wide for the currently applicable schedule.
- **Classification:** STATUTORY.
- **Implementation mapping:** `stt_delivery_pct = 0.001`,
  `stt_intraday_sell_pct = 0.00025`. **Unchanged from V1** — confirmed
  correct, not corrected.
- **Conclusion:** VERIFIED.

## 3. Exchange transaction charges

- **Source:** NSE circular **NSE/FA/73061**, dated 27 Feb 2026, "Revision in
  Transaction Charges", `nsearchives.nseindia.com/content/circulars/FA73061.pdf`
  (official NSE circular archive), effective **1 March 2026**.
- **What it says:** revises the transaction-charge structure while keeping
  the **total outflow** for trading members in the Cash Market segment
  unchanged at a combined **₹307.00 per crore of traded value, each side**
  — composed of a transaction charge of ₹306.99/crore plus an NSE Investor
  Protection Fund Trust (IPFT) contribution of ₹0.01/crore. This *does*
  differ from what was implemented in V1 (₹297.00/crore, sourced from the
  prior NSE/FA/64232 circular that this rate superseded) — a genuine,
  dated regulatory change that predates today and was missed by the
  unverified V1 schedule.
- **Cross-check:** a search specifically for anything superseding
  NSE/FA/73061 between 1 March 2026 and today (29 September 2026) found no
  further revision circular.
- **Exchange-specificity:** this rate is NSE's own; BSE publishes a
  separate cash-market transaction-charge schedule which this session did
  **not** verify (out of scope — the model has no exchange dimension; see
  Limitations in `cost-model.md`).
- **Classification:** EXCHANGE (not a pan-market statutory constant).
- **Implementation mapping:** `exchange_txn_pct` changed from `0.0000297`
  (V1, retained unchanged for reproducibility) to `0.0000307` (V2) =
  307 / 1,00,00,000.
- **Conclusion:** VERIFIED (NSE-specific), superseding V1's rate as of
  2026-03-01.

## 4. SEBI turnover fee

- **Source:** the same NSE page as §2 (updated 17/04/2026).
- **Rate found:** "0.0001 per cent of the price at which the securities are
  purchased or sold" — restated on the page as **₹10 per crore**.
- **Statutory basis:** SEBI (Stock Brokers) Regulations, Third Schedule
  turnover-fee table, as collected via the exchange.
- **Unit-conversion check:** ₹10 per crore = 10 / 1,00,00,000 = 0.000001 =
  0.0001%. A dedicated test
  (`test_sebi_turnover_fee_unit_conversion_rs_10_per_crore`) computes the
  fee at exactly ₹1 crore of turnover and asserts the result is exactly
  ₹10.00, per Slice 4.5B §9's explicit instruction to test this conversion
  rather than trust it by inspection.
- **Classification:** REGULATORY.
- **Implementation mapping:** `sebi_charges_pct = 0.0000010`. **Unchanged
  from V1** — confirmed correct.
- **Conclusion:** VERIFIED.

## 5. GST

- **Source:** the same NSE page as §2 (updated 17/04/2026), which states
  the GST rate on "Stock brokers Services" as **18.00%**, "Payable by:
  Brokers and collected from their clients." Cross-checked against SEBI
  circular SEBI/HO/GSD/TAD/CIR/P/2022/0097 (18 Jul 2022), "Levy of Goods &
  Services Tax (GST) on the fees payable to SEBI," which confirms GST
  applies within this same regulatory-fee ecosystem (a related but
  distinct fee flow — SEBI's own fees, not the turnover fee collected via
  exchanges — used here as corroboration of the 18% rate, not as the
  primary source for the turnover-fee GST treatment itself).
- **Rate — classification:** REGULATORY. VERIFIED.
- **Base:** the existing implementation applies GST to
  `brokerage + exchange_txn_charges + sebi_charges`, excluding STT and
  stamp duty. Neither NSE page itemises the taxable base as a formula;
  this base composition instead reflects **universal contract-note
  practice** across Indian discount and full-service brokers (GST is
  charged on brokerage and the statutorily-passed-through
  exchange/regulatory service charges; STT and stamp duty are taxes in
  their own right, not consideration for a taxable supply, and fall
  outside GST's scope under GST law's general treatment of such levies).
  This session did not locate a single itemised primary-source rule
  stating the base formula in so many words.
- **Classification (base):** CONFIGURABLE-BUT-STANDARD, not independently
  itemised-verified.
- **Implementation mapping:** `gst_pct = 0.18`, base unchanged from V1.
- **Conclusion:** rate VERIFIED; base preserved as-is (correct per
  universal practice, but recorded honestly as not itemised by the primary
  source itself, per Slice 4.5B §10's instruction not to assume the
  textbook base without checking).

## 6. Stamp duty

- **Source:** NSE, "Stamp Duty" (`nseindia.com/invest/first-time-investor-stamp-duty-charges-taxes`),
  an official NSE investor-education page, footer "Updated on: 03/10/2023."
- **Rates found:** Delivery-basis transactions in equity shares — **0.015%**;
  intraday/non-delivery-basis — **0.003%**. Both are payable **by the buyer
  only**, uniformly across all Indian states, per the amended Indian Stamp
  Act, 1899 framework (Finance Act 2019 amendments), effective nationwide
  from 1 July 2020 — the reform this table's rates reflect (the page's own
  update timestamp is more recent, but the underlying rates have not
  changed since 1 Jul 2020, so no separate newer-effective-date table
  exists to supersede this one).
- **Jurisdictional note:** this uniform, centrally-collected structure is
  exactly why the existing model's single configurable percentage (no
  per-state dimension) remains adequate — pre-2020 stamp duty genuinely was
  state-dependent, but the post-2020 regime is not, so no model gap exists
  here. This is recorded explicitly rather than assumed.
- **Classification:** STATUTORY.
- **Implementation mapping:** `stamp_duty_delivery_buy_pct = 0.00015`,
  `stamp_duty_intraday_buy_pct = 0.00003`. **Unchanged from V1** —
  confirmed correct.
- **Conclusion:** VERIFIED.

## Additional components considered and NOT added

Per Slice 4.5B §5's instruction not to add a component merely because it
exists somewhere: no additional *mandatory* transaction-cost component was
identified as missing from the Stage 3 §6/§2 specification. Exchange
identity (NSE vs BSE) is the one real gap surfaced by this verification
(§3 above) — it is documented as a limitation in `cost-model.md`, not
silently modeled, per §18's "no silent model expansion" instruction.

## Source hierarchy actually used

1. Official exchange investor-education pages (NSE) — used for STT, SEBI
   turnover fee, GST rate, stamp duty.
2. Official exchange circular (NSE/FA/73061) — used for the exchange
   transaction charge, since it is the more precise, dated, primary
   instrument for that specific component.
3. Official regulator circular (SEBI) — used as corroboration for the GST
   rate's applicability in this ecosystem.

No blog, comparison site, forum, or AI-generated summary was used as final
provenance for any rate recorded as VERIFIED above.
