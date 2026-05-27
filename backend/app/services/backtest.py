import logging
from datetime import datetime, timezone

from app.services.binance_client import get_crypto_prices, get_realized_vol
from app.services.kalshi_client import KalshiClient
from app.services.probability_model import compute_edge, series_to_underlying

logger = logging.getLogger(__name__)


async def run_backtest_preview(
    venue: str,
    pair: str,
    entry_z_score: float | None = None,
    exit_z_score: float | None = None,
    stop_loss_pct: float = 15.0,
    position_size_usd: float = 25.0,
    contracts_per_signal: int = 50,
    lookback_periods: int = 48,
    min_edge: float | None = None,
    exit_edge: float | None = None,
    vol_lookback_hours: int | None = None,
) -> dict:
    if venue == "kalshi":
        return await _backtest_kalshi(
            pair,
            min_edge=min_edge or 0.08,
            exit_edge=exit_edge or -0.02,
            stop_loss_pct=stop_loss_pct,
            contracts=contracts_per_signal,
            vol_lookback_hours=vol_lookback_hours or 24,
        )
    return _empty_result()


async def _backtest_kalshi(
    series_ticker: str,
    min_edge: float = 0.08,
    exit_edge: float = -0.02,
    stop_loss_pct: float = 15.0,
    contracts: int = 50,
    vol_lookback_hours: int = 24,
) -> dict:
    symbol = series_to_underlying(series_ticker)
    if not symbol:
        return _empty_result()

    try:
        prices = await get_crypto_prices()
        spot = prices.get(symbol, 0)
        if spot <= 0:
            return _empty_result()
        vol = await get_realized_vol(symbol, hours=vol_lookback_hours, interval="15m")
        if not vol or vol <= 0:
            return _empty_result()
    except Exception:
        return _empty_result()

    kc = KalshiClient.public()
    try:
        data = await kc.get_markets(series_ticker=series_ticker, limit=200)
    except Exception:
        return _empty_result()

    now = datetime.now(timezone.utc)
    hours_to_years = 1 / (365.25 * 24)
    signals = []

    for m in data.get("markets", []):
        last_price = float(m.get("yes_ask_dollars", 0) or 0) or float(m.get("last_price_dollars", 0) or 0)
        if last_price <= 0:
            continue

        floor_strike = m.get("floor_strike")
        cap_strike = m.get("cap_strike")
        strike_type = m.get("strike_type", "between")
        if floor_strike is None and cap_strike is None:
            continue

        if floor_strike is not None:
            floor_strike = float(floor_strike)
        if cap_strike is not None:
            cap_strike = float(cap_strike)

        close_time = m.get("close_time", "")
        try:
            ct = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            hours_left = (ct - now).total_seconds() / 3600
        except (ValueError, AttributeError):
            continue

        if hours_left <= 0:
            continue

        t_years = hours_left * hours_to_years
        result = compute_edge(spot, floor_strike, cap_strike, strike_type, t_years, vol, last_price)

        if result.edge >= min_edge:
            pnl = (result.model_prob - last_price) * contracts
            signals.append({
                "entry": last_price,
                "exit": result.model_prob,
                "pnl_pct": round(result.edge * 100, 2),
                "pnl_usd": round(pnl, 4),
                "bars_held": round(hours_left, 1),
                "edge": round(result.edge, 4),
            })

    wins = sum(1 for s in signals if s["pnl_usd"] >= 0)
    losses = len(signals) - wins
    total_pnl = sum(s["pnl_usd"] for s in signals)
    avg_pnl = total_pnl / len(signals) if signals else 0
    avg_hold = sum(s["bars_held"] for s in signals) / len(signals) if signals else 0

    return {
        "signals_count": len(signals),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(signals) * 100, 1) if signals else 0,
        "avg_pnl_usd": round(avg_pnl, 4),
        "total_pnl_usd": round(total_pnl, 2),
        "avg_hold_bars": round(avg_hold, 1),
        "data_points": len(data.get("markets", [])),
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
