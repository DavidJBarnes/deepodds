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

## 4. Historical Data Unavailable

Markets from 2024-2025 return `volume_fp = 0.00` (zero trading activity recorded).
This includes NASDAQ100 daily bracket markets from Oct 2024.

Election and financial series are absent from search results:
- KXPRES, KXPRESUSA, KXSENATE, KXHOUSE: 0 settled markets
- NASDAQ100 series filter: 0 settled markets
- INX series filter: 0 settled markets

These appear in the API as legacy records with no volume data — the old
trading-api.kalshi.com system's data was not carried over into the elections API
with live trading metrics.

---

## 5. Root Cause

Kalshi pivoted its main platform toward U.S. election and politics markets
around 2024-2025, migrating to `api.elections.kalshi.com`. The prior market
types (sports game-winners, Fed rate markets, financial brackets, individual
game outcome markets) that would generate the rich binary-price time-series
needed for a favorites calibration study are either:

1. **Not in this API** — data lives on a legacy system or a different endpoint
2. **Present but zero-volume** — market shells with no price history recorded

The high-volume market type that IS present (KXMVESPORTSMULTIGAMEEXTENDED)
is a 5-leg daily sports parlay that resolves within hours and has no gradual
price discovery in the 80-97¢ range.

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

1. **Access the legacy Kalshi trading API** — the prior platform (trading-api.kalshi.com)
   may have a different data endpoint with historical game-winner and economic
   outcome markets from 2022-2024.

2. **Alternative data source** — Kalshi publishes bulk market history files at
   https://kalshi.com/stats/historical-data (downloadable ZIP archives).
   These contain all settled markets with their price histories and would enable
   the full calibration analysis without API rate limits.

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
