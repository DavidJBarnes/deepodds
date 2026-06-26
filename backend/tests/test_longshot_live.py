"""Unit tests for the live longshot trading path: client write-safety, executor
idempotency / partial fills / confirm-after-timeout, fail-closed risk gate, and
Kalshi-truth reconciliation. No network — fakes stand in for httpx and the broker.
"""
import os

import httpx
import pytest

from longshot.config import LongshotConfig
from longshot.kalshi_client import KalshiClient
from longshot.execution import Executor
from longshot.risk import RiskGate, PortfolioRisk, is_killed, trip_kill
from longshot import reconcile


# --------------------------------------------------------------------------
# Fake httpx client for KalshiClient write-safety tests
# --------------------------------------------------------------------------
class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.content = b"x" if payload is not None else b""
        self.headers = {}
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=self)


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, params=None, json=None, headers=None):
        self.calls.append((method, path, json))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def close(self):
        pass


def _client(responses):
    c = KalshiClient("kid", _DUMMY_PEM)
    c._client = FakeHTTP(responses)
    return c


# A throwaway RSA key so _sign works in tests.
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
_DUMMY_PEM = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption())


def test_post_does_not_retry_by_default():
    # POST that 500s must raise immediately — never auto-retried (double-submit risk).
    c = _client([FakeResp(500, {})])
    with pytest.raises(httpx.HTTPStatusError):
        c.create_order(ticker="T", side="ask", count=1, price=0.05, client_order_id="x")
    assert len(c._client.calls) == 1


def test_get_retries_on_500_then_succeeds():
    c = _client([FakeResp(500), FakeResp(500), FakeResp(200, {"ok": 1})])
    # speed up retry sleeps
    import longshot.kalshi_client as K
    K._RETRY_DELAYS = [0, 0, 0]
    assert c.get("/x") == {"ok": 1}
    assert len(c._client.calls) == 3


def test_create_order_body_and_path():
    c = _client([FakeResp(201, {"order": {"order_id": "o1"}})])
    c.create_order(ticker="KXHIGH-1", side="ask", count=3, price=0.11,
                   client_order_id="ls-KXHIGH-1-42")
    method, path, body = c._client.calls[0]
    assert method == "POST" and path == "/portfolio/events/orders"   # V2, not deprecated v1
    assert body["side"] == "ask"                                      # sell YES
    assert body["count"] == "3.00" and body["price"] == "0.1100"      # fixed-point strings
    assert body["time_in_force"] == "immediate_or_cancel"            # marketable take + auto-cancel
    assert body["self_trade_prevention_type"] == "taker_at_cross"
    assert body["client_order_id"] == "ls-KXHIGH-1-42"


# --------------------------------------------------------------------------
# Executor: idempotency, partial fill, confirm-after-timeout, dry-run
# --------------------------------------------------------------------------
class FakeBroker:
    """Duck-typed KalshiClient for the executor."""
    def __init__(self, *, create=None, create_exc=None, fills=None, found=None):
        self._create = create
        self._create_exc = create_exc
        self._fills = fills or []
        self._found = found
        self.cancelled = []

    def create_order(self, **kw):
        if self._create_exc:
            raise self._create_exc
        return self._create

    def find_order_by_client_id(self, coid):
        return self._found

    def get_fills(self, **kw):
        return {"fills": self._fills}

    def cancel_order(self, oid):
        self.cancelled.append(oid)
        return {}


def test_client_order_id_is_deterministic():
    ex = Executor(FakeBroker(), "ls")
    assert ex.client_order_id("KXHIGHNY-X", 100) == ex.client_order_id("KXHIGHNY-X", 100)
    assert ex.client_order_id("KXHIGHNY-X", 100) != ex.client_order_id("KXHIGHNY-X", 101)


def test_client_order_id_strips_dot():
    # Kalshi 400s on client_order_id containing '.' (B-bracket tickers like B89.5).
    ex = Executor(FakeBroker(), "ls")
    coid = ex.client_order_id("KXHIGHDEN-26JUN24-B89.5", 495085)
    assert "." not in coid
    assert coid == ex.client_order_id("KXHIGHDEN-26JUN24-B89.5", 495085)  # deterministic


def test_dry_run_places_nothing():
    broker = FakeBroker()
    ex = Executor(broker, "ls", dry_run=True)
    r = ex.place_short(ticker="T", sell_price=0.10, count=1, tick_epoch=5)
    assert r.status == "dryrun" and r.filled_count == 0 and not broker.cancelled


def test_partial_fill_books_actual_no_explicit_cancel():
    # IOC auto-cancels the unfilled remainder — we must NOT issue a cancel.
    broker = FakeBroker(
        create={"order": {"order_id": "o9"}},
        fills=[{"count": 2, "yes_price": 10}],   # asked 5, only 2 filled
    )
    ex = Executor(broker, "ls")
    r = ex.place_short(ticker="T", sell_price=0.10, count=5, tick_epoch=1)
    assert r.status == "partial" and r.filled_count == 2
    assert abs(r.avg_price - 0.10) < 1e-9
    assert broker.cancelled == []              # IOC handles the remainder


def test_fill_parsed_from_v2_response_inline():
    # V2 returns fill_count/average_fill_price/average_fee_paid inline — use it,
    # don't depend on polling get_fills.
    broker = FakeBroker(create={"order": {
        "order_id": "o1", "fill_count": "1.00",
        "average_fill_price": "0.1100", "average_fee_paid": "0.0069",
        "remaining_count": "0.00"}}, fills=[])   # fills empty on purpose
    ex = Executor(broker, "ls")
    r = ex.place_short(ticker="T", sell_price=0.11, count=1, tick_epoch=1)
    assert r.status == "filled" and r.filled_count == 1
    assert r.avg_price == 0.11
    assert r.fee == 0.0069                       # real raw fee, not ceil-to-cent


def test_full_fill_no_cancel():
    broker = FakeBroker(create={"order": {"order_id": "o1"}},
                        fills=[{"count": 3, "yes_price": 11}])
    ex = Executor(broker, "ls")
    r = ex.place_short(ticker="T", sell_price=0.11, count=3, tick_epoch=1)
    assert r.status == "filled" and r.filled_count == 3 and broker.cancelled == []


def test_timeout_confirms_before_giving_up():
    # POST times out but the order actually landed — must confirm, not error/resubmit.
    broker = FakeBroker(create_exc=httpx.TimeoutException("boom"),
                        found={"order_id": "o7"}, fills=[{"count": 1, "yes_price": 9}])
    ex = Executor(broker, "ls")
    r = ex.place_short(ticker="T", sell_price=0.09, count=1, tick_epoch=1)
    assert r.order_id == "o7" and r.status == "filled" and r.filled_count == 1


def test_timeout_unconfirmed_is_error_not_resubmit():
    broker = FakeBroker(create_exc=httpx.TimeoutException("boom"), found=None)
    ex = Executor(broker, "ls")
    r = ex.place_short(ticker="T", sell_price=0.09, count=1, tick_epoch=1)
    assert r.status == "error" and r.filled_count == 0


# --------------------------------------------------------------------------
# Risk gate: fail-closed
# --------------------------------------------------------------------------
def _cfg(tmp_path, **over):
    kw = dict(max_deployed_collateral=200.0, max_per_trade_contracts=1,
              max_open_positions=3, max_daily_loss=25.0,
              kill_file=str(tmp_path / "KILL"))
    kw.update(over)
    return LongshotConfig(**kw)


def test_per_trade_cap(tmp_path):
    g = RiskGate(_cfg(tmp_path))
    pr = PortfolioRisk(0, 0, 0)
    assert not g.check_order(pr, contracts=2, collateral=1).allow   # cap is 1
    assert g.check_order(pr, contracts=1, collateral=1).allow


def test_deployed_cap(tmp_path):
    g = RiskGate(_cfg(tmp_path))
    pr = PortfolioRisk(deployed_collateral=199.5, open_positions=0, realized_pnl_today=0)
    assert not g.check_order(pr, contracts=1, collateral=1.0).allow   # 200.5 > 200


def test_open_positions_cap(tmp_path):
    g = RiskGate(_cfg(tmp_path))
    pr = PortfolioRisk(0, 3, 0)
    assert not g.check_order(pr, contracts=1, collateral=1).allow


def test_daily_loss_trips_kill(tmp_path):
    cfg = _cfg(tmp_path)
    g = RiskGate(cfg)
    pr = PortfolioRisk(0, 0, realized_pnl_today=-30.0)
    assert not g.pretick(pr).allow
    assert is_killed(cfg)                       # sentinel was written
    # and it persists: a fresh gate refuses too
    assert not RiskGate(cfg).pretick(PortfolioRisk(0, 0, 0)).allow


def test_kill_file_blocks_orders(tmp_path):
    cfg = _cfg(tmp_path)
    trip_kill(cfg, "manual")
    g = RiskGate(cfg)
    assert not g.check_order(PortfolioRisk(0, 0, 0), contracts=1, collateral=1).allow


def test_env_kill_switch(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setenv("LONGSHOT_KILL", "1")
    assert is_killed(cfg)


# --------------------------------------------------------------------------
# Reconciliation: Kalshi is truth
# --------------------------------------------------------------------------
def test_apply_settlements_books_real_outcome():
    state = {"positions": [
        {"ticker": "A", "status": "open", "sell_price": 0.1, "size": 10, "fee": 0.07,
         "result": None, "pnl": None},
        {"ticker": "B", "status": "open", "sell_price": 0.1, "size": 10, "fee": 0.07,
         "result": None, "pnl": None},
    ]}
    settlements = [{"ticker": "A", "market_result": "no", "revenue": 100}]  # gross payout, ignored
    n = reconcile.apply_settlements(state, settlements)
    a = state["positions"][0]
    assert n == 1 and a["status"] == "settled" and a["result"] == "no"
    # NET P&L (premium kept - fee), NOT Kalshi's gross $1/contract revenue
    assert a["pnl"] == pytest.approx(0.93) and a["settled_ts"]  # 0.1*10 - 0.07
    assert state["positions"][1]["status"] == "open"   # B not settled


def test_apply_settlements_fallback_when_no_money():
    state = {"positions": [{"ticker": "A", "status": "open", "sell_price": 0.1,
                            "size": 10, "fee": 0.07, "result": None, "pnl": None}]}
    reconcile.apply_settlements(state, [{"ticker": "A", "result": "yes"}])
    # loss = -(1-0.1)*10 - 0.07
    assert state["positions"][0]["pnl"] == pytest.approx(-9.07)


def test_adopt_orphans_flags_unknown_positions():
    state = {"positions": [{"ticker": "KNOWN", "status": "open"}]}
    positions = [{"ticker": "KNOWN", "position": -5},
                 {"ticker": "KXHIGHNY-ORPH", "position": -3},
                 {"ticker": "ZERO", "position": 0}]
    n = reconcile.adopt_orphans(state, positions)
    assert n == 1
    orph = [p for p in state["positions"] if p["ticker"] == "KXHIGHNY-ORPH"][0]
    assert orph["adopted"] and orph["size"] == 3


def test_realized_pnl_today():
    from datetime import datetime, timezone
    now = datetime(2026, 6, 24, 12, tzinfo=timezone.utc)
    state = {"positions": [
        {"status": "settled", "pnl": 5.0, "settled_ts": "2026-06-24T01:00:00+00:00"},
        {"status": "settled", "pnl": -20.0, "settled_ts": "2026-06-24T02:00:00+00:00"},
        {"status": "settled", "pnl": 3.0, "settled_ts": "2026-06-23T23:00:00+00:00"},  # yesterday
    ]}
    assert reconcile.realized_pnl_today(state, now) == -15.0


def test_live_equity_comes_from_kalshi_not_account(tmp_path):
    cfg = _cfg(tmp_path)          # cfg.account is the simulated number
    state = {"positions": [{"status": "open", "collateral": 0.9}]}
    snap = reconcile.live_snapshot(cfg, state, {"balance_dollars": 5.22})
    assert snap["balance"] == 5.22
    assert snap["equity"] == 6.12          # balance + deployed collateral
    assert snap["equity"] != cfg.account   # never the made-up account size


def test_live_equity_null_when_kalshi_unreachable(tmp_path):
    snap = reconcile.live_snapshot(_cfg(tmp_path), {"positions": []}, {"balance_dollars": None})
    assert snap["balance"] is None and snap["equity"] is None   # no fabricated number


def test_available_balance_caps_orders(tmp_path):
    g = RiskGate(_cfg(tmp_path))
    over = PortfolioRisk(deployed_collateral=5.0, open_positions=1,
                         realized_pnl_today=0, available_balance=5.22)
    assert not g.check_order(over, contracts=1, collateral=0.9).allow   # 5.9 > 5.22
    ok = PortfolioRisk(deployed_collateral=4.0, open_positions=1,
                       realized_pnl_today=0, available_balance=5.22)
    assert g.check_order(ok, contracts=1, collateral=0.9).allow         # 4.9 <= 5.22


def test_slippage_stats():
    state = {"positions": [
        {"intended_price": 0.10, "avg_fill_price": 0.10, "intended_size": 5, "filled_size": 5},
        {"intended_price": 0.11, "avg_fill_price": 0.09, "intended_size": 4, "filled_size": 2},
    ]}
    s = reconcile.slippage_stats(state)
    assert s["orders"] == 2
    assert s["fill_rate"] == pytest.approx(7 / 9, abs=1e-3)
    # slippage cents: (0.10-0.10)*100=0 and (0.11-0.09)*100=2 -> mean 1.0
    assert s["avg_slippage_c"] == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Canonical net-pnl + self-healing (the 2026-06-25 gross-revenue artifact)
# --------------------------------------------------------------------------
def test_net_pnl_win_and_loss():
    assert reconcile.net_pnl(0.10, 10, 0.07, "no") == pytest.approx(0.93)    # keep premium
    assert reconcile.net_pnl(0.10, 10, 0.07, "yes") == pytest.approx(-9.07)  # lose collateral


def test_heal_settled_pnl_corrects_gross_and_is_idempotent():
    # A win mis-booked as Kalshi gross ($1/ct) instead of the net premium.
    state = {"positions": [
        {"ticker": "STALE", "status": "settled", "result": "no",
         "sell_price": 0.01, "size": 1, "fee": 0.001, "pnl": 2.0},          # phantom
        {"ticker": "OK", "status": "settled", "result": "no",
         "sell_price": 0.05, "size": 1, "fee": 0.003, "pnl": 0.047},        # already correct
    ]}
    n = reconcile.heal_settled_pnl(state)
    assert n == 1                                                            # only STALE healed
    assert state["positions"][0]["pnl"] == pytest.approx(0.009)             # 0.01 - 0.001
    assert reconcile.heal_settled_pnl(state) == 0                            # idempotent


def test_heal_skips_open_and_adopted():
    state = {"positions": [
        {"ticker": "OPEN", "status": "open", "sell_price": 0.1, "size": 1, "fee": 0.0, "pnl": None},
        {"ticker": "ORPH", "status": "settled", "result": "no",             # adopted: no entry px
         "sell_price": None, "size": 3, "fee": 0.0, "pnl": 0.5},
    ]}
    assert reconcile.heal_settled_pnl(state) == 0
    assert state["positions"][1]["pnl"] == 0.5                              # untouched


def test_settled_win_pnl_never_exceeds_premium():
    # Invariant guard: a healed short-YES win can never profit more than the premium.
    state = {"positions": [
        {"ticker": "W", "status": "settled", "result": "no",
         "sell_price": 0.08, "size": 2, "fee": 0.01, "pnl": 5.0},
    ]}
    reconcile.heal_settled_pnl(state)
    p = state["positions"][0]
    assert p["pnl"] <= p["sell_price"] * p["size"] + 1e-9


def test_paper_resolve_sets_settled_ts_and_net_pnl():
    from datetime import datetime, timezone
    from longshot import paper_run

    class FakeClient:
        def get(self, path, **kw):
            return {"market": {"result": "no"}}

    now = datetime(2026, 6, 26, 12, tzinfo=timezone.utc)
    state = {"positions": [
        {"ticker": "KXHIGHNY-X", "status": "open", "close_time": "2026-06-26T04:59:00+00:00",
         "sell_price": 0.1, "size": 3, "fee": 0.02, "result": None, "pnl": None},
    ]}
    n = paper_run._resolve(None, FakeClient(), state, now)
    p = state["positions"][0]
    assert n == 1 and p["status"] == "settled" and p["result"] == "no"
    assert p["pnl"] == pytest.approx(0.28)                  # 0.1*3 - 0.02, canonical net
    assert p["settled_ts"] == now.isoformat()              # enables time-windowed reporting
