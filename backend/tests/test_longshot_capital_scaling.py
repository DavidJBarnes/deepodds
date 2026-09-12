"""Capital scaling for the LIVE longshot arm (2026-09-12): added capital must flow.

Two defects meant a deposit did nothing — or less than nothing:

1. MAX_PER_TRADE REJECTED oversized orders instead of trimming them. Clip size is
   equity*0.04/(1-p), so once equity crossed 650*(1-p) (~$572 at 12c, ~$644 at 1c) the
   gate dropped every deep-book candidate at that price, every tick. Prod on 09-12 at
   $624 equity: `risk skip KXHIGHLAX-26SEP12-B79.5: per-trade 27 > cap 25`. A deposit to
   ~$1k would have rejected nearly the whole deep book.
2. MAX_DEPLOYED / MAX_DAILY_LOSS were fixed dollars that any growth left behind:
   deployed sat at >=445 of 450 on 73 of 168 ticks.

Fix: live trims to the per-trade cap; the deployed and daily-loss caps scale with
equity, the absolutes kept as ceilings. The gate still rejects >cap as a backstop.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from longshot import live_run, reconcile
from longshot.config import LongshotConfig
from longshot.kalshi_client import kalshi_fee_per_contract as fee
from longshot.live_run import trim_to_cap
from longshot.paper_run import size_candidate
from longshot.risk import PortfolioRisk, RiskGate

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
CLOSE = "2030-01-01T10:00:00Z"
BAND = (0.01, 0.02, 0.04, 0.05, 0.08, 0.10, 0.12)
COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"
LIVE_SERVICE = "longshot-live"
CAP_KEYS = ("LONGSHOT_TRADE_FRACTION", "LONGSHOT_MAX_PER_TRADE", "LONGSHOT_MAX_OPEN",
            "LONGSHOT_MAX_DEPLOYED", "LONGSHOT_MAX_DEPLOYED_FRAC",
            "LONGSHOT_MAX_DAILY_LOSS", "LONGSHOT_MAX_DAILY_LOSS_FRAC")


def _market(yb, bid_size=1000.0, ticker="KXHIGHNY-30JAN01-T80", close=CLOSE):
    return {"ticker": ticker, "yes_ask_dollars": yb, "yes_bid_dollars": yb,
            "yes_bid_size_fp": bid_size, "close_time": close, "open_interest_fp": 500.0}


def _cfg(tmp_path, **over):
    kw = dict(trade_fraction=0.04, max_per_trade_contracts=50, max_open_positions=120,
              max_deployed_collateral=2000.0, max_deployed_frac=0.85,
              max_daily_loss=250.0, max_daily_loss_frac=0.15,
              kill_file=str(tmp_path / "KILL"))
    kw.update(over)
    return LongshotConfig(**kw)


def _old_cfg(tmp_path):
    """The caps live ran with through 2026-09-12: fixed dollars, no scaling."""
    return _cfg(tmp_path, max_per_trade_contracts=25, max_deployed_collateral=450.0,
                max_deployed_frac=0.0, max_daily_loss=85.0, max_daily_loss_frac=0.0)


def _pr(equity, deployed=0.0, realized=0.0, balance=None):
    return PortfolioRisk(deployed_collateral=deployed, open_positions=0,
                         realized_pnl_today=realized,
                         available_balance=equity - deployed if balance is None else balance,
                         equity=equity)


# --- trim, don't reject ------------------------------------------------------


def test_oversized_clip_is_trimmed_to_the_cap():
    c = size_candidate(LongshotConfig(trade_fraction=0.04), _market(0.05), "KXHIGHNY", NOW, 1500.0, 0.0)
    assert c["size"] == int(1500 * 0.04 / 0.95) == 63
    t = trim_to_cap(c, 50)
    assert t["size"] == 50 and t["trimmed_from"] == 63
    assert c["size"] == 63 and "trimmed_from" not in c      # input not mutated


def test_trimmed_clip_prices_exactly_like_a_native_clip_of_that_size():
    """Collateral and fee must be recomputed at the trimmed size. Booking the untrimmed
    collateral would overstate exposure and choke the deployed cap for no reason."""
    cfg = LongshotConfig(trade_fraction=0.04)
    big = size_candidate(cfg, _market(0.12), "KXHIGHNY", NOW, 2000.0, 0.0)
    native = size_candidate(cfg, _market(0.12), "KXHIGHNY", NOW, 1105.0, 0.0)
    assert native["size"] == 50 and big["size"] > 50
    t = trim_to_cap(big, 50)
    for k in ("size", "collateral", "fee", "sell_price", "ticker", "close_time", "bid_depth"):
        assert t[k] == native[k], k
    assert t["fee"] == round(fee(0.12, 50), 4)


def test_clip_under_the_cap_is_untouched():
    c = size_candidate(LongshotConfig(trade_fraction=0.04), _market(0.05), "KXHIGHNY", NOW, 624.21, 0.0)
    assert c["size"] == 26
    assert trim_to_cap(c, 50) is c


def test_clip_exactly_at_the_cap_is_not_marked_trimmed():
    c = size_candidate(LongshotConfig(trade_fraction=0.04), _market(0.12), "KXHIGHNY", NOW, 1105.0, 0.0)
    assert c["size"] == 50 and "trimmed_from" not in trim_to_cap(c, 50)


def test_thin_books_stay_depth_governed(tmp_path):
    """Raising the ceiling must not let a clip outgrow the book: 0.25 * bid still rules."""
    c = size_candidate(_cfg(tmp_path), _market(0.05, bid_size=40), "KXHIGHNY", NOW, 1125.0, 0.0)
    assert c["size"] == 10
    assert trim_to_cap(c, 50) is c


def test_gate_still_rejects_above_cap_as_a_backstop(tmp_path):
    d = RiskGate(_cfg(tmp_path)).check_order(_pr(1000.0), contracts=51, collateral=48.45)
    assert not d.allow and "per-trade" in d.reason


REJECTED_AT_624 = (0.04, 0.05, 0.08, 0.10, 0.12)


@pytest.mark.parametrize("yb", REJECTED_AT_624)
def test_regression_0912_per_trade_cap_rejected_instead_of_trimming(tmp_path, yb):
    """Prod 09-12, equity $624.21, deep book: the 4c+ clip sizes to 26-28 > cap 25 and the
    old path rejected it outright. Trimmed to the same cap, it clears."""
    old = _old_cfg(tmp_path)
    gate = RiskGate(old)
    c = size_candidate(old, _market(yb), "KXHIGHNY", NOW, 624.21, 0.0)
    assert c["size"] > 25
    assert not gate.check_order(_pr(624.21), contracts=c["size"], collateral=c["collateral"]).allow
    t = trim_to_cap(c, old.max_per_trade_contracts)
    assert gate.check_order(_pr(624.21), contracts=t["size"], collateral=t["collateral"]).allow


@pytest.mark.parametrize("yb", BAND)
def test_a_deposit_to_1k_would_have_rejected_every_deep_book(tmp_path, yb):
    """The failure the user was worried about, stated directly: on the old path, adding
    money made the strategy trade LESS. On the new one every deep-book candidate clears."""
    old = _old_cfg(tmp_path)
    c = size_candidate(old, _market(yb), "KXHIGHNY", NOW, 1000.0, 0.0)
    assert c["size"] > 25
    assert not RiskGate(old).check_order(_pr(1000.0), contracts=c["size"], collateral=c["collateral"]).allow
    new = _cfg(tmp_path)
    t = trim_to_cap(c, new.max_per_trade_contracts)
    assert t is c                                           # 50 doesn't even bind at $1k
    assert RiskGate(new).check_order(_pr(1000.0), contracts=t["size"], collateral=t["collateral"]).allow


# --- deployed cap scales with equity ----------------------------------------


@pytest.mark.parametrize("equity", (624.21, 1000.0, 1125.0))
def test_deployed_cap_scales_with_equity(tmp_path, equity):
    assert RiskGate(_cfg(tmp_path)).deployed_cap(_pr(equity)) == pytest.approx(0.85 * equity)


def test_deployed_absolute_is_a_ceiling(tmp_path):
    assert RiskGate(_cfg(tmp_path)).deployed_cap(_pr(10_000.0)) == 2000.0


def test_deployed_cap_falls_back_to_absolute(tmp_path):
    no_equity = PortfolioRisk(0.0, 0, 0.0, available_balance=None, equity=None)
    assert RiskGate(_cfg(tmp_path)).deployed_cap(no_equity) == 2000.0
    # fraction off => the fixed cap, exactly as before this change
    assert RiskGate(_cfg(tmp_path, max_deployed_frac=0.0)).deployed_cap(_pr(1000.0)) == 2000.0


def test_check_order_enforces_the_effective_deployed_cap(tmp_path):
    g = RiskGate(_cfg(tmp_path))
    assert g.check_order(_pr(1000.0, deployed=800.0), contracts=40, collateral=40.0).allow   # 840 <= 850
    d = g.check_order(_pr(1000.0, deployed=820.0), contracts=40, collateral=40.0)
    assert not d.allow and "cap 850.00" in d.reason                                          # 860 > 850


def test_deployed_cap_does_not_move_as_the_tick_fills(tmp_path):
    """equity is captured once per tick; fills move cash to collateral 1:1. If the cap
    were recomputed from running totals it would inflate with every fill (#224)."""
    g = RiskGate(_cfg(tmp_path))
    pr = _pr(1000.0)
    before = g.deployed_cap(pr)
    pr.deployed_collateral += 300.0
    pr.deployed_this_tick += 300.0
    assert g.deployed_cap(pr) == before


# --- daily-loss breaker scales with START-OF-DAY equity ---------------------


def test_daily_loss_cap_scales_with_equity(tmp_path):
    assert RiskGate(_cfg(tmp_path)).daily_loss_cap(_pr(1000.0)) == pytest.approx(150.0)


def test_daily_loss_cap_does_not_tighten_as_losses_land(tmp_path):
    """Realized losses leave the balance, so equity falls through a bad day. Off live
    equity, a $1,000 day-start down $140 would read 0.15*860 = $129 and trip early."""
    g = RiskGate(_cfg(tmp_path))
    assert g.daily_loss_cap(_pr(860.0, realized=-140.0)) == pytest.approx(150.0)
    assert g.pretick(_pr(860.0, realized=-140.0)).allow
    assert not (tmp_path / "KILL").exists()
    assert not g.pretick(_pr(849.0, realized=-151.0)).allow
    assert (tmp_path / "KILL").exists()


def test_daily_loss_start_of_day_base_nets_out_wins_too(tmp_path):
    assert RiskGate(_cfg(tmp_path)).daily_loss_cap(_pr(1050.0, realized=50.0)) == pytest.approx(150.0)


def test_daily_loss_absolute_is_a_ceiling_and_fallback(tmp_path):
    g = RiskGate(_cfg(tmp_path))
    assert g.daily_loss_cap(_pr(5000.0)) == 250.0
    assert g.daily_loss_cap(PortfolioRisk(0.0, 0, 0.0, equity=None)) == 250.0


def test_daily_loss_with_fraction_off_is_unchanged(tmp_path):
    g = RiskGate(_cfg(tmp_path, max_daily_loss=85.0, max_daily_loss_frac=0.0))
    assert g.daily_loss_cap(_pr(5000.0)) == 85.0


# --- end to end: a real live tick at post-deposit equity ---------------------


class _FakeClient:
    def __init__(self, markets, balance):
        self.markets, self.balance = markets, balance

    def get(self, path, params=None):
        assert path == "/markets"
        return {"markets": self.markets}

    def get_balance(self):
        return {"balance": int(round(self.balance * 100))}

    def close(self):
        pass


def _tick(monkeypatch, tmp_path, cfg, equity):
    """One live_run.run_once against a fake broker: an empty book, `equity` in free
    cash, and one deep market per price in BAND closing in 10h."""
    close = (datetime.now(timezone.utc) + timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    markets = [_market(yb, ticker=f"KXHIGHNY-30JAN01-B{i}", close=close) for i, yb in enumerate(BAND)]
    placed = []

    class _Exec:
        def __init__(self, client, prefix, dry_run=False):
            pass

        def place_short(self, *, ticker, sell_price, count, tick_epoch):
            placed.append((ticker, sell_price, count))
            return SimpleNamespace(status="filled", avg_price=sell_price, filled_count=count,
                                   fee=fee(sell_price, count), client_order_id=f"ls-{ticker}",
                                   order_id=f"o-{ticker}")

    monkeypatch.delenv("LONGSHOT_KILL", raising=False)
    monkeypatch.setattr(live_run, "load_kalshi_creds", lambda: ("kid", b"pem"))
    monkeypatch.setattr(live_run, "KalshiClient", lambda k, p: _FakeClient(markets, equity))
    monkeypatch.setattr(live_run, "Executor", _Exec)
    monkeypatch.setattr(reconcile, "fetch_truth",
                        lambda client: {"balance_dollars": equity, "positions": [], "settlements": []})
    cfg.whitelist = ("KXHIGHNY",)
    cfg.oracle_gate_enabled = False
    cfg.state_file = str(tmp_path / "state.json")
    snap = live_run.run_once(cfg, dry_run=False)
    return placed, snap, live_run._load_state(cfg.state_file)


def test_live_tick_places_the_whole_band_at_top_of_deposit_range(monkeypatch, tmp_path):
    equity = 1125.0
    placed, snap, state = _tick(monkeypatch, tmp_path, _cfg(tmp_path), equity)
    assert len(placed) == len(BAND)                          # nothing gated
    sizes = {p: n for _, p, n in placed}
    for yb in BAND:
        assert sizes[yb] == min(int(equity * 0.04 / (1 - yb)), 50)
    assert sizes[0.12] == 50                                 # 51 -> trimmed, not dropped
    trimmed = {p["sell_price"]: p["trimmed_from"] for p in state["positions"]}
    assert trimmed[0.12] == 51 and trimmed[0.01] is None
    assert snap["deployed_cap"] == 956.25 and snap["daily_loss_cap"] == 168.75


def test_live_tick_trims_in_the_real_path_not_just_the_helper(monkeypatch, tmp_path):
    """Same $1k tick with the old 25 ceiling: before the fix this placed ZERO orders
    (every clip was 40-45 > 25). Now all seven go through at 25."""
    placed, _, state = _tick(monkeypatch, tmp_path, _cfg(tmp_path, max_per_trade_contracts=25), 1000.0)
    assert [n for _, _, n in placed] == [25] * len(BAND)
    assert all(p["trimmed_from"] > 25 for p in state["positions"])


def test_live_tick_books_trimmed_collateral(monkeypatch, tmp_path):
    placed, snap, state = _tick(monkeypatch, tmp_path, _cfg(tmp_path, max_per_trade_contracts=25), 1000.0)
    expected = round(sum(round((1 - p) * n, 2) for _, p, n in placed), 2)
    assert snap["deployed_collateral"] == expected
    assert all(p["collateral"] == round((1 - p["sell_price"]) * 25, 2) for p in state["positions"])


def test_live_tick_still_stops_at_the_effective_deployed_cap(monkeypatch, tmp_path):
    """Scaling must not remove the exposure cap. Clips are 4% of equity, so seven of them
    can't reach an 85% cap; use a 10% fraction ($100 on $1k) that ~40-dollar clips fill
    after two, and check the rest are skipped rather than placed."""
    placed, snap, _ = _tick(monkeypatch, tmp_path, _cfg(tmp_path, max_deployed_frac=0.10), 1000.0)
    assert 0 < len(placed) < len(BAND)
    assert snap["deployed_collateral"] <= 100.0
    assert snap["deployed_cap"] == 100.0


# --- compose: prod actually carries the scaling ------------------------------


def _live_env() -> dict:
    with COMPOSE.open() as fh:
        entries = yaml.safe_load(fh)["services"][LIVE_SERVICE].get("environment") or []
    out = {}
    for item in entries:
        key, _, value = str(item).partition("=")
        out[key.strip()] = value.split("#")[0].strip()
    return out


def _compose_cfg(monkeypatch, tmp_path) -> LongshotConfig:
    env = _live_env()
    for k in CAP_KEYS:
        monkeypatch.setenv(k, env[k])
    cfg = LongshotConfig()
    cfg.kill_file = str(tmp_path / "KILL")
    return cfg


def test_live_compose_turns_scaling_on():
    env = _live_env()
    for k in CAP_KEYS:
        assert k in env, f"{k} missing from {LIVE_SERVICE}"
    assert float(env["LONGSHOT_MAX_DEPLOYED_FRAC"]) > 0
    assert float(env["LONGSHOT_MAX_DAILY_LOSS_FRAC"]) > 0


@pytest.mark.parametrize("equity", (624.21, 875.0, 1000.0, 1125.0))
def test_compose_caps_let_the_planned_deposit_flow(monkeypatch, tmp_path, equity):
    """Planned: $250-500 on $624. Across that range, with the literal compose values,
    every deep-book candidate clears the gate and the FRACTIONS bind, not the ceilings —
    so the caps genuinely scale rather than stall at a fixed dollar figure again."""
    cfg = _compose_cfg(monkeypatch, tmp_path)
    g = RiskGate(cfg)
    pr = _pr(equity)
    assert g.deployed_cap(pr) == pytest.approx(cfg.max_deployed_frac * equity)
    assert g.daily_loss_cap(pr) == pytest.approx(cfg.max_daily_loss_frac * equity)
    for yb in BAND:
        c = trim_to_cap(size_candidate(cfg, _market(yb), "KXHIGHNY", NOW, equity, 0.0),
                        cfg.max_per_trade_contracts)
        assert g.check_order(pr, contracts=c["size"], collateral=c["collateral"]).allow, yb


def test_compose_caps_tighten_nothing_at_todays_equity(monkeypatch, tmp_path):
    """Merging mid-flight must not TIGHTEN anything at the current $624 — a lower daily-
    loss line could trip the kill on an ordinary day; a lower deployed cap would shed book."""
    cfg = _compose_cfg(monkeypatch, tmp_path)
    g = RiskGate(cfg)
    assert g.deployed_cap(_pr(624.21)) >= 450.0
    assert g.daily_loss_cap(_pr(624.21)) >= 85.0
    assert cfg.max_per_trade_contracts >= 25
