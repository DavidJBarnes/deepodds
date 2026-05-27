from app.models.kalshi_config import KalshiConfig
from app.models.pair_config import PairConfig


def resolve_kalshi_config(global_config: KalshiConfig, override: PairConfig | None) -> dict:
    return {
        "min_edge": _pick(override, "min_edge", global_config.min_edge),
        "exit_edge": _pick(override, "exit_edge", global_config.exit_edge),
        "contracts_per_signal": _pick(override, "contracts_per_signal", global_config.contracts_per_signal),
        "max_cost_per_signal": global_config.max_cost_per_signal,
        "stop_loss_pct": _pick(override, "stop_loss_pct", global_config.stop_loss_pct),
        "take_profit_pct": global_config.take_profit_pct,
    }


def _pick(override: PairConfig | None, field: str, global_value):
    if override is None:
        return global_value
    val = getattr(override, field, None)
    return val if val is not None else global_value
