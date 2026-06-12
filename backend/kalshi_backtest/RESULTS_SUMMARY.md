## DeepOdds Kalshi Favorites Backtest — Results for Review

**Status:** Pipeline built; awaiting first data run (2026-06-12)

**Data source:** Kalshi S3 daily files — `market_data_{YYYY-MM-DD}.json`
**Archive start:** 2021-07-02 confirmed via binary search
**Study window:** 2024-06-01 → present (validation window 2025-07-01 → present, 11+ months)
**Schema:** 10 fields confirmed — no `close` or `result` field; close = (high+low)/2/100

### Schema discovery (2026-06-12)
- S3 file has 10 fields: ticker_name, report_ticker, date, high (¢), low (¢), daily_volume, block_volume, open_interest, payout_type, status
- No close or result field — close = (high+low)/2/100; settlement via API per-ticker lookup
- Archive starts 2021-07-02; study window 2024-06-01 onward is fully covered
- File size: 0.4MB (2024) → 73MB+ (2026, sports parlay bloat)

### Kill criteria
Not yet computed — run `uv run python -m kalshi_backtest.ingest_s3` first.

Once run, results will be pasted back here in this format:

| KC | Threshold | Actual | Verdict |
|----|-----------|--------|---------|
| KC-1 non-sports/big-sports net+ CI-excl | ≥1 cell | _TBD_ | _TBD_ |
| KC-2 validated ROI ($8k) | ≥5%/yr | _TBD_ | _TBD_ |
| KC-3 max drawdown | ≤15% | _TBD_ | _TBD_ |
| KC-4 capacity (trades/yr) | ≥200 | _TBD_ | _TBD_ |
| KC-5 fee-doubled ROI > 0 | >0% | _TBD_ | _TBD_ |

### Haircut sensitivity
Both 1¢ and 2¢ fill haircut results will be reported side-by-side.

### Module status
118 tests green. Pipeline ready to run.
