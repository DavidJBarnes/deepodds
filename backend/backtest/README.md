# Carry Strategy Backtester

Historical replay engine for the funding-carry strategy (`backend/carry/`).

Drives the production `engine.tick()` over 6+ years of Binance historical data
(BTC + ETH, 2020-01-01 → present) and evaluates pre-agreed kill criteria.

---

## Quick start

```bash
cd backend

# 1. Download historical data (first run only — caches to backtest/data/)
uv run python -m backtest.data_ingest

# 2. Run a single replay (production defaults, $8k capital)
uv run python -m backtest.replay --capital 8000

# 3. Run full sweep + walk-forward validation (saves to backtest/results/)
uv run python -m backtest.sweep

# 4. Generate REPORT.md + equity chart
uv run python -m backtest.report

# 5. Tests
uv run pytest tests/test_backtest_*.py -v
```

---

## Module layout

| File | Purpose |
|------|---------|
| `data_ingest.py` | Download/cache Binance Vision funding rates + 1h klines; HL cross-check |
| `scaling.py` | `scaled_config(capital_usd)` — derive position limits from capital |
| `replay.py` | `run_replay()` — drives `engine.tick()` per hour, returns `ReplayResult` |
| `sweep.py` | 99-combo parameter sweep + walk-forward validation |
| `report.py` | Generates `REPORT.md` + `REPORT_equity.png` |
| `data/` | Cached CSV files (gitignored) |
| `results/` | Sweep output CSV (gitignored) |
| `REPORT.md` | Latest backtest report (gitignored) |

---

## Data pipeline

All data sourced from Binance Vision bulk archives (public, no API key):

```
https://data.binance.vision/data/futures/um/monthly/fundingRate/{SYMBOL}/
https://data.binance.vision/data/futures/um/monthly/klines/{SYMBOL}/1h/
https://data.binance.vision/data/spot/monthly/klines/{SYMBOL}/1h/
```

Bybit v5 REST is available as a fallback for funding rates.

**Critical unit conversion:** Binance settles funding every 8 hours. The engine
expects per-hour rates. Conversion: `funding_hourly = funding_rate_8h / 8.0`.

**Timestamp quirk:** Binance spot klines switched from milliseconds to microseconds
in 2025. Values `> 2e12` are divided by 1000 before storage.

Data assembled into a canonical hourly DataFrame per coin:
- `ts` — UTC timestamp (1h intervals)
- `funding_hourly` — funding rate per hour (float)
- `perp_close` — perpetual close price (USD)
- `spot_close` — spot close price (USD)

Coverage: 56,195 hourly rows per coin (2020-01-01 → 2026-05-31, 31 dropped hours each).

---

## Capital scaling

`scaled_config(capital_usd)` derives position limits that keep total committed
capital within the wallet:

| Parameter | Ratio | At $8k | At $5k |
|-----------|-------|--------|--------|
| `max_notional_per_symbol` | 30% | $2,400 | $1,500 |
| `max_total_notional` | 55% | $4,400 | $2,750 |

With 2× leverage + 15% reserve, full two-symbol deployment commits ≈ 91% of wallet.

---

## Walk-forward protocol

- **Selection window:** 2020-01-01 → 2023-12-31 (in-sample — rank configs)
- **Validation window:** 2024-01-01 → present (OOS — headline numbers)

OOS is run **once only** per config. No re-tuning after seeing OOS results.

Disqualification from selection: liquidation OR kill-switch OR negative P&L in ≥2 years.

---

## Kill criteria

Pre-agreed before any backtest was run. Non-negotiable.

| # | Criterion | Threshold |
|---|-----------|-----------|
| KC-1 | Validation-window ann. ROI ($8k, prod defaults) | ≥ 5% |
| KC-2 | Zero liquidations + zero kill-switch (full 2020→present, 2x lev) | 0 / 0 |
| KC-3 | Max drawdown ≤ 10% in every calendar year | ≤ −10% |
| KC-4 | Total fees ≤ 25% of gross funding collected | ≤ 25% |

See `REPORT.md` for the verdict.

---

## Engine fix (Task 4)

The production `carry/engine.py` had a cash-check bug: `pf.cash_usd > tgt` only checked
whether cash exceeded notional, not whether it covered margin + spot + reserve + fees.
At small capital this allowed negative cash on open.

Fix (line 163–168 of `engine.py`):
```python
committed_estimate = (
    tgt * (1 + 1 / cfg.target_leverage + cfg.reserve_frac)
    + tgt * cfg.taker_fee_frac * (cfg.legs_per_round_trip / 2)
)
if pf.total_notional(marks) + tgt <= cfg.max_total_notional_usd and pf.cash_usd >= committed_estimate:
```

Regression test: `tests/test_carry_engine.py::test_cash_cannot_go_negative_on_open`.

---

## Known limitations

- **Binance ≠ Hyperliquid funding:** HL funding averages +7pp higher than Binance
  in overlapping quarters (2023–2026). Binance-derived conclusions understate
  potential HL income but also understate execution costs.
- **Isolated margin:** The engine models HL perp shorts with isolated margin.
  A 50–70% adverse price move drains the margin account even though total
  portfolio equity is unchanged (spot gains cancel perp losses). This is the
  structural source of KC-2 failure.
- **Single-exchange execution:** No cross-venue basis risk modeled.
- **No rebalancing:** Position notional drifts with price; no dynamic resizing.
