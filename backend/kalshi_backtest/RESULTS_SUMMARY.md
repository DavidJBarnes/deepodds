## DeepOdds Kalshi Favorites Backtest — Results for Review
**Data source:** Kalshi S3 daily files (archive start 2021-07-02)
**Universe:** 142,729 distinct markets, 2024-06-01 → present, vol ≥ 500, binary, no parlays
**Settled:** 36,383  |  Categories: financials: 253,741, crypto: 163,802, sports: 105,470, entertainment: 97,515, elections: 66,999, politics: 61,901, economics: 57,163, mentions: 30,749, climate and weather: 25,508, companies: 14,512, science and technology: 10,889, health: 3,041, exotics: 2,857, transportation: 2,543, world: 2,316, commodities: 999, social: 507, other: 320
**Entry haircut:** 1¢ fill haircut on daily close price

### Schema discovery (2026-06-12)
- S3 file has 10 fields: ticker_name, report_ticker, date, high (¢), low (¢), daily_volume, block_volume, open_interest, payout_type, status
- No close or result field — close = (high+low)/2/100; settlement via API per-ticker lookup
- Archive starts 2021-07-02; study window 2024-06-01 onward is fully covered

### Calibration (validation window 2025-07+, n≥50)
| Horizon | Bucket | Category | n | Implied | Realized | Net edge | CI excl. 0? |
|---------|--------|----------|---|---------|----------|----------|-------------|
| 1d | 80–84¢ | financials | 73 | 0.821 | 0.973 | +0.1318 | YES |
| 1d | 80–84¢ | crypto | 178 | 0.823 | 0.955 | +0.1118 | YES |
| 1d | 85–89¢ | financials | 67 | 0.872 | 0.985 | +0.1030 | YES |
| 1d | 85–89¢ | crypto | 216 | 0.870 | 0.972 | +0.0918 | YES |
| 1d | 90–93¢ | financials | 51 | 0.917 | 1.000 | +0.0730 | YES |
| 1d | 85–89¢ | sports | 1055 | 0.870 | 0.948 | +0.0683 | YES |
| 1d | 80–84¢ | sports | 1217 | 0.822 | 0.899 | +0.0572 | YES |
| 2d | 85–89¢ | sports | 501 | 0.869 | 0.928 | +0.0491 | YES |
| 1d | 90–93¢ | crypto | 232 | 0.915 | 0.970 | +0.0444 | YES |
| 1d | 85–89¢ | ALL | 1939 | 0.870 | 0.924 | +0.0441 | YES |
| 1d | 90–93¢ | sports | 691 | 0.915 | 0.965 | +0.0403 | YES |
| 2d | 90–93¢ | mentions | 301 | 0.916 | 0.964 | +0.0376 | YES |

### Kill criteria (1¢ haircut)
| KC | Threshold | Actual | Verdict |
|----|-----------|--------|---------|
| KC-1 non-sports/big-sports net+ CI-excl | ≥1 cell | 14 cells | PASS |
| KC-2 validated ROI ($8k) | ≥5%/yr | 8590.77%/yr | PASS |
| KC-3 max drawdown | ≤15% | 15.95% | FAIL |
| KC-4 capacity (trades/yr) | ≥200 | 7564/yr | PASS |
| KC-5 fee-doubled ROI > 0 | >0% | 4486.77%/yr | PASS |

### Validated bankroll sim ($8k, 1¢ haircut)
- Ann. ROI: 8590.77% | Trades: 3790 | Hit rate: 97.0% | MaxDD: 15.95% | Fees-doubled ROI: 4486.77%
- Capacity: 0 trades skipped (cash floor) | Peak concurrent exposure: $1526.28

### Adverse-selection finding
Rising-momentum favorites: mean net edge -0.0268. Falling-momentum favorites: mean net edge -0.1055 (worse). Falling-favorite cells have negative net edge (mean -0.1055). Entry rule should require non-negative 24h momentum to avoid buying into informed selling flow.

### Anomalies / data quality issues
none reported

### 2¢ haircut sensitivity
| KC | Verdict |
|----|--------|
| KC-1 | PASS |
| KC-2 ROI 356.42%/yr | PASS |
| KC-3 MaxDD 22.44% | FAIL |
| KC-4 1593 trades/yr | PASS |
| KC-5 doubled-fee ROI 279.78%/yr | PASS |
| **Overall** | **FAIL** |

