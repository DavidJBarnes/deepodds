## DeepOdds Backtest v2 — Results for Review
**Data:** Binance Vision (perp+spot klines, 8h funding) | 2020-01-01–2026-05-31 | BTC,ETH | gaps dropped: 62
**Engine:** rebalancing v2, band sweep {2.5,3.0,3.5}, leverage 2.0x

### Kill criteria ($8k, production defaults, band=3.0)
| KC | Threshold | Actual | Verdict |
|----|-----------|--------|---------|
| KC-1 validated ROI | ≥5%/yr | 1.79% | FAIL |
| KC-2 liq/kill events | 0 | 0/0 | PASS |
| KC-3 worst-year drawdown | ≤10% | -0.1% | PASS |
| KC-4 total fees / funding | ≤25% | 1% | PASS |
| KC-5 recenter fees / funding | ≤10% | 0.6% | PASS |

### Per calendar year ($8k, production defaults, band=3.0)
| Year | ROI | MaxDD | %Deployed | RoundTrips | TopUps | Recenters | Funding$ | Fees$ |
|------|-----|-------|-----------|------------|--------|-----------|----------|-------|
| 2020 | 2.05% | -0.01% | 98.2% | 5 | 27 | 0 | $164.86 | $1.71 |
| 2021 | 12.69% | -0.10% | 94.7% | 6 | 27 | 1 | $1030.32 | $8.95 |
| 2022 | 0.01% | -0.00% | 70.4% | 13 | 5 | 0 | $0.61 | $0.17 |
| 2023 | 0.02% | -0.00% | 87.4% | 2 | 14 | 0 | $1.89 | $0.04 |
| 2024 | 0.06% | -0.00% | 89.5% | 2 | 14 | 0 | $4.85 | $0.04 |
| 2025 | 0.00% | -0.00% | 95.8% | 4 | 6 | 0 | $0.41 | $0.03 |
| 2026 | 0.00% | -0.00% | 26.8% | 2 | 0 | 0 | $0.02 | $0.01 |

### Walk-forward (validation window 2024→present, $8k)
| Config (hurdle/rich/window/exit/band) | Sel. ROI | Val. ROI | Val. MaxDD | Val. fees/funding |
|--------------------------------------|----------|----------|------------|-------------------|
| 6%/20%/168h/0%/3.0 | 3.70% | 1.79% | -0.04% | 4% |
| 6%/15%/168h/0%/3.5 | 5.09% | 1.69% | -0.04% | 3% |
| 6%/15%/168h/0%/3.0 | 4.75% | 1.69% | -0.04% | 3% |
| 6%/15%/168h/2%/3.5 | 5.08% | 1.62% | -0.04% | 3% |

### Sensitivity & notes
- Costs doubled → validated ROI: 1.78%
- $5k capital, production defaults → validated ROI: 1.79%
- Binance vs HL mean funding (overlap, ann.): 7.0% vs 14.2%
- Worst single episode: see engine log
- Anomalies/bugs encountered: v1 ghost-position (pct_deployed=99.9%); v1 Binance CSV column-order (rate was at index 2 not 1); 2025+ spot kline microsecond timestamps — all fixed
