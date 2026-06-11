# Carry Strategy Backtest Report (v2 — Two-Tier Rebalancing)

_Generated: 2026-06-11 21:30 UTC_

---

## 1. Data Provenance

**BTC** — 56,195 hourly rows  [2020-01-01 → 2026-05-31]
**ETH** — 56,195 hourly rows  [2020-01-01 → 2026-05-31]

| Source | Purpose | Coverage |
|--------|---------|----------|
| Binance Vision bulk archives | Funding rates (8h settlements) + 1h perp klines | 2020-01 → last complete month |
| Binance Vision spot archives | 1h spot klines | 2020-01 → last complete month |
| Hyperliquid info API | Funding cross-check (hourly) | 2023-07 → present |

**Engine version:** v2 with two-tier leverage rebalancing (Task 1+2)
- Tier A (fee-free): cash→hl_margin transfer when lev > max_leverage_band
- Tier B (real fills): close+reopen when Tier A exhausted (cash floor)
- `halt_on_kill=False` in backtest: kill events counted + resumed, not halting

**Gap counts (price data):**
  - BTC: 31 hours dropped
  - ETH: 31 hours dropped

## 2. Per-Calendar-Year Performance (Production Defaults, $8k)

_Config: hurdle=6%, rich=20%, trailing=168h, exit=0%, leverage=2x, band=3.0_

| Year | Ann. ROI | MaxDD | %Deployed | RoundTrips | TopUps | Recenters | Funding$ | Fees$ |
|------|----------|-------|-----------|------------|--------|-----------|----------|-------|
| 2020 | 2.05% | -0.01% | 98.2% | 5 | 27 | 0 | $164.86 | $1.71 |
| 2021 | 12.69% | -0.10% | 94.7% | 6 | 27 | 1 | $1030.32 | $8.95 |
| 2022 | 0.01% | -0.00% | 70.4% | 13 | 5 | 0 | $0.61 | $0.17 |
| 2023 | 0.02% | -0.00% | 87.4% | 2 | 14 | 0 | $1.89 | $0.04 |
| 2024 | 0.06% | -0.00% | 89.5% | 2 | 14 | 0 | $4.85 | $0.04 |
| 2025 | 0.00% | -0.00% | 95.8% | 4 | 6 | 0 | $0.41 | $0.03 |
| 2026 | 0.00% | -0.00% | 26.8% | 2 | 0 | 0 | $0.02 | $0.01 |

**Full period:** Net P&L=$1,187.39  Ann. ROI=2.31%  Sharpe=-3.658  MaxDD=-0.10%  Fees=$10.94  Funding=$1,202.97  TopUps=93  Recenters=1  RecenterFees=$7.24  KillEvents=0  % deployed=85.3%

## 3. Walk-Forward Results

**Selection window:** 2020-01-01 → 2023-12-31  **Validation window:** 2024-01-01 → present

### Top 10 configs (selection window, $8k, zero kill events)

| Hurdle | Rich | Trail(h) | Exit | Band | Ann.ROI | MaxDD | Deploy% |
|--------|------|----------|------|------|---------|-------|---------|
| 6% | 15% | 168 | 0% | 3.5 | 5.09% | -0.19% | 87.7% |
| 6% | 15% | 168 | 2% | 3.5 | 5.08% | -0.19% | 84.7% |
| 6% | 15% | 168 | 0% | 3.0 | 4.75% | -0.07% | 87.7% |
| 6% | 15% | 168 | 2% | 3.0 | 4.74% | -0.07% | 84.7% |
| 4% | 15% | 168 | 0% | 3.5 | 4.68% | -0.07% | 91.0% |
| 4% | 15% | 168 | 2% | 3.5 | 4.68% | -0.07% | 88.3% |
| 4% | 15% | 168 | 0% | 3.0 | 4.68% | -0.07% | 91.0% |
| 4% | 15% | 168 | 2% | 3.0 | 4.67% | -0.07% | 88.3% |
| 4% | 15% | 168 | 0% | 2.5 | 4.62% | -0.08% | 91.0% |
| 4% | 15% | 168 | 2% | 2.5 | 4.62% | -0.08% | 88.3% |

### Validation window results ($8k)

| Config | Hurdle | Rich | Trail(h) | Exit | Band | Ann.ROI | MaxDD | Liq | KillEvents |
|--------|--------|------|----------|------|------|---------|-------|-----|------------|
| prod_default | 6% | 20% | 168 | 0% | 3.0 | 1.79% | -0.04% | 0 | 0 |
| validation | 6% | 15% | 168 | 0% | 3.5 | 1.69% | -0.04% | 0 | 0 |
| validation | 6% | 15% | 168 | 0% | 3.0 | 1.69% | -0.04% | 0 | 0 |
| validation | 6% | 15% | 168 | 2% | 3.5 | 1.62% | -0.04% | 0 | 0 |

## 4. Cost Sensitivity

Production defaults ($8k), validation window, with all fees + spreads doubled:
  - Baseline ROI: **1.79%**
  - Doubled-cost ROI: **1.78%**
  - ROI delta: **-0.00pp**
  - Baseline fees: $13.92  |  Doubled-cost fees: $22.87

## 5. Binance vs Hyperliquid Funding Comparison

Mean annualized funding per calendar quarter (decimal → %):

| Quarter | Coin | Binance Ann | HL Ann | Diff (pp) |
|---------|------|------------|--------|-----------|
| 2023Q3 | BTC | 4.75% | 3.81% | -0.94pp |
| 2023Q4 | BTC | 12.21% | 27.98% | +15.78pp |
| 2024Q1 | BTC | 22.32% | 42.10% | +19.78pp |
| 2024Q2 | BTC | 9.34% | 18.17% | +8.82pp |
| 2024Q3 | BTC | 3.47% | 12.31% | +8.83pp |
| 2024Q4 | BTC | 12.61% | 24.11% | +11.50pp |
| 2025Q1 | BTC | 5.25% | 10.18% | +4.93pp |
| 2025Q2 | BTC | 3.59% | 10.06% | +6.47pp |
| 2025Q3 | BTC | 7.03% | 13.67% | +6.64pp |
| 2025Q4 | BTC | 4.68% | 8.61% | +3.94pp |
| 2026Q1 | BTC | 1.23% | 3.54% | +2.32pp |
| 2026Q2 | BTC | 0.29% | 0.77% | +0.48pp |
| 2023Q3 | ETH | 4.40% | 8.87% | +4.47pp |

**Venue transferability:** Mean Binance ann. 7.0% vs HL ann. 14.2% (overlap period). HL funding averages +7.16pp higher.

## 6. Equity Curve

Production defaults ($8k), full period 2020 → present.

![Equity curve](REPORT_equity.png)

## 7. Verdict — Kill Criteria (v2)

Pre-agreed kill criteria, mechanically evaluated. No editorializing.

| # | Criterion | Threshold | Actual | Result |
|---|-----------|-----------|--------|--------|
| KC-1 | Validation-window ann. ROI (prod defaults, $8k) | ≥ 5% | 1.79% ann. ROI ($8k, validation) | **FAIL** |
| KC-2 | Zero liquidations + zero kill events (full period, 2x lev) | 0 / 0 | 0 liquidations, 0 kill events (full 2020→present) | **PASS** |
| KC-3 | Max drawdown ≤ 10% every calendar year | ≤ −10% | Worst: -0.10% (2021) | **PASS** |
| KC-4 | Total fees ≤ 25% of gross funding | ≤ 25% | 0.9% ($10.94 / $1202.97) | **PASS** |
| KC-5 | Tier-B recenter fees ≤ 10% of gross funding | ≤ 10% | 0.6% ($7.24 / $1202.97) | **PASS** |

**Overall verdict:** ONE OR MORE KILL CRITERIA FAILED — see above.

- KC-1 FAILED: Validation ROI 1.79% < 5%.

