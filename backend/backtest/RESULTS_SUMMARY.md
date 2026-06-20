## DeepOdds Backtest v3 — Results for Review
**Bisect outcome:** standalone 2024 funding = $361 vs full-period 2024 = $4.85 → verdict: state contamination
**Root cause:** Positions opened when the 168h trailing mean barely crossed the 6% hurdle (engine.py:target_notional). The ramp fraction was ~0.1%, so coin_qty = $2.54/mark. No upward resize path: tick() step 4 only opens when not held, closes when thin — never adjusts size. Position stayed $2.54 through multi-year rich regimes.
**Fixes applied:**
- resize_position() in engine.py: up via additional perp/spot legs (weighted entry avg); down via proportional partial close. Accounting invariant verified zero-drift. (tests: test_resize_up_fires_when_notional_below_target, test_resize_up_accounting_invariant, test_resize_down_fires_when_notional_above_target, test_resize_down_accounting_invariant, test_tick_resizes_position_toward_target)
- resize_tolerance=0.25 in config.py; resize_up_count/resize_down_count/resize_fees_usd in models.py
**Timestamp audit (2025+ files):** ok — data_ingest.py already detects µs vs ms by magnitude (ts_raw > 2e12); 2025+ rows parse with exact 1.000h spacing, zero anomalies

**Data:** Binance Vision (perp+spot klines, 8h funding) | 2020-01-01–2026-05-31 | BTC,ETH | gaps dropped: 62
**Engine:** v3 symmetric resize, band sweep {2.5,3.0,3.5}, leverage 2.0x

### Kill criteria ($8k, prod defaults, band=3.0)
| KC | Threshold | Actual | Verdict |
|----|-----------|--------|---------|
| KC-1 validated ROI | ≥5%/yr | 1.67% | FAIL |
| KC-2 liq/kill events | 0 | 0/0 | PASS |
| KC-3 worst-year drawdown | ≤10% | -0.1% | PASS |
| KC-4 total fees (incl. resize) / funding | ≤25% | 7% | PASS |
| KC-5 recenter fees / funding | ≤10% | 0.2% | PASS |

### Per calendar year ($8k, prod defaults, band=3.0)
| Year | ROI | MaxDD | %Deployed | RoundTrips | Resize↑ | Resize↓ | Funding$ | Fees$ |
|------|-----|-------|-----------|------------|---------|---------|----------|-------|
| 2020 | 9.37% | -0.09% | 98.2% | 6 | 149 | 123 | $794.63 | $43.57 |
| 2021 | 12.71% | -0.08% | 94.7% | 6 | 96 | 109 | $1061.16 | $32.65 |
| 2022 | -0.07% | -0.08% | 70.4% | 13 | 320 | 299 | $13.42 | $16.68 |
| 2023 | 1.10% | -0.05% | 87.4% | 2 | 333 | 300 | $121.42 | $29.59 |
| 2024 | 4.22% | -0.01% | 89.5% | 2 | 142 | 149 | $365.03 | $24.65 |
| 2025 | 0.04% | -0.05% | 95.8% | 4 | 338 | 310 | $21.78 | $15.78 |
| 2026 | -0.01% | -0.01% | 26.8% | 2 | 39 | 37 | $0.39 | $0.82 |

### Walk-forward (validation 2024→present, $8k)
| Config (hurdle/rich/window/exit/band) | Sel. ROI | Val. ROI | Val. MaxDD | fees/funding |
|--------------------------------------|----------|----------|------------|--------------|
| 6%/15%/168h/0%/3.5 | 8.31% | 1.71% | -0.10% | 15% |
| 6%/20%/168h/0%/3.0 | 5.80% | 1.67% | -0.07% | 12% |
| 6%/15%/168h/0%/3.0 | 8.31% | 1.65% | -0.10% | 16% |
| 6%/15%/168h/2%/3.0 | 8.31% | 1.65% | -0.10% | 16% |

### Sensitivity & notes
- Costs doubled → validated ROI: 1.38%
- $5k capital → validated ROI: 1.67%
- Binance vs HL mean funding (overlap, ann.): 7.0% vs 14.2%
- Worst single episode: see engine log
- Anomalies remaining: none (ghost-position, CSV column-order, µs timestamps all fixed in prior PRs)
