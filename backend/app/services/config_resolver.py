from app.models.bot_config import BotConfig
from app.models.kalshi_config import KalshiConfig
from app.models.pair_config import PairConfig


def resolve_crypto_config(global_config: BotConfig, override: PairConfig | None) -> dict:
    return {
        "entry_z_score": _pick(override, "entry_z_score", global_config.entry_z_score),
        "exit_z_score": _pick(override, "exit_z_score", global_config.exit_z_score),
        "position_size_usd": _pick(override, "position_size_usd", global_config.position_size_usd),
        "stop_loss_pct": _pick(override, "stop_loss_pct", global_config.stop_loss_pct),
    }


def resolve_kalshi_config(global_config: KalshiConfig, override: PairConfig | None) -> dict:
    return {
        "entry_z_score": _pick(override, "entry_z_score", global_config.entry_z_score),
        "exit_z_score": _pick(override, "exit_z_score", global_config.exit_z_score),
        "contracts_per_signal": _pick(override, "contracts_per_signal", global_config.contracts_per_signal),
        "stop_loss_pct": _pick(override, "stop_loss_pct", global_config.stop_loss_pct),
    }


def _pick(override: PairConfig | None, field: str, global_value):
    if override is None:
        return global_value
    val = getattr(override, field, None)
    return val if val is not None else global_value
