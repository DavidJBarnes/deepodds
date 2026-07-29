"""Tests for the Kalshi order-book recorder. No network — client is faked.

The fake MUST mirror the live response shape. An earlier version returned
{"orderbook": {"yes": ...}} — a shape the API does not produce — so it agreed with
a bug that read the same wrong key, and CI stayed green while prod banked nulls for
weeks. Verified against api.elections.kalshi.com on 2026-07-29: depth comes back as
{"orderbook_fp": {"yes_dollars": [["0.0100","52559.98"], ...], "no_dollars": [...]}}
with every numeric field a decimal STRING.
"""
import json

import vrp.kalshi_book_recorder as br

# One high-OI market row, fields verbatim from the live /markets response.
MKT = {
    "ticker": "b2", "open_interest_fp": "900.00",
    "yes_bid_dollars": "0.4800", "yes_ask_dollars": "0.4900",
    "yes_bid_size_fp": "19816.89", "yes_ask_size_fp": "170314.88",
}
BOOK = {"yes_dollars": [["0.0100", "52559.98"]], "no_dollars": [["0.5400", "113819.92"]]}


class _Client:
    def __init__(self, markets_by_series, books, book_key="orderbook_fp"):
        self._m = markets_by_series
        self._b = books
        self._book_key = book_key
        self.book_calls = []

    def get(self, path, params=None):
        if path == "/markets":
            return {"markets": self._m.get(params["series_ticker"], [])}
        if path.endswith("/orderbook"):
            t = path.split("/markets/")[1].split("/orderbook")[0]
            self.book_calls.append(t)
            return {self._book_key: self._b.get(t, {})}
        raise AssertionError(path)


def test_top_oi_sorts_and_truncates():
    c = _Client({
        "KXBTCD": [{"ticker": "b1", "open_interest_fp": "100"},
                   {"ticker": "b2", "open_interest_fp": "900"}],
        "KXMLBGAME": [{"ticker": "m1", "open_interest_fp": "500"}],
    }, {})
    top = br.top_oi_markets(c, ("KXBTCD", "KXMLBGAME"), top_n=2)
    assert [m["ticker"] for m in top] == ["b2", "m1"]   # highest OI first, truncated to 2


def test_run_once_captures_real_orderbook_fp_shape(tmp_path):
    """The regression that mattered: orderbook_fp / *_dollars must land as depth."""
    c = _Client({"KXBTCD": [MKT]}, {"b2": BOOK})
    assert br.run_once(c, str(tmp_path), series=("KXBTCD",), top_n=5) == 1
    line = json.loads((tmp_path / next(f.name for f in tmp_path.iterdir())).read_text().strip())
    assert line["yes"] == [[0.01, 52559.98]]           # parsed to floats, NOT None
    assert line["no"] == [[0.54, 113819.92]]
    assert line["ticker"] == "b2" and line["ts"]


def test_run_once_carries_top_of_book_and_oi(tmp_path):
    """Top-of-book rides along from the market row — no extra call, and it survives
    even if the depth endpoint goes dark for real."""
    c = _Client({"KXBTCD": [MKT]}, {"b2": BOOK})
    br.run_once(c, str(tmp_path), series=("KXBTCD",), top_n=5)
    line = json.loads((tmp_path / next(f.name for f in tmp_path.iterdir())).read_text().strip())
    assert line["yes_bid"] == 0.48 and line["yes_ask"] == 0.49
    assert line["yes_bid_size"] == 19816.89 and line["yes_ask_size"] == 170314.88
    assert line["oi"] == 900.0


def test_run_once_accepts_legacy_orderbook_shape(tmp_path):
    """If Kalshi ever serves the pre-migration shape again, don't silently bank nulls."""
    c = _Client({"KXBTCD": [MKT]}, {"b2": {"yes": [["0.05", "100"]], "no": [["0.95", "200"]]}},
                book_key="orderbook")
    br.run_once(c, str(tmp_path), series=("KXBTCD",), top_n=5)
    line = json.loads((tmp_path / next(f.name for f in tmp_path.iterdir())).read_text().strip())
    assert line["yes"] == [[0.05, 100.0]]


def test_empty_depth_records_none_not_empty_list(tmp_path):
    """An empty book must read as unpopulated so the explorer's dq rule can see it."""
    c = _Client({"KXBTCD": [MKT]}, {"b2": {"yes_dollars": [], "no_dollars": []}})
    br.run_once(c, str(tmp_path), series=("KXBTCD",), top_n=5)
    line = json.loads((tmp_path / next(f.name for f in tmp_path.iterdir())).read_text().strip())
    assert line["yes"] is None and line["no"] is None
    assert not (line.get("yes") or line.get("no"))     # matches sources.bookrec_latest_stats


def test_run_once_tolerates_book_failure(tmp_path):
    class _Flaky(_Client):
        def get(self, path, params=None):
            if path.endswith("/orderbook"):
                raise RuntimeError("book down")
            return super().get(path, params)
    c = _Flaky({"KXBTCD": [MKT]}, {})
    assert br.run_once(c, str(tmp_path), series=("KXBTCD",)) == 0    # no crash, nothing written
