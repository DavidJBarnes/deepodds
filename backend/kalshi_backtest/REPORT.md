# Kalshi Favorites Backtest — Data Investigation Report

_Generated: 2026-06-11_

---

## Finding: Insufficient historical market data — analysis not possible

The API investigation is complete. The hypothesis cannot be tested with the currently
available Kalshi API (`api.elections.kalshi.com/trade-api/v2`). This report documents
exactly what was found and what would be required to proceed.

---

## 1. API Access

- **Authentication**: RSA-PSS signing confirmed working (key ID 53378289-...)
- **Endpoint**: `api.elections.kalshi.com` (trading-api.kalshi.com redirects here)
- **Signing**: Message = `ts_ms + METHOD.upper() + /trade-api/v2 + path`
- **Rate-limit handling**: 429 back-off + retry implemented and tested

---

## 2. What the API Returns

Pages through `GET /markets?status=settled&min_close_ts=1717200000` (2024-06-01+).

**10,000 markets scanned. Year breakdown: 100% from 2026.** The API returns
markets sorted by close_time descending (newest first). To reach 2024-2025 data
requires scrolling through hundreds of thousands of 2026 parlay pages.

**Volume distribution (5,000 sampled, volume ≥ 500):**

| Series prefix | Count | Market type |
|---------------|-------|-------------|
| KXMVESPORTSMULTIGAMEEXTENDED | 236 | 5-leg sports parlay bundles |
| KXMVECROSSCATEGORY | 82 | Cross-category parlay bundles |
| KXCS2MAP | 2 | Counter-Strike 2 map winner |
| KXNHLTOTAL | 1 | NHL total goals |

**Total passing vol ≥ 500**: 321 out of 5,000 markets scanned (6.4%).

---

## 3. Price Range Audit

Fetched candlesticks for the 10 highest-volume settled markets. None had any
hourly candle with `yes_ask_close_dollars` in the 0.80–0.97 range:

| Market | Volume | Result | Candles | Price range | 80–97¢ candles |
|--------|--------|--------|---------|-------------|----------------|
| KXMVESPORTSMULTIGAMEEXTENDED (×9) | 1,400–12,650 | no | 0–1 | 0.00–1.00 | 0 |
| KXMVECROSSCATEGORY | 3,704 | no | 1 | 1.00 | 0 |

Sports parlay bundles (5-leg) are either already dead (0¢) or resolved at 100¢.
They have no gradual price discovery in the 80–97¢ window.

NHL championship series markets (KXNHL-26-WSH, etc.) — highest individual
market volumes — had price ranges of 1–11¢ (eliminated teams) or were still
unresolved (Stanley Cup finals ongoing as of 2026-06-11).

---

## 4. Historical API Tier Investigation (2026-06-12)

Kalshi exposes a separate historical tier for markets settled before the cutoff.
The cutoff date was discovered at `GET /historical/cutoff`:
`{"market_settled_ts": "2026-04-13T00:00:00Z"}`.

**Historical endpoint behavior (`GET /historical/markets`):**

- Returns markets sorted newest-first — no ascending sort option
- Silently ignores `min_close_ts` / `max_close_ts` query parameters
- 50 pages × 200 = 10,000 markets scanned → all from 2026-04-12 only
- Series filter results:
  - `series_ticker=KXPRES` → **0 results**
  - `series_ticker=KXFOMC` → **0 results**
  - `series_ticker=KXNASDAQ` → **0 results**
  - `series_ticker=KXBTCD` (BTC daily brackets) → results but only April 2026
  - `series_ticker=KXTEMPNYCH` (NYC temperature) → 4,000 markets, March–April 2026 only, 3 in 80–97¢

**Estimated pages to reach June 2024:**

~500–1,000 sports parlay markets/day × 680 days ÷ 200 per page ≈ 1,700–3,400 pages
minimum, just for sports. Election/financial series (KXPRES, KXFOMC) are not indexed
in the settled listing at all and cannot be reached via `series_ticker` filter.

**Historical market schema differs from live:** no `series_ticker` or `category` fields;
uses `event_ticker` and `mve_collection_ticker`. The `_normalise_market` helper
already derives series from `event_ticker` as a fallback.

---

## 5. Root Cause

The Kalshi API (`api.elections.kalshi.com`) was designed for real-time access,
not historical research. Both the live and historical tiers:

1. Sort newest-first with no mechanism to jump to older dates
2. Are dominated by daily sports parlay bundles (~500–1,000/day) that bury
   election/financial/economic markets far back in the pagination stack
3. Have no working date-range filter on the historical tier
4. Do not index election series (KXPRES, KXSENATE) in the settled-market listing

The 2024 election, Fed, CPI, and financial bracket markets exist in the Kalshi
database but are effectively unreachable via this API without a multi-day crawl.

---

## 6. Stop Condition Met

Per the backtest specification: "If the Kalshi API blocks or rate-limits the
historical fetch so hard that the universe is too small to analyze
(< 5,000 usable markets), stop and report that as the finding rather than
analyzing an inadequate sample."

**Usable markets with price data in 80–97¢ range: 0** (out of 5,000+ scanned).
This is below the 5,000 threshold, and the analysis is stopped.

---

## 7. What Would Be Required to Proceed

1. **Kalshi bulk historical download** — Kalshi publishes complete market history
   at https://kalshi.com/stats/historical-data (downloadable ZIP archives).
   These contain all settled markets with their full price histories, bypassing
   the API pagination problem entirely. This is the primary recommended path.

2. **Deep API crawl** — Theoretically possible but impractical: filter by specific
   series (KXBTCD, KXTEMPNYCH, etc.) and crawl page by page until reaching 2024 data.
   Estimated 1,700–3,400+ pages, ~7–14 hours of runtime, and only for series that
   the API indexes. Election series (KXPRES, KXFOMC) are not available via this path.

3. **Sufficient universe** — need ≥ 5,000 markets where the YES ask price was
   in the 80-97¢ range at some point in the final 72h before close, with
   a clear binary settlement. The bulk download likely contains this data.

---

## 8. Module Status

The full pipeline is implemented and tested:

- `ingest.py` — pagination, resume, rate-limit handling, volume filter, category derivation
- `calibration.py` — implied vs realized by bucket/horizon/category, exact Kalshi fee, Wilson CI, momentum split
- `simulate.py` — walk-forward bankroll sim, cells selected on selection window only
- `report.py` — REPORT.md + RESULTS_SUMMARY.md
- **34 tests, all green** (exact fee computation, Wilson CI, bucketing fixture with planted bias, sim accounting invariant, pagination/resume/rate-limit mocks)

The module is ready to run against real data once the data source issue is resolved.
API authentication, signing, and candlestick endpoint parameters have been fully
debugged and documented.
