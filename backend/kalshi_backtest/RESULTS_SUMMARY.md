# Kalshi Favorites Backtest — Results Summary

**Date:** 2026-06-11
**Verdict: STOP CONDITION MET — insufficient historical data**

---

## Hypothesis

Heavy favorites (90–97¢) on Kalshi resolve YES more often than implied by their price,
creating a positive expected value opportunity after the 7% fee. Specifically: does the
realized resolution rate exceed the breakeven rate `price / (price - fee)`?

## Result

**Cannot test. Universe of usable markets = 0.**

The `api.elections.kalshi.com/trade-api/v2` endpoint does not provide usable historical
binary market data in the 80–97¢ price range from 2024–2025.

## What was found

| Metric | Value |
|--------|-------|
| Markets scanned (settled, 2024+) | 10,000+ |
| Markets with volume ≥ 500 | 321 / 5,000 (6.4%) |
| Market types present | KXMVESPORTSMULTIGAMEEXTENDED (74%), KXMVECROSSCATEGORY (26%) |
| Markets with 80–97¢ price data | **0** |
| Historical 2024 markets (NASDAQ, election) | Present but volume_fp = 0.00 |
| KXPRES / KXSENATE settled markets | 0 returned |

The API is dominated by 5-leg daily sports parlay bundles that resolve in hours,
settle at 0¢ or 100¢ with no gradual price discovery, and have no history in the
target price range. Traditional binary prediction markets (elections, NASDAQ brackets,
economic outcomes) are either absent or return zero volume.

## Root cause

Kalshi migrated to `api.elections.kalshi.com` for U.S. politics markets. The prior
trading-api.kalshi.com market universe (sports game-winners, financial brackets, fed rate
decisions) is not carried forward with live trading metrics in this endpoint.

## Kill criteria

- **KC-1** (≥ 5,000 usable markets): **FAIL — 0 markets**
- KC-2 through KC-5: untestable, pending data

## Path forward

Download Kalshi bulk historical data from https://kalshi.com/stats/historical-data —
ZIP archives containing all settled markets with price histories. This bypasses the
API universe issue entirely and would enable the full calibration analysis.

## Module status

Full pipeline built and 34 tests passing. Ready to run against bulk data.
