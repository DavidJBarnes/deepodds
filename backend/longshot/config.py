"""Config + credential loading for the longshot paper harness."""
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


def load_kalshi_creds() -> tuple[str, bytes]:
    """
    (api_key_id, pem_bytes). Priority for the private key:
      1. KALSHI_PRIVATE_KEY_PEM_B64 — base64 of the raw PEM (prod: no newline
         escaping pain, safe through env files / SSM).
      2. KALSHI_PRIVATE_KEY_PEM     — inline PEM (literal \n or real newlines).
      3. KALSHI_PRIVATE_KEY_PATH    — PEM file path (local dev).
    """
    import base64

    key_id = os.environ.get("KALSHI_API_KEY_ID", "").strip()
    pem_b64 = os.environ.get("KALSHI_PRIVATE_KEY_PEM_B64", "").strip()
    pem_inline = os.environ.get("KALSHI_PRIVATE_KEY_PEM", "")
    key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "").strip()
    if not key_id or not (pem_b64 or pem_inline or key_path):
        raise SystemExit(
            "[longshot] Missing credentials. Set KALSHI_API_KEY_ID and one of "
            "KALSHI_PRIVATE_KEY_PEM_B64 (base64 PEM), KALSHI_PRIVATE_KEY_PEM "
            "(inline PEM), or KALSHI_PRIVATE_KEY_PATH (file)."
        )
    if pem_b64:
        pem = base64.b64decode(pem_b64)
    elif pem_inline:
        pem = pem_inline.replace("\\n", "\n").encode()
    else:
        pem = Path(key_path).read_bytes()
    return key_id, pem


# Temperature cities trade year-round; sports (NFL/NCAA/tennis) seasonal. The
# validated edge lives in these categories — do NOT trade a blanket band.
#
# EVERY series below is verified to exist on Kalshi (200 from /series/{ticker})
# and to carry a CI-clean longshot-short edge in backtest (validation 2025-07+,
# 1-12c, 1-day, daily-low fill, net fee — see kalshi_backtest/VERDICT_EDGE_BY_CATEGORY.md).
# test_longshot_whitelist.py guards against re-introducing a non-existent series.
#
# History: the prior whitelist shipped non-existent names (KXNFLFIRST/KXNFLATD →
# 404; only KXNFLFIRSTTD/KXNFL2TD are real) plus 10 dead temp cities, so NFL never
# fired and the canary traded temp + KXNCAAFGAME only. Fixed 2026-06-25.
#
# Backtest-first follow-ups (NOT yet whitelisted): the KXHIGHT{city} temp
# generation (ATL/BOS/SEA/DC/PHX/MIN/DAL/SFO exist) and crypto (KXBTC*, fattest
# but BTC-correlated) each need their own backtest before inclusion.
TEMP_CITIES = ("NY", "CHI", "LAX", "MIA", "AUS", "DEN", "PHIL", "HOU")
SPORTS_SERIES = (
    "KXNCAAFGAME",    # NCAA football game  +2.01c  (already live; capacity king)
    "KXNFLFIRSTTD",   # NFL first TD         +3.43c  (was mis-named KXNFLFIRST → 404)
    "KXNFL2TD",       # NFL 2+ TD            +4.48c  (intended by KXNFLATD; that was 404)
    "KXNFLSPREAD",    # NFL spread           +4.72c
    "KXNCAAMBGAME",   # NCAA basketball game +2.70c
    "KXATPMATCH",     # ATP tennis match     +5.35c  (liquid but n=40/0-loss — thin, watch live)
)


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name, "").strip()
    try:
        return float(v) if v else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name, "").strip()
    try:
        return int(v) if v else default
    except ValueError:
        return default


@dataclass
class LongshotConfig:
    whitelist: tuple = field(default_factory=lambda: tuple(
        [f"KXHIGH{c}" for c in TEMP_CITIES] + list(SPORTS_SERIES)))
    band: tuple = (0.01, 0.12)         # cheap longshot YES band ($)
    max_hours_to_close: float = 30.0   # ~1-day horizon
    account: float = field(default_factory=lambda: _env_float("LONGSHOT_ACCOUNT", 8_000.0))
    trade_fraction: float = field(default_factory=lambda: _env_float("LONGSHOT_TRADE_FRACTION", 0.005))
    max_depth_frac: float = 0.25       # max fraction of standing bid we take

    # ----- live-trading mode -----------------------------------------------
    # "paper" (default): read the book, simulate fills/settlement/PnL — no orders.
    # "live": place real orders on Kalshi; Kalshi balance/positions/fills are the
    # source of truth. Gated by risk caps + kill switch below.
    mode: str = field(default_factory=lambda: os.environ.get("LONGSHOT_MODE", "paper").strip().lower())
    # Prefix for the deterministic client_order_id (idempotency key).
    order_id_prefix: str = field(default_factory=lambda: os.environ.get("LONGSHOT_ORDER_PREFIX", "ls").strip())
    # Safe by default: live container reconciles + reads truth + logs INTENDED orders
    # but places nothing until explicitly armed (LONGSHOT_DRY_RUN=false). This is the
    # Phase 1/2 default. Only paper mode ignores this flag.
    dry_run: bool = field(default_factory=lambda:
        os.environ.get("LONGSHOT_DRY_RUN", "true").strip().lower() not in ("0", "false", "no", "off"))

    # ----- risk caps (live mode; fail-closed) ------------------------------
    # All checked before EVERY order. A breach of max_daily_loss trips the kill
    # switch. Defaults are sized for the $100-250 canary phase.
    max_deployed_collateral: float = field(default_factory=lambda: _env_float("LONGSHOT_MAX_DEPLOYED", 200.0))
    max_per_trade_contracts: int = field(default_factory=lambda: _env_int("LONGSHOT_MAX_PER_TRADE", 1))
    max_open_positions: int = field(default_factory=lambda: _env_int("LONGSHOT_MAX_OPEN", 40))
    max_daily_loss: float = field(default_factory=lambda: _env_float("LONGSHOT_MAX_DAILY_LOSS", 25.0))
    # Sentinel kill file: if present, no new orders are placed. env LONGSHOT_KILL=1 also halts.
    kill_file: str = field(default_factory=lambda: os.environ.get("LONGSHOT_KILL_FILE", "/data/KILL"))

    state_file: str = field(default_factory=lambda: os.environ.get(
        "LONGSHOT_STATE", "/tmp/longshot_state.json"))
    history_file: str = field(default_factory=lambda: os.environ.get(
        "LONGSHOT_HISTORY", "/tmp/longshot_history.jsonl"))
    heartbeat_file: str = field(default_factory=lambda: os.environ.get(
        "LONGSHOT_HEARTBEAT", "/tmp/longshot_heartbeat.json"))

    @property
    def is_live(self) -> bool:
        return self.mode == "live"
