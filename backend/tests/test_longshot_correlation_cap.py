"""Per-underlying correlation cap — the GO-A prerequisite. All BTC tails are one
trade; a single fat BTC day resolves them together, so cap open collateral per
correlation group. Default OFF must not change temp/sports behavior."""
from datetime import datetime, timezone

from longshot.config import LongshotConfig
from longshot.paper_run import underlying_key, deployed_by_underlying, discover_candidates

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
CLOSE = "2030-01-01T10:00:00Z"


def test_underlying_key_collapses_crypto_families():
    assert underlying_key("KXBTCD-30JAN01-T72000") == "BTC"
    assert underlying_key("KXBTC-30JAN0112-T80000") == "BTC"
    assert underlying_key("KXETHD-30JAN01-T4000") == "ETH"
    # non-crypto groups by event family (independent) -> per-series/per-city
    assert underlying_key("KXHIGHNY-30JAN01-T80") == "KXHIGHNY"
    assert underlying_key("KXMLBGAME-30JAN01-ABC") == "KXMLBGAME"


def test_deployed_by_underlying_sums_open_only():
    pos = [
        {"status": "open", "ticker": "KXBTCD-x-T1", "collateral": 5.0},
        {"status": "open", "ticker": "KXBTCD-x-T2", "collateral": 3.0},
        {"status": "settled", "ticker": "KXBTCD-x-T3", "collateral": 9.0},   # ignored
        {"status": "open", "ticker": "KXHIGHNY-x-T80", "collateral": 2.0},
    ]
    dbu = deployed_by_underlying(pos)
    assert dbu["BTC"] == 8.0 and dbu["KXHIGHNY"] == 2.0
    assert "settled" not in dbu


class _Client:
    """Serves one series of cheap BTC tail markets, all same underlying (BTC)."""
    def __init__(self, n):
        self._markets = [{
            "ticker": f"KXBTCD-30JAN01-T{72000+i}", "yes_ask_dollars": 0.05,
            "yes_bid_dollars": 0.05, "yes_bid_size_fp": 1000.0, "close_time": CLOSE,
            "open_interest_fp": 500.0,
        } for i in range(n)]

    def get(self, path, params=None):
        return {"markets": self._markets} if params.get("series_ticker") == "KXBTCD" else {"markets": []}


def _cfg(cap):
    c = LongshotConfig()
    c.whitelist = ("KXBTCD",)
    c.max_underlying_collateral = cap
    c.trade_fraction = 0.02
    return c


def test_cap_limits_total_btc_collateral():
    # each candidate ~0.95 collateral (sell 0.05, 1 ct after depth math on $1000 acct...)
    cands = discover_candidates(_cfg(cap=3.0), _Client(20), NOW, set(), 0.0, account=1000.0)
    total = sum(c["collateral"] for c in cands)
    assert total <= 3.0                      # BTC group capped
    assert len(cands) < 20                    # not all admitted


def test_cap_off_admits_all():
    cands = discover_candidates(_cfg(cap=0.0), _Client(20), NOW, set(), 0.0, account=1000.0)
    assert len(cands) == 20                   # cap disabled -> unchanged behavior


def test_cap_seeded_by_existing_positions():
    # already at the cap from open positions -> no new BTC candidates
    seed = {"BTC": 3.0}
    cands = discover_candidates(_cfg(cap=3.0), _Client(20), NOW, set(), 0.0,
                                account=1000.0, by_underlying=seed)
    assert cands == []
