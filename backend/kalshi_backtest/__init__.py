"""
Kalshi Favorites Backtest
=========================
Tests the hypothesis that heavy favorites (90–97¢) on Kalshi resolve YES more
often than their price implies — by enough to clear Kalshi's fee and spread.

Modules:
    ingest.py       — paginated market + candlestick fetch, CSV sharding, resumable
    calibration.py  — implied vs realized rate by price bucket / horizon / category
    simulate.py     — walk-forward bankroll simulation
    report.py       — REPORT.md + RESULTS_SUMMARY.md + stdout paste-back

Data lives under kalshi_backtest/data/ (gitignored).
Credentials: KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_PATH env vars.
"""
