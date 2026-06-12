# Kalshi Favorites Backtest — Data Investigation Report

_Updated: 2026-06-12 — S3 ingest pipeline built; awaiting data run_

---

## Status

The calibration pipeline is fully implemented and ready to run against the
Kalshi S3 bulk market-data archive. This report will be regenerated automatically
when `python -m kalshi_backtest.ingest_s3` completes.

---

## 1. Data Source (S3 bulk files)

Kalshi publishes one JSON file per trading day:

```
https://kalshi-public-docs.s3.amazonaws.com/reporting/market_data_{YYYY-MM-DD}.json
```

**Archive start:** 2021-07-02 (confirmed via binary search).
Study window 2024-06-01 → present is fully covered.
Validation window 2025-07-01 → present = 11+ months (> 6 months minimum). ✓

**Confirmed schema (Task 1, 2026-06-12):**

| Field | Type | Notes |
|-------|------|-------|
| `ticker_name` | str | Full market ticker, e.g. `KXPRES-24-DEM` |
| `report_ticker` | str | Series prefix, e.g. `KXPRES` |
| `date` | str `YYYY-MM-DD` | Trading day |
| `high` | int (¢) | Daily high price, cents |
| `low` | int (¢) | Daily low price, cents |
| `daily_volume` | int/str | Volume that day (type varies by vintage) |
| `block_volume` | int/str | Block trade volume |
| `open_interest` | int/str | Open interest |
| `payout_type` | str | `"Binary Option"` |
| `status` | str | `"active"` \| `"finalized"` \| `"closed"` |

**No `close` or `result` field.** Close is approximated as `(high + low) / 2 / 100`.
Settlement outcomes are resolved via direct per-ticker keyed lookup:
`GET /historical/markets/{ticker}` (old) or `GET /markets/{ticker}` (recent).

---

## 2. Why S3 (vs. API)

The previous investigation (2026-06-11) exhausted both API tiers:

- **Live tier** (`/markets`): 10,000 markets scanned — 100% sports parlays from 2026
- **Historical tier** (`/historical/markets`): newest-first only, ignores date params;
  50 pages = 10,000 markets all from 2026-04-12; election/financial series return 0 results

S3 bypasses these constraints entirely. See §4 below for the historical API findings
(preserved for reference).

---

## 3. Pipeline Architecture

```
Task 2: run_ingest()         → data/s3_markets/markets_s3_YYYY_MM.csv (monthly shards)
Task 3: fetch_series_metadata → data/series_cache.json
Task 4: resolve_settlements  → data/settlements/**/*.json
         build_funnel_report → printed to stdout
Task 5: build_dataset_s3()   → pd.DataFrame, horizons {1,2,7}d, haircut 1¢
Task 6: evaluate_kcs()       → KC-1..KC-5 verdicts
Task 7: generate_report_s3() → REPORT.md + RESULTS_SUMMARY.md (this file)
```

Key design decisions:
- **Streaming ingest:** raw JSON deleted after row extraction; never accumulate 70MB+/day
- **Resumable:** `data/s3_manifest.json` records completed dates; rerun skips them
- **Haircut sensitivity:** all KCs evaluated at both 1¢ and 2¢ fill haircut
- **KC-1 amendment:** non-parlay/non-sports cell OR sports with n ≥ 1,000

---

## 4. Historical API Tier Investigation (archived, 2026-06-12)

Kalshi exposes a separate historical tier for markets settled before the cutoff.
The cutoff date: `GET /historical/cutoff` → `"2026-04-13T00:00:00Z"`.

**Historical endpoint behavior (`GET /historical/markets`):**

- Returns markets sorted newest-first — no ascending sort option
- Silently ignores `min_close_ts` / `max_close_ts` query parameters
- 50 pages × 200 = 10,000 markets scanned → all from 2026-04-12 only
- Series filter results:
  - `series_ticker=KXPRES` → **0 results**
  - `series_ticker=KXFOMC` → **0 results**
  - `series_ticker=KXNASDAQ` → **0 results**
  - `series_ticker=KXTEMPNYCH` (NYC temperature) → 4,000 markets, March–April 2026 only, 3 in 80–97¢

Reaching June 2024 via API would require ~1,700–3,400+ pages — effectively impossible.

---

## 5. Module Status

| Module | Tests | Status |
|--------|-------|--------|
| `ingest.py` | 37 tests | Green |
| `ingest_s3.py` | 81 tests | Green |
| `calibration.py` | 12 tests | Green |
| `simulate.py` | 9 tests | Green |
| `report.py` | 12 tests | Green |
| **Total** | **118 tests** | **All green** |

Run with: `uv run pytest tests/test_kalshi_backtest.py`

---

## 6. How to Run

```bash
cd backend

# Set credentials (for settlement API lookups only)
export KALSHI_API_KEY_ID=...
export KALSHI_PRIVATE_KEY_PATH=...

# Full ingest + calibration + reports
uv run python -m kalshi_backtest.ingest_s3
```

Expected runtime: ~2–4h for 740+ days of S3 downloads (4-parallel, ~3s/day each).
Reports regenerated in-place when complete.

---

_Awaiting first full data run. Results will appear here automatically._
