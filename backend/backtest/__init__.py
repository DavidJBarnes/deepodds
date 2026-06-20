"""
Carry strategy historical replay backtester.

Drives carry.engine.tick() over 6+ years of hourly Binance data to evaluate
whether the funding-carry strategy meets kill criteria at $5k and $8k capital.

Modules:
  data_ingest  — download + cache Binance + HL historical data
  replay       — drive engine.tick() over history; produce ReplayResult
  scaling      — derive CarryConfig from capital amount
  sweep        — parameter grid + walk-forward validation
  report       — generate REPORT.md with equity chart and verdict
"""
