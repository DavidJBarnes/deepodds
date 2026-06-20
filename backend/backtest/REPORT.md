# Carry Strategy Backtest Report (v3 — Symmetric Position Resize)

_Generated: 2026-06-12 02:00 UTC_

---

## 1. Data Provenance

**BTC** — 56,195 hourly rows  [2020-01-01 → 2026-05-31]
**ETH** — 56,195 hourly rows  [2020-01-01 → 2026-05-31]

| Source | Purpose | Coverage |
|--------|---------|----------|
| Binance Vision bulk archives | Funding rates (8h settlements) + 1h perp klines | 2020-01 → last complete month |
| Binance Vision spot archives | 1h spot klines | 2020-01 → last complete month |
| Hyperliquid info API | Funding cross-check (hourly) | 2023-07 → present |

**Engine version:** v3 with symmetric position resize (Phase 2A fix)
- Root cause: positions opened near the hurdle stayed frozen at tiny notional.
  The 168h trailing mean was barely above 6% at first crossing; no upward resize path.
  Effect: 2021 full-period funding $1,030 (correct); 2024 $4.85 vs standalone $361 (120× gap).
- Fix: each tick, if |current_notional - gate_target| / max > resize_tolerance (0.25),
  adjust via additional legs (up) or proportional partial close (down) at taker fills.
- Tier A/B leverage rebalancing retained (v2); timestamp fix retained (data_ingest).
- `halt_on_kill=False` in backtest: kill events counted + resumed.

**Gap counts (price data):**
  - BTC: 31 hours dropped
  - ETH: 31 hours dropped

## 2. Per-Calendar-Year Performance (Production Defaults, $8k)

_Config: hurdle=6%, rich=20%, trailing=168h, exit=0%, leverage=2x, band=3.0_

| Year | Ann. ROI | MaxDD | %Deployed | RoundTrips | Resize↑ | Resize↓ | Funding$ | Fees$ |
|------|----------|-------|-----------|------------|---------|---------|----------|-------|
| 2020 | 9.37% | -0.09% | 98.2% | 6 | 149 | 123 | $794.63 | $43.57 |
| 2021 | 12.71% | -0.08% | 94.7% | 6 | 96 | 109 | $1061.16 | $32.65 |
| 2022 | -0.07% | -0.08% | 70.4% | 13 | 320 | 299 | $13.42 | $16.68 |
| 2023 | 1.10% | -0.05% | 87.4% | 2 | 333 | 300 | $121.42 | $29.59 |
| 2024 | 4.22% | -0.01% | 89.5% | 2 | 142 | 149 | $365.03 | $24.65 |
| 2025 | 0.04% | -0.05% | 95.8% | 4 | 338 | 310 | $21.78 | $15.78 |
| 2026 | -0.01% | -0.01% | 26.8% | 2 | 39 | 37 | $0.39 | $0.82 |

**Full period:** Net P&L=$2,198.24  Ann. ROI=4.28%  Sharpe=-0.426  MaxDD=-0.09%  Fees=$163.74  Funding=$2,377.83  Resize↑=1417  Resize↓=1327  ResizeFees=$153.74  KillEvents=0  % deployed=85.3%

## 3. Walk-Forward Results

**Selection window:** 2020-01-01 → 2023-12-31  **Validation window:** 2024-01-01 → present

### Top 10 configs (selection window, $8k, zero kill events)

| Hurdle | Rich | Trail(h) | Exit | Band | Ann.ROI | MaxDD | Deploy% |
|--------|------|----------|------|------|---------|-------|---------|
| 6% | 15% | 168 | 2% | 3.5 | 8.31% | -0.12% | 84.7% |
| 6% | 15% | 168 | 2% | 3.0 | 8.31% | -0.12% | 84.7% |
| 6% | 15% | 168 | 4% | 3.5 | 8.31% | -0.12% | 81.1% |
| 6% | 15% | 168 | 4% | 3.0 | 8.31% | -0.12% | 81.1% |
| 6% | 15% | 168 | 0% | 3.5 | 8.31% | -0.12% | 87.7% |
| 6% | 15% | 168 | 0% | 3.0 | 8.31% | -0.12% | 87.7% |
| 6% | 15% | 336 | 0% | 3.5 | 8.19% | -0.17% | 91.3% |
| 6% | 15% | 336 | 2% | 3.5 | 8.19% | -0.17% | 83.6% |
| 6% | 15% | 336 | 4% | 3.5 | 8.19% | -0.17% | 80.7% |
| 4% | 15% | 168 | 2% | 3.0 | 8.02% | -0.12% | 88.3% |

### Validation window results ($8k)

| Config | Hurdle | Rich | Trail(h) | Exit | Band | Ann.ROI | MaxDD | Liq | KillEvents |
|--------|--------|------|----------|------|------|---------|-------|-----|------------|
| validation | 6% | 15% | 168 | 0% | 3.5 | 1.71% | -0.10% | 0 | 0 |
| prod_default | 6% | 20% | 168 | 0% | 3.0 | 1.67% | -0.07% | 0 | 0 |
| validation | 6% | 15% | 168 | 0% | 3.0 | 1.65% | -0.10% | 0 | 0 |
| validation | 6% | 15% | 168 | 2% | 3.0 | 1.65% | -0.10% | 0 | 0 |

## 4. Cost Sensitivity

Production defaults ($8k), validation window, with all fees + spreads doubled:
  - Baseline ROI: **1.67%**
  - Doubled-cost ROI: **1.38%**
  - ROI delta: **-0.29pp**
  - Baseline fees: $44.36  |  Doubled-cost fees: $88.71

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
| KC-1 | Validation-window ann. ROI (prod defaults, $8k) | ≥ 5% | 1.67% ann. ROI ($8k, validation) | **FAIL** |
| KC-2 | Zero liquidations + zero kill events (full period, 2x lev) | 0 / 0 | 0 liquidations, 0 kill events (full 2020→present) | **PASS** |
| KC-3 | Max drawdown ≤ 10% every calendar year | ≤ −10% | Worst: -0.09% (2020) | **PASS** |
| KC-4 | Total fees ≤ 25% of gross funding | ≤ 25% | 6.9% ($163.74 / $2377.83) | **PASS** |
| KC-5 | Tier-B recenter fees ≤ 10% of gross funding | ≤ 10% | 0.2% ($4.39 / $2377.83) | **PASS** |

**Overall verdict:** ONE OR MORE KILL CRITERIA FAILED — see above.

- KC-1 FAILED: Validation ROI 1.67% < 5%.

