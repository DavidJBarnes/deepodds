"""
Scoped backtest runner — uses S3 shards already on disk (no re-ingest), resolves
settlements only for tickers that can actually produce a calibration row
(non-parlay, lifetime volume >= 500, ever traded in the 80-97c favorites band),
then runs calibration -> kill criteria -> reports.

Run:
    KALSHI_API_KEY_ID=... KALSHI_PRIVATE_KEY_PATH=/abs/path.pem \
        uv run python -m kalshi_backtest.run_scoped
"""
import logging
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("run_scoped")

VOLUME_FLOOR = 500.0
BAND_LO, BAND_HI = 80, 97


def scoped_tickers(rows):
    from kalshi_backtest.ingest_s3 import _is_parlay
    vol = defaultdict(float)
    inband = defaultdict(bool)
    parlay = {}
    for r in rows:
        t = r["ticker_name"]
        parlay[t] = _is_parlay(r["report_ticker"])
        vol[t] += float(r.get("daily_volume") or 0)
        try:
            mid = (int(r["high_cents"]) + int(r["low_cents"])) / 2
            if BAND_LO <= mid <= BAND_HI:
                inband[t] = True
        except Exception:
            pass
    return [t for t in vol
            if not parlay[t] and vol[t] >= VOLUME_FLOOR and inband[t]]


def main():
    from kalshi_backtest.ingest_s3 import (
        load_s3_shards, resolve_settlements, build_funnel_report,
        build_dataset_s3, fetch_series_metadata,
    )
    from kalshi_backtest.ingest import (
        KalshiClient, fetch_historical_cutoff, _load_creds,
    )

    rows = load_s3_shards()
    logger.info("Loaded %d shard rows", len(rows))

    tickers = scoped_tickers(rows)
    logger.info("Scoped settlement universe: %d tickers", len(tickers))

    key_id, pem_bytes = _load_creds()
    client = KalshiClient(key_id, pem_bytes)

    report_tickers = list({r["report_ticker"] for r in rows})
    series_cache = fetch_series_metadata(report_tickers, client)
    logger.info("Series cache: %d entries", len(series_cache))

    cutoff_dt = fetch_historical_cutoff(client)
    settlements = resolve_settlements(tickers, client, cutoff_dt)

    print(build_funnel_report(rows, settlements, series_cache))

    settled = {t for t, v in settlements.items() if v in ("yes", "no")}
    logger.info("Settled markets: %d", len(settled))

    from kalshi_backtest.calibration import calibrate, adverse_selection_analysis
    from kalshi_backtest.report import evaluate_kcs, generate_report_s3

    for haircut in (1, 2):
        df = build_dataset_s3(rows, settlements, series_cache, haircut_cents=haircut)
        if df.empty:
            logger.error("Empty dataset at %d¢ haircut — aborting", haircut)
            client.close()
            return
        df_sel = calibrate(df, window="selection")
        df_val = calibrate(df, window="validation")
        df_adv = adverse_selection_analysis(df, window="selection")
        kc = evaluate_kcs(df_sel, df_val, df_adv, df)
        generate_report_s3(
            df, df_sel, df_val, df_adv, kc,
            rows, settlements, series_cache,
            haircut_1c=(haircut == 1),
        )
        logger.info("Reports written for %d¢ haircut", haircut)

    client.close()
    logger.info("DONE")


if __name__ == "__main__":
    main()
