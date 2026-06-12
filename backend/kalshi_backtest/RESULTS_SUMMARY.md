# Kalshi Favorites Backtest — Results Summary

**Date:** 2026-06-11
**Verdict: STOP CONDITION MET — insufficient historical data**

---

## Hypothesis

Heavy favorites (90–97¢) on Kalshi resolve YES more often than implied by their price,
creating a positive expected value opportunity after the 7% fee. Specifically: does the
realized resolution rate exceed the breakeven rate `price / (price - fee)`?

## Result

**Cannot test. Universe of usable markets = 0 via API.**

Both the live endpoint (`/markets`) and the historical endpoint (`/historical/markets`)
are dominated by 5-leg daily sports parlay bundles. 2024 election/financial/econ markets
exist in the historical database but are unreachable without a full pagination crawl
through millions of recent sports markets.

## What was found

### Live tier (GET /markets, last ~3 months)

| Metric | Value |
|--------|-------|
| Markets scanned (settled, 2024+) | 10,000+ |
| Markets with volume ≥ 500 | 321 / 5,000 (6.4%) |
| Market types present | KXMVESPORTSMULTIGAMEEXTENDED (74%), KXMVECROSSCATEGORY (26%) |
| Markets with 80–97¢ price data | **0** |

### Historical tier (GET /historical/markets, settled before 2026-04-13)

| Metric | Value |
|--------|-------|
| Cutoff date (live/historical boundary) | 2026-04-13 |
| Pages scanned (50 pages × 200) | 10,000 markets |
| All pages' close_time | 2026-04-12 only |
| Date filtering supported | **No** — min/max_close_ts ignored |
| Ascending sort supported | **No** — newest-first only |
| KXPRES (US elections) via series filter | 0 results |
| KXFOMC / KXNASDAQ via series filter | 0 results |
| KXTEMPNYCH (NYC temperature, 13 days of data) | 4,000 markets, 3 in 80-97¢ range |
| Estimated pages to reach June 2024 | ~100,000+ (infeasible) |

### Why 2024 data is unreachable via API

The historical endpoint sorts newest-first with no pagination shortcut to older dates.
Sports parlay series generate thousands of markets per day (KXMVESPORTSMULTIGAMEEXTENDED
alone: ~500 markets/day). To reach June 2024 (~680 days ago) requires paginating through
an estimated 300,000–500,000 markets at 0.25s/request = 21–35 hours minimum.
Traditional election and financial series (KXPRES, KXFOMC, KXNASDAQ) return 0 results
via `series_ticker` filter — they don't appear to be indexed in this endpoint.

## Kill criteria

- **KC-1** (≥ 5,000 usable markets): **FAIL — 0 markets in 80-97¢ range reachable via API**
- KC-2 through KC-5: untestable, pending data

## Path forward

Download Kalshi bulk historical data from https://kalshi.com/stats/historical-data —
ZIP archives containing all settled markets with price histories. This bypasses the
API universe issue entirely and would enable the full calibration analysis.

## Module status

Full pipeline built and 37 tests passing. Ready to run against bulk data.
