"""
Offline recompute — no API. Loads cached S3 shards, settlement cache, and
series cache from disk, then runs build_dataset -> calibrate -> kill criteria
-> reports at 1c and 2c haircut. Use after settlements are already resolved
(e.g. by run_scoped) to re-evaluate quickly after a sim/calibration change.

    uv run python -m kalshi_backtest.recompute
"""
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("recompute")


def main():
    from kalshi_backtest.ingest_s3 import (
        load_s3_shards, load_settlement_cache, build_dataset_s3,
        build_funnel_report, SERIES_CACHE,
    )
    from kalshi_backtest.calibration import calibrate, adverse_selection_analysis
    from kalshi_backtest.report import evaluate_kcs, generate_report_s3

    rows = load_s3_shards()
    settlements = load_settlement_cache()
    series_cache = json.loads(SERIES_CACHE.read_text()) if SERIES_CACHE.exists() else {}
    logger.info("Loaded %d rows, %d settlements, %d series",
                len(rows), len(settlements), len(series_cache))

    print(build_funnel_report(rows, settlements, series_cache))

    for haircut in (1, 2):
        df = build_dataset_s3(rows, settlements, series_cache, haircut_cents=haircut)
        if df.empty:
            logger.error("Empty dataset at %d¢ — aborting", haircut)
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

    logger.info("DONE")


if __name__ == "__main__":
    main()
