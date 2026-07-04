"""Unit tests for the config-gated low-OI selection filter (backtest #209).

Guarantees the filter is SAFE for the live path: it is OFF by default (live
behavior unchanged), it only ever *removes* high-OI candidates when explicitly
enabled, and entry open-interest is RECORDED on every candidate regardless. Also
covers the oi_split within-book A/B used to read the paper experiment.

No network — size_candidate is pure over a market dict.
"""
from datetime import datetime, timezone

from longshot.config import LongshotConfig, _env_bool
from longshot.paper_run import size_candidate
from longshot.fill_diff import oi_split

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
CLOSE = "2030-01-01T10:00:00Z"   # 10h out, inside max_hours_to_close


def _market(oi, ticker="KXHIGHNY-30JAN01-T80"):
    return {
        "ticker": ticker, "yes_ask_dollars": 0.05, "yes_bid_dollars": 0.04,
        "yes_bid_size_fp": 1000.0, "close_time": CLOSE, "open_interest_fp": oi,
    }


def _cfg(enabled=False, oi_max=968.0, keep_high=False):
    cfg = LongshotConfig()
    cfg.oi_filter_enabled = enabled
    cfg.oi_max = oi_max
    cfg.oi_keep_high = keep_high
    return cfg


def test_filter_off_by_default():
    assert LongshotConfig().oi_filter_enabled is False


def test_oi_recorded_when_filter_off():
    c = size_candidate(_cfg(enabled=False), _market(50_000), "KXHIGHNY", NOW, 8000.0, 0.0)
    assert c is not None                      # high OI still allowed when off
    assert c["open_interest"] == 50_000


def test_filter_on_skips_high_oi():
    c = size_candidate(_cfg(enabled=True, oi_max=968), _market(5000), "KXHIGHNY", NOW, 8000.0, 0.0)
    assert c is None


def test_filter_on_keeps_low_oi():
    c = size_candidate(_cfg(enabled=True, oi_max=968), _market(500), "KXHIGHNY", NOW, 8000.0, 0.0)
    assert c is not None
    assert c["open_interest"] == 500


def test_filter_boundary_is_inclusive():
    # oi exactly == oi_max is KEPT (filter drops only oi > oi_max)
    c = size_candidate(_cfg(enabled=True, oi_max=968), _market(968), "KXHIGHNY", NOW, 8000.0, 0.0)
    assert c is not None


def test_missing_oi_treated_as_zero():
    m = _market(0)
    del m["open_interest_fp"]
    c = size_candidate(_cfg(enabled=True, oi_max=968), m, "KXHIGHNY", NOW, 8000.0, 0.0)
    assert c is not None and c["open_interest"] == 0.0


def test_keep_high_default_is_false():
    assert LongshotConfig().oi_keep_high is False


def test_keep_high_skips_low_oi():
    # inverted (high-OI) arm: low OI is skipped
    c = size_candidate(_cfg(enabled=True, oi_max=968, keep_high=True), _market(500), "KXHIGHNY", NOW, 8000.0, 0.0)
    assert c is None


def test_keep_high_keeps_high_oi():
    c = size_candidate(_cfg(enabled=True, oi_max=968, keep_high=True), _market(5000), "KXHIGHNY", NOW, 8000.0, 0.0)
    assert c is not None and c["open_interest"] == 5000


def test_keep_high_boundary_excludes_equal():
    # high-OI arm keeps oi > oi_max strictly; oi == oi_max is skipped
    # (so the two arms partition the universe with no overlap at the cut)
    c = size_candidate(_cfg(enabled=True, oi_max=968, keep_high=True), _market(968), "KXHIGHNY", NOW, 8000.0, 0.0)
    assert c is None


def test_low_and_high_arms_partition_universe():
    # every market lands in exactly one arm at the shared cut
    low = _cfg(enabled=True, oi_max=968, keep_high=False)
    high = _cfg(enabled=True, oi_max=968, keep_high=True)
    for oi in (0, 500, 968, 969, 5000):
        in_low = size_candidate(low, _market(oi), "KXHIGHNY", NOW, 8000.0, 0.0) is not None
        in_high = size_candidate(high, _market(oi), "KXHIGHNY", NOW, 8000.0, 0.0) is not None
        assert in_low != in_high, f"oi={oi} must be in exactly one arm"


def test_env_bool_helper(monkeypatch):
    monkeypatch.setenv("X", "true");  assert _env_bool("X", False) is True
    monkeypatch.setenv("X", "off");   assert _env_bool("X", True) is False
    monkeypatch.delenv("X", raising=False); assert _env_bool("X", True) is True


# --------------------------------------------------------------------------
# oi_split — within-book A/B
# --------------------------------------------------------------------------
def _pos(oi, result, size=1, sell=0.05, pnl=None, status="settled"):
    if pnl is None:
        pnl = sell * size if result == "no" else -(1 - sell) * size
    return {"status": status, "entry_oi": oi, "result": result, "size": size,
            "sell_price": sell, "pnl": round(pnl, 4)}


def test_oi_split_partitions_kept_and_dropped():
    pos = [_pos(100, "no"), _pos(200, "no"), _pos(5000, "yes"), _pos(8000, "no")]
    s = oi_split(pos, oi_max=968)
    assert s["with_oi"] == 4
    assert s["kept"]["n"] == 2 and s["dropped"]["n"] == 2
    assert s["all"]["n"] == 4
    # dropped contains the only YES -> kept YES-rate 0, dropped 0.5
    assert s["kept"]["yes_rate"] == 0.0
    assert s["dropped"]["yes_rate"] == 0.5


def test_oi_split_cents_ct_math():
    # two kept NO wins at 5c, 1ct each -> +5c/ct
    s = oi_split([_pos(100, "no", sell=0.05), _pos(200, "no", sell=0.05)], oi_max=968)
    assert s["kept"]["cents_ct"] == 5.0


def test_oi_split_ignores_unsettled_and_missing_oi():
    pos = [_pos(100, "no"), _pos(100, None, status="open"),
           {"status": "settled", "result": "no", "size": 1, "sell_price": 0.05, "pnl": 0.05}]  # no entry_oi
    s = oi_split(pos, oi_max=968)
    assert s["with_oi"] == 1
