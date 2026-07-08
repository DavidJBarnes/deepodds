"""Tests for the Deribit-oracle capture daemon. No network — scan + Kalshi client
are faked. Covers snapshot append, settlement backfill, idempotency, realized pnl."""
import json
from datetime import datetime, timezone

import vrp.oracle_daemon as od

NOW = datetime(2026, 7, 8, 18, 0, tzinfo=timezone.utc)


def _snap(ticker, close_iso, bid=0.05, fair=0.01):
    return {"ticker": ticker, "close_time": close_iso, "kalshi_bid": bid,
            "kalshi_mid": bid, "deribit_fair": fair, "gap": bid - fair,
            "sell_ev_vs_deribit": round(bid - fair, 4), "captured_ts": NOW.isoformat()}


def test_capture_appends_snapshots(monkeypatch, tmp_path):
    monkeypatch.setattr(od, "scan", lambda client, series, currency, now: [
        _snap(f"{series}-x-T1", "2026-07-08T15:00:00Z")])
    n = od.capture(None, str(tmp_path), NOW)
    assert n == 2                                   # BTC + ETH series
    f = tmp_path / "oracle_20260708.jsonl"
    assert len(f.read_text().strip().splitlines()) == 2


def test_capture_tolerates_one_series_failing(monkeypatch, tmp_path):
    def flaky(client, series, currency, now):
        if series == "KXETHD":
            raise RuntimeError("deribit down")
        return [_snap("KXBTCD-x-T1", "2026-07-08T15:00:00Z")]
    monkeypatch.setattr(od, "scan", flaky)
    assert od.capture(None, str(tmp_path), NOW) == 1


class _Client:
    def __init__(self, results):
        self.results = results          # ticker -> "yes"/"no"
    def get(self, path, params=None):
        t = path.split("/markets/")[1]
        return {"market": {"result": self.results.get(t, "")}}


def test_resolve_pending_settles_closed_and_computes_pnl(tmp_path):
    # two captured tails, both closed before NOW
    snaps = [_snap("KXBTCD-x-T1", "2026-07-08T15:00:00Z", bid=0.05),
             _snap("KXBTCD-x-T2", "2026-07-08T15:00:00Z", bid=0.10)]
    (tmp_path / "oracle_20260708.jsonl").write_text("\n".join(json.dumps(s) for s in snaps))
    client = _Client({"KXBTCD-x-T1": "no", "KXBTCD-x-T2": "yes"})
    n = od.resolve_pending(client, str(tmp_path), NOW)
    assert n == 2
    rec = {r["ticker"]: r for r in
           (json.loads(l) for l in (tmp_path / "resolved.jsonl").read_text().splitlines())}
    assert rec["KXBTCD-x-T1"]["realized_pnl"] == 0.05        # NO -> keep bid
    assert abs(rec["KXBTCD-x-T2"]["realized_pnl"] - (-(1 - 0.10))) < 1e-9  # YES -> -0.90


def test_resolve_pending_is_idempotent(tmp_path):
    snaps = [_snap("KXBTCD-x-T1", "2026-07-08T15:00:00Z")]
    (tmp_path / "oracle_20260708.jsonl").write_text(json.dumps(snaps[0]))
    client = _Client({"KXBTCD-x-T1": "no"})
    assert od.resolve_pending(client, str(tmp_path), NOW) == 1
    assert od.resolve_pending(client, str(tmp_path), NOW) == 0     # already resolved


def test_resolve_skips_not_yet_closed(tmp_path):
    snaps = [_snap("KXBTCD-x-T1", "2026-07-09T15:00:00Z")]     # closes AFTER now
    (tmp_path / "oracle_20260708.jsonl").write_text(json.dumps(snaps[0]))
    assert od.resolve_pending(_Client({}), str(tmp_path), NOW) == 0
