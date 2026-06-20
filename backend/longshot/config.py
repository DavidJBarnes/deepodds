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


# Temperature cities trade year-round; football (NFL/NCAA) seasonal. The
# validated edge lives in these categories — do NOT trade a blanket band.
TEMP_CITIES = ("NY", "CHI", "LAX", "MIA", "AUS", "DEN", "PHIL", "HOU", "ATL",
               "BOS", "SEA", "DC", "PHX", "MINN", "DET", "DAL", "SF", "SLC")
FOOTBALL_SERIES = ("KXNFLFIRST", "KXNFLATD", "KXNCAAFGAME")


@dataclass
class LongshotConfig:
    whitelist: tuple = field(default_factory=lambda: tuple(
        [f"KXHIGH{c}" for c in TEMP_CITIES] + list(FOOTBALL_SERIES)))
    band: tuple = (0.01, 0.12)         # cheap longshot YES band ($)
    max_hours_to_close: float = 30.0   # ~1-day horizon
    account: float = 8_000.0           # paper account size
    trade_fraction: float = 0.005      # collateral per trade (low-DD config)
    max_depth_frac: float = 0.25       # max fraction of standing bid we take

    state_file: str = field(default_factory=lambda: os.environ.get(
        "LONGSHOT_STATE", "/tmp/longshot_state.json"))
    history_file: str = field(default_factory=lambda: os.environ.get(
        "LONGSHOT_HISTORY", "/tmp/longshot_history.jsonl"))
    heartbeat_file: str = field(default_factory=lambda: os.environ.get(
        "LONGSHOT_HEARTBEAT", "/tmp/longshot_heartbeat.json"))
