"""Tests for the Kalshi order-book recorder. No network — client is faked."""
import json

import vrp.kalshi_book_recorder as br


class _Client:
    def __init__(self, markets_by_series, books):
        self._m = markets_by_series
        self._b = books
        self.book_calls = []

    def get(self, path, params=None):
        if path == "/markets":
            return {"markets": self._m.get(params["series_ticker"], [])}
        if path.endswith("/orderbook"):
            t = path.split("/markets/")[1].split("/orderbook")[0]
            self.book_calls.append(t)
            return {"orderbook": self._b.get(t, {})}
        raise AssertionError(path)


def test_top_oi_sorts_and_truncates():
    c = _Client({
        "KXBTCD": [{"ticker": "b1", "open_interest_fp": 100},
                   {"ticker": "b2", "open_interest_fp": 900}],
        "KXMLBGAME": [{"ticker": "m1", "open_interest_fp": 500}],
    }, {})
    top = br.top_oi_markets(c, ("KXBTCD", "KXMLBGAME"), top_n=2)
    assert top == ["b2", "m1"]        # highest OI first, truncated to 2


def test_run_once_writes_snapshots(tmp_path):
    c = _Client(
        {"KXBTCD": [{"ticker": "b2", "open_interest_fp": 900}]},
        {"b2": {"yes": [[5, 100]], "no": [[95, 200]]}},
    )
    n = br.run_once(c, str(tmp_path), series=("KXBTCD",), top_n=5)
    assert n == 1
    line = json.loads((tmp_path / next(f.name for f in tmp_path.iterdir())).read_text().strip())
    assert line["ticker"] == "b2" and line["yes"] == [[5, 100]] and line["ts"]


def test_run_once_tolerates_book_failure(tmp_path):
    class _Flaky(_Client):
        def get(self, path, params=None):
            if path.endswith("/orderbook"):
                raise RuntimeError("book down")
            return super().get(path, params)
    c = _Flaky({"KXBTCD": [{"ticker": "b2", "open_interest_fp": 900}]}, {})
    assert br.run_once(c, str(tmp_path), series=("KXBTCD",)) == 0    # no crash, nothing written
