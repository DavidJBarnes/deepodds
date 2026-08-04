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
# HOU removed 2026-08-04: KXHIGHHOU is DEAD (0 open markets; verified via the public
# /series + /markets API). Kalshi migrated it to KXHIGHTHOU — same settlement oracle
# (NWS CLI Houston, HGX) — but that belongs to the KXHIGHT* generation which BACKTESTED
# SIGNIFICANTLY WORSE (-0.66c/ct pooled, YES 4.09% vs control 2.32%, p~0.03), so it is
# NOT a drop-in swap and must be backtested on its own before any whitelist entry.
# Leaving the dead string cost an API call per series per tick and, worse, made the
# whitelist read as 8 cities while trading 7 — the same silent-failure class as the
# KXNFLFIRST/KXNFLATD 404s that meant NFL never fired at all.
TEMP_CITIES = ("NY", "CHI", "LAX", "MIA", "AUS", "DEN", "PHIL")
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


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name, "").strip().lower()
    if not v:
        return default
    return v not in ("0", "false", "no", "off")


# Default whitelist: temp (year-round) + sports props (seasonal).
_DEFAULT_WHITELIST = tuple([f"KXHIGH{c}" for c in TEMP_CITIES] + list(SPORTS_SERIES))


def _env_whitelist() -> tuple:
    """LONGSHOT_WHITELIST (comma-separated) overrides the default whitelist so a
    single image can run per-vein paper arms (e.g. sports-game tails, crypto tails)
    without code changes. Empty/unset -> the validated default."""
    v = os.environ.get("LONGSHOT_WHITELIST", "").strip()
    if not v:
        return _DEFAULT_WHITELIST
    return tuple(s.strip().upper() for s in v.split(",") if s.strip())


@dataclass
class LongshotConfig:
    whitelist: tuple = field(default_factory=_env_whitelist)
    band: tuple = (0.01, 0.12)         # cheap longshot YES band ($)
    max_hours_to_close: float = 30.0   # ~1-day horizon
    account: float = field(default_factory=lambda: _env_float("LONGSHOT_ACCOUNT", 8_000.0))
    trade_fraction: float = field(default_factory=lambda: _env_float("LONGSHOT_TRADE_FRACTION", 0.005))
    max_depth_frac: float = 0.25       # max fraction of standing bid we take

    # ----- OI selection filter (default OFF) --------------------------------
    # Open interest partitions the longshot universe at oi_max. Two directions:
    #   oi_keep_high=False (LOW-OI): trade only oi <= oi_max  (skip oi > oi_max)
    #   oi_keep_high=True  (HIGH-OI): trade only oi >  oi_max  (skip oi <= oi_max)
    # Backtest #209 favored LOW-OI, but that backtest is biased (s3_markets_low is a
    # cheap-selected ingest -> ~0% YES in temp -> it can't test loss-avoidance; see
    # VERDICT_BACKTEST_BIAS.md). LIVE-forward data (which has real losses) says the
    # opposite: HIGH-OI is the SAFER bucket (YES 1.3% vs 4.7%, +3.2c vs -1.0c).
    # So the paper A/B now forward-tests HIGH-OI. Default OFF => LIVE unchanged.
    # entry_oi is always RECORDED regardless of this flag.
    oi_filter_enabled: bool = field(default_factory=lambda: _env_bool("LONGSHOT_OI_FILTER", False))
    oi_max: float = field(default_factory=lambda: _env_float("LONGSHOT_OI_MAX", 968.0))
    oi_keep_high: bool = field(default_factory=lambda: _env_bool("LONGSHOT_OI_KEEP_HIGH", False))

    # ----- per-underlying correlation cap (default OFF = 0) -----------------
    # Max open collateral in one correlation group (all BTC tails = one trade; a
    # single 10% BTC day resolves them together). 0 disables. Mandatory for the
    # crypto-tails arm; barely binds on temp/sports (independent events).
    max_underlying_collateral: float = field(default_factory=lambda: _env_float("LONGSHOT_MAX_UNDERLYING", 0.0))

    # ----- Deribit oracle gate (default OFF) -------------------------------
    # For the crypto-tails arm: sell a Kalshi tail ONLY when its mid exceeds the
    # Deribit risk-neutral fair by >= oracle_min_edge (rent the sharp venue's price;
    # don't sell tails Deribit says are fairly priced). Fail-closed: if Deribit is
    # unreachable, discovery places nothing. Default OFF => temp/sports/live unchanged.
    oracle_gate_enabled: bool = field(default_factory=lambda: _env_bool("LONGSHOT_ORACLE_GATE", False))
    oracle_min_edge: float = field(default_factory=lambda: _env_float("LONGSHOT_ORACLE_MIN_EDGE", 0.005))
    # Model-free tail-distance floor: only sell tails at least this fraction OTM (strike
    # vs spot). Near-money short-horizon crypto tails are POISON — our BS Deribit-fair has
    # no jump term so it underprices them, the gate wrongly clears them, and a normal ~2%
    # move resolves them YES (the 2026-07-10 -$100 day was all ~2%-OTM tails). Default 0.
    oracle_min_otm: float = field(default_factory=lambda: _env_float("LONGSHOT_ORACLE_MIN_OTM", 0.0))

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
