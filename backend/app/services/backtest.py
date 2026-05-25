import logging

from app.services.mean_reversion import _compute_vwap_and_std, _public_candles, compute_z_score
from app.core.async_util import run_async

logger = logging.getLogger(__name__)

MAX_HOLD_BARS = 96


async def run_backtest_preview(
    venue: str,
    pair: str,
    entry_z_score: float,
    exit_z_score: float,
    stop_loss_pct: float,
    position_size_usd: float = 25.0,
    contracts_per_signal: int = 50,
    lookback_periods: int = 48,
) -> dict:
    if venue == "crypto":
        return await _backtest_crypto(
            pair, entry_z_score, exit_z_score, stop_loss_pct,
            position_size_usd, lookback_periods,
        )
    elif venue == "kalshi":
        return await _backtest_kalshi(
            pair, entry_z_score, exit_z_score, stop_loss_pct,
            contracts_per_signal, lookback_periods,
        )
    return _empty_result()


async def _backtest_crypto(
    pair: str,
    entry_z: float,
    exit_z: float,
    stop_loss_pct: float,
    position_size: float,
    lookback: int,
) -> dict:
    candles = await _public_candles(pair, 300)
    if not candles or len(candles) < lookback + 10:
        return _empty_result()

    candles = list(reversed(candles))
    return _simulate(candles, lookback, entry_z, exit_z, stop_loss_pct, position_size)


async def _backtest_kalshi(
    series_ticker: str,
    entry_z: float,
    exit_z: float,
    stop_loss_pct: float,
    contracts: int,
    lookback: int,
) -> dict:
    import time
    from app.services.kalshi_client import KalshiClient
    from app.services.kalshi_mean_reversion import _kalshi_candles_to_generic

    kc = KalshiClient.public()

    try:
        data = await kc.get_markets(series_ticker=series_ticker, limit=10)
    except Exception:
        return _empty_result()

    best_market = None
    best_vol = 0
    for m in data.get("markets", []):
        vol = float(m.get("volume_24h_fp", 0))
        if vol > best_vol:
            best_vol = vol
            best_market = m

    if not best_market:
        return _empty_result()

    ticker = best_market["ticker"]
    now_ts = int(time.time())
    lookback_sec = lookback * 60 * 60 * 3

    try:
        raw = await kc.get_candlesticks(
            series_ticker, ticker,
            start_ts=now_ts - lookback_sec,
            end_ts=now_ts,
            period_interval=60,
        )
        candles = _kalshi_candles_to_generic(raw)
    except Exception:
        return _empty_result()

    if not candles or len(candles) < lookback + 10:
        return _empty_result()

    candles = list(reversed(candles))
    position_size = contracts
    return _simulate(candles, lookback, entry_z, exit_z, stop_loss_pct, position_size)


def _simulate(
    candles: list[dict],
    lookback: int,
    entry_z: float,
    exit_z: float,
    stop_loss_pct: float,
    position_size: float,
) -> dict:
    signals = []
    in_position = False
    entry_price = 0.0
    entry_idx = 0

    for i in range(lookback, len(candles)):
        window = candles[i - lookback:i]
        vwap, std = _compute_vwap_and_std(window, lookback)
        if vwap <= 0 or std <= 0:
            continue

        price = float(candles[i].get("close", 0))
        if price <= 0:
            continue

        z = compute_z_score(price, vwap, std)

        if not in_position:
            if z <= entry_z:
                in_position = True
                entry_price = price
                entry_idx = i
        else:
            pnl_pct = (price - entry_price) / entry_price * 100 if entry_price > 0 else 0
            bars_held = i - entry_idx

            should_exit = False
            if z >= exit_z and z != 0 and price >= entry_price:
                should_exit = True
            elif pnl_pct <= -stop_loss_pct:
                should_exit = True
            elif bars_held >= MAX_HOLD_BARS:
                should_exit = True

            if should_exit:
                pnl_usd = (price - entry_price) / entry_price * position_size
                signals.append({
                    "entry": entry_price,
                    "exit": price,
                    "pnl_pct": round(pnl_pct, 2),
                    "pnl_usd": round(pnl_usd, 4),
                    "bars_held": bars_held,
                })
                in_position = False

    wins = sum(1 for s in signals if s["pnl_usd"] >= 0)
    losses = len(signals) - wins
    total_pnl = sum(s["pnl_usd"] for s in signals)
    avg_pnl = total_pnl / len(signals) if signals else 0
    avg_hold = sum(s["bars_held"] for s in signals) / len(signals) if signals else 0
    data_bars = len(candles) - lookback

    return {
        "signals_count": len(signals),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(signals) * 100, 1) if signals else 0,
        "avg_pnl_usd": round(avg_pnl, 4),
        "total_pnl_usd": round(total_pnl, 2),
        "avg_hold_bars": round(avg_hold, 1),
        "data_points": data_bars,
    }


def _empty_result() -> dict:
    return {
        "signals_count": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": 0,
        "avg_pnl_usd": 0,
        "total_pnl_usd": 0,
        "avg_hold_bars": 0,
        "data_points": 0,
    }
