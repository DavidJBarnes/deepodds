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

    # -- low-level signed request ------------------------------------------
    def _request(self, method: str, path: str, params: dict | None = None,
                 json_body: dict | None = None, retry: bool = True) -> dict:
        """Signed request with optional retry. NOTE: callers that place orders
        MUST pass retry=False — a retried POST can double-submit. The kalshi
        signature covers timestamp+METHOD+path only (body excluded)."""
        attempts = [0] + (_RETRY_DELAYS if retry else [])
        for delay in attempts:
            if delay:
                time.sleep(delay)
            ts_ms = int(time.time() * 1000)
            headers = _sign(method, path, ts_ms, self._key_id, self._pem)
            resp = self._client.request(method, path, params=params, json=json_body, headers=headers)
            if 200 <= resp.status_code < 300:
                time.sleep(_REQUEST_DELAY_SEC)
                return resp.json() if resp.content else {}
            if resp.status_code == 429:
                ra = int(resp.headers.get("Retry-After", "5"))
                logger.warning("rate-limited; sleeping %ds", ra)
                time.sleep(ra)
                continue
            if resp.status_code >= 500 and retry:
                logger.warning("server error %d on %s %s", resp.status_code, method, path)
                continue
            resp.raise_for_status()
        raise RuntimeError(f"Failed after retries: {method} {path}")

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params, retry=True)

    def post(self, path: str, json_body: dict, retry: bool = False) -> dict:
        # Default retry=False: order placement is not safely retryable.
        return self._request("POST", path, json_body=json_body, retry=retry)

    def delete(self, path: str) -> dict:
        # Cancels are idempotent (cancelling a gone order is a no-op/404).
        return self._request("DELETE", path, retry=True)

    # -- orders -------------------------------------------------------------
    def create_order(self, *, ticker: str, action: str, side: str, count: int,
                     type: str = "limit", yes_price: int | None = None,
                     no_price: int | None = None, client_order_id: str,
                     **extra) -> dict:
        """POST /portfolio/orders. Prices are integer cents. Not auto-retried."""
        body = {"ticker": ticker, "action": action, "side": side,
                "count": count, "type": type, "client_order_id": client_order_id}
        if yes_price is not None:
            body["yes_price"] = int(yes_price)
        if no_price is not None:
            body["no_price"] = int(no_price)
        body.update(extra)
        return self.post("/portfolio/orders", body)

    def cancel_order(self, order_id: str) -> dict:
        return self.delete(f"/portfolio/orders/{order_id}")

    def get_order(self, order_id: str) -> dict:
        return self.get(f"/portfolio/orders/{order_id}")

    def list_orders(self, **params) -> dict:
        return self.get("/portfolio/orders", params=params or None)

    def find_order_by_client_id(self, client_order_id: str) -> dict | None:
        """Confirm-after-timeout helper: did a (maybe-)submitted order land?"""
        for o in self.list_orders(limit=200).get("orders", []):
            if o.get("client_order_id") == client_order_id:
                return o
        return None

    # -- account truth ------------------------------------------------------
    def get_balance(self) -> dict:
        return self.get("/portfolio/balance")

    def get_positions(self, **params) -> dict:
        return self.get("/portfolio/positions", params=params or None)

    def get_fills(self, **params) -> dict:
        return self.get("/portfolio/fills", params=params or None)

    def get_settlements(self, **params) -> dict:
        return self.get("/portfolio/settlements", params=params or None)

    def close(self):
        self._client.close()
