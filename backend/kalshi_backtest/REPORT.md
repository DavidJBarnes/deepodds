# Kalshi Favorites Backtest Report

_Generated: 2026-06-18 13:58 UTC | Entry haircut: 1¢_

---

## 1. Data Source

- **Source:** Kalshi S3 daily market-data files
  (`kalshi-public-docs.s3.amazonaws.com/reporting/market_data_{YYYY-MM-DD}.json`)
- **Archive start:** 2021-07-02 (study window from 2024-06-01)
- **Schema fields:** ticker_name, report_ticker, date, high (¢), low (¢),
  daily_volume, open_interest, status, payout_type
- **Close proxy:** `(high + low) / 2 / 100`  (no explicit close field)
- **Settlement:** keyed API lookup per ticker (GET /historical/markets/{ticker})

## 2. Universe & Data

- **Volume floor:** lifetime ≥ 500 contracts, binary settlement
- **Parlays excluded:** via series metadata + prefix patterns
- **Total distinct markets ingested:** 142,729
- **With resolved settlement:** 36,383
- **Date range:** 2024-06-01 → present

| Category | Markets |
|----------|---------|
| financials | 253,741 |
| crypto | 163,802 |
| sports | 105,470 |
| entertainment | 97,515 |
| elections | 66,999 |
| politics | 61,901 |
| economics | 57,163 |
| mentions | 30,749 |
| climate and weather | 25,508 |
| companies | 14,512 |
| science and technology | 10,889 |
| health | 3,041 |
| exotics | 2,857 |
| transportation | 2,543 |
| world | 2,316 |
| commodities | 999 |
| social | 507 |
| other | 320 |

## 3. Calibration (validation window 2025-07+)

| Horizon (d) | Bucket | Category | n | Implied | Realized | Net edge | CI excl. 0? |
|-------------|--------|----------|---|---------|----------|----------|-------------|
| 1d | 80–84¢ | ALL | 2083 | 0.822 | 0.874 | +0.0321 | YES |
| 1d | 80–84¢ | crypto | 178 | 0.823 | 0.955 | +0.1118 | YES |
| 1d | 80–84¢ | entertainment | 123 | 0.820 | 0.699 | -0.1412 | no |
| 1d | 80–84¢ | financials | 73 | 0.821 | 0.973 | +0.1318 | YES |
| 1d | 80–84¢ | mentions | 373 | 0.822 | 0.850 | +0.0082 | no |
| 1d | 80–84¢ | sports | 1217 | 0.822 | 0.899 | +0.0572 | YES |
| 1d | 85–89¢ | ALL | 1939 | 0.870 | 0.924 | +0.0441 | YES |
| 1d | 85–89¢ | crypto | 216 | 0.870 | 0.972 | +0.0918 | YES |
| 1d | 85–89¢ | entertainment | 115 | 0.871 | 0.826 | -0.0547 | no |
| 1d | 85–89¢ | financials | 67 | 0.872 | 0.985 | +0.1030 | YES |
| 1d | 85–89¢ | mentions | 363 | 0.870 | 0.893 | +0.0122 | no |
| 1d | 85–89¢ | sports | 1055 | 0.870 | 0.948 | +0.0683 | YES |
| 1d | 90–93¢ | ALL | 1569 | 0.915 | 0.955 | +0.0295 | YES |
| 1d | 90–93¢ | crypto | 232 | 0.915 | 0.970 | +0.0444 | YES |
| 1d | 90–93¢ | entertainment | 148 | 0.914 | 0.892 | -0.0326 | no |
| 1d | 90–93¢ | financials | 51 | 0.917 | 1.000 | +0.0730 | YES |
| 1d | 90–93¢ | mentions | 323 | 0.915 | 0.951 | +0.0252 | no |
| 1d | 90–93¢ | sports | 691 | 0.915 | 0.965 | +0.0403 | YES |
| 1d | 94–97¢ | ALL | 1770 | 0.956 | 0.973 | +0.0071 | no |
| 1d | 94–97¢ | crypto | 270 | 0.955 | 0.989 | +0.0238 | YES |
| 1d | 94–97¢ | economics | 88 | 0.957 | 0.932 | -0.0353 | no |
| 1d | 94–97¢ | entertainment | 195 | 0.956 | 0.949 | -0.0169 | no |
| 1d | 94–97¢ | financials | 61 | 0.956 | 1.000 | +0.0341 | no |
| 1d | 94–97¢ | mentions | 330 | 0.955 | 0.964 | -0.0010 | no |
| 1d | 94–97¢ | politics | 59 | 0.956 | 1.000 | +0.0338 | no |
| 1d | 94–97¢ | sports | 701 | 0.956 | 0.976 | +0.0094 | no |
| 2d | 80–84¢ | ALL | 1139 | 0.820 | 0.805 | -0.0349 | no |
| 2d | 80–84¢ | entertainment | 112 | 0.822 | 0.705 | -0.1363 | no |
| 2d | 80–84¢ | mentions | 277 | 0.820 | 0.874 | +0.0336 | no |
| 2d | 80–84¢ | sports | 606 | 0.820 | 0.822 | -0.0181 | no |
| 2d | 85–89¢ | ALL | 1065 | 0.870 | 0.894 | +0.0142 | no |
| 2d | 85–89¢ | entertainment | 118 | 0.871 | 0.873 | -0.0083 | no |
| 2d | 85–89¢ | mentions | 278 | 0.869 | 0.885 | +0.0055 | no |
| 2d | 85–89¢ | sports | 501 | 0.869 | 0.928 | +0.0491 | YES |
| 2d | 90–93¢ | ALL | 954 | 0.916 | 0.944 | +0.0185 | YES |
| 2d | 90–93¢ | crypto | 55 | 0.917 | 0.891 | -0.0359 | no |
| 2d | 90–93¢ | entertainment | 128 | 0.916 | 0.938 | +0.0118 | no |
| 2d | 90–93¢ | mentions | 301 | 0.916 | 0.964 | +0.0376 | YES |
| 2d | 90–93¢ | sports | 332 | 0.915 | 0.949 | +0.0233 | no |
| 2d | 94–97¢ | ALL | 1260 | 0.956 | 0.969 | +0.0030 | no |
| 2d | 94–97¢ | economics | 93 | 0.958 | 0.935 | -0.0322 | no |
| 2d | 94–97¢ | entertainment | 177 | 0.956 | 0.938 | -0.0284 | no |
| 2d | 94–97¢ | mentions | 275 | 0.954 | 0.967 | +0.0038 | no |
| 2d | 94–97¢ | politics | 72 | 0.957 | 0.986 | +0.0192 | no |
| 2d | 94–97¢ | sports | 506 | 0.957 | 0.982 | +0.0156 | no |

## 4. Kill Criteria

| KC | Criterion | Threshold | Actual | Verdict |
|---|-----------|-----------|--------|---------|
| KC-1 | Val cell net edge > 0, CI excl 0, non-sports or sports n≥1k | ≥1 | 14 cells net+ CI-excl-zero (non-sports OR sports n≥1k) | **PASS** |
| KC-2 | Validated bankroll ROI ($8k) | ≥5%/yr | 1078.56%/yr | **PASS** |
| KC-3 | Max drawdown (validation) | ≤15% | 16.93% | **FAIL** |
| KC-4 | Capacity (trades/yr) | ≥200 | 5608/yr | **PASS** |
| KC-5 | Fee-doubled ROI still > 0 | >0% | 639.02%/yr | **PASS** |

**Overall verdict:** ONE OR MORE KILL CRITERIA FAILED — see above.

## 5. Validated Bankroll Simulation ($8k)

- **Annualized ROI:** 1078.56%
- **Total trades:** 2810
- **Hit rate:** 96.7%
- **Max drawdown:** 16.93%
- **Total fees paid:** $3054.09
- **Peak concurrent exposure:** $26920.62
- **Skipped (cash floor):** 980
- **Fees-doubled ROI:** 639.02%

## 6. Adverse Selection

Rising-momentum favorites: mean net edge -0.0268. Falling-momentum favorites: mean net edge -0.1055 (worse). Falling-favorite cells have negative net edge (mean -0.1055). Entry rule should require non-negative 24h momentum to avoid buying into informed selling flow.

## 7. Haircut Sensitivity

This report uses a **1¢ fill haircut** on top of the daily close price.
At 1¢: entry = close + 0.01. At 2¢: entry = close + 0.02.
Both KC verdicts are reported; see RESULTS_SUMMARY.md for the side-by-side.

