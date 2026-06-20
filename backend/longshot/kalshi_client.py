"""Minimal signed Kalshi REST client + fee formula — self-contained so the prod
image needs only the longshot package (not the research kalshi_backtest tree).

Ported from kalshi_backtest.ingest / .calibration; keep behaviour in sync.
"""
import base64
import logging
import math
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

logger = logging.getLogger("longshot.kalshi_client")

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
_API_PATH_PREFIX = "/trade-api/v2"
_REQUEST_DELAY_SEC = 0.25
_RETRY_DELAYS = [2, 4, 8]


def kalshi_fee_per_contract(price: float, n_contracts: int = 1) -> float:
    """fee = ceil_to_cent(0.07 * n * P * (1 - P)). Symmetric in P."""
    raw = 0.07 * n_contracts * price * (1 - price)
    return math.ceil(raw * 100) / 100


def _sign(method: str, path: str, ts_ms: int, key_id: str, pem_bytes: bytes) -> dict:
    ts_str = str(ts_ms)
    full_path = path if path.startswith(_API_PATH_PREFIX) else _API_PATH_PREFIX + path
    msg = ts_str + method.upper() + full_path
    pk = serialization.load_pem_private_key(pem_bytes, password=None)
    sig = pk.sign(
        msg.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": ts_str,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


class KalshiClient:
    def __init__(self, key_id: str, pem_bytes: bytes):
        self._key_id = key_id
        self._pem = pem_bytes
        self._client = httpx.Client(base_url=BASE_URL, timeout=30)

    def get(self, path: str, params: dict | None = None) -> dict:
        ts_ms = int(time.time() * 1000)
        headers = _sign("GET", path, ts_ms, self._key_id, self._pem)
        for attempt, delay in enumerate([0] + _RETRY_DELAYS):
            if delay:
                time.sleep(delay)
            resp = self._client.get(path, params=params, headers=headers)
            if resp.status_code == 200:
                time.sleep(_REQUEST_DELAY_SEC)
                return resp.json()
            if resp.status_code == 429:
                ra = int(resp.headers.get("Retry-After", "5"))
                logger.warning("rate-limited; sleeping %ds", ra)
                time.sleep(ra)
                ts_ms = int(time.time() * 1000)
                headers = _sign("GET", path, ts_ms, self._key_id, self._pem)
                continue
            if resp.status_code >= 500:
                logger.warning("server error %d on %s", resp.status_code, path)
                continue
            resp.raise_for_status()
        raise RuntimeError(f"Failed after retries: GET {path}")

    def close(self):
        self._client.close()
