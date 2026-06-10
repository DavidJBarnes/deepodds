"""Loop plumbing: per-tick history JSONL, heartbeat, bounded run, error isolation.
run_once is monkeypatched so these tests never touch the network."""
import json

import carry.loop as loop
from carry.config import CarryConfig


def _fake_snap(ts):
    return {"ts": ts, "cash": 90000.0, "equity": 100000.0 + ts,
            "accrued_funding_total": ts, "realized_pnl": 0.0, "fees_total": 1.0,
            "killed": False, "symbols": {"BTC": {"notional": 1000.0}}, "log_tail": ["x"]}


def test_history_and_heartbeat_written(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "HISTORY_FILE", str(tmp_path / "h.jsonl"))
    monkeypatch.setattr(loop, "HEARTBEAT_FILE", str(tmp_path / "hb.json"))
    monkeypatch.setattr(loop, "_STOP", False)
    counter = {"n": 0}

    def fake_run_once(cfg):
        counter["n"] += 1
        return _fake_snap(counter["n"])

    monkeypatch.setattr(loop, "run_once", fake_run_once)
    monkeypatch.setattr(loop, "print_snapshot", lambda s: None)

    n = loop.run_loop(CarryConfig(), interval=0, max_ticks=3)
    assert n == 3

    lines = (tmp_path / "h.jsonl").read_text().strip().splitlines()
    assert len(lines) == 3
    recs = [json.loads(line) for line in lines]
    assert [r["accrued_funding_total"] for r in recs] == [1, 2, 3]   # grows each tick
    assert "log_tail" not in recs[0]                                 # stripped from history
    hb = json.loads((tmp_path / "hb.json").read_text())
    assert hb["status"] == "ok" and hb["killed"] is False


def test_loop_isolates_tick_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "HISTORY_FILE", str(tmp_path / "h.jsonl"))
    monkeypatch.setattr(loop, "HEARTBEAT_FILE", str(tmp_path / "hb.json"))
    monkeypatch.setattr(loop, "_STOP", False)

    def boom(cfg):
        raise RuntimeError("network down")

    monkeypatch.setattr(loop, "run_once", boom)
    monkeypatch.setattr(loop, "print_snapshot", lambda s: None)

    # a throwing tick must NOT crash the loop; it records an error heartbeat
    n = loop.run_loop(CarryConfig(), interval=0, max_ticks=2)
    assert n == 2
    hb = json.loads((tmp_path / "hb.json").read_text())
    assert hb["status"] == "error" and "network down" in hb["error"]


def test_loop_stops_on_kill(tmp_path, monkeypatch):
    monkeypatch.setattr(loop, "HISTORY_FILE", str(tmp_path / "h.jsonl"))
    monkeypatch.setattr(loop, "HEARTBEAT_FILE", str(tmp_path / "hb.json"))
    monkeypatch.setattr(loop, "_STOP", False)

    def killed_run(cfg):
        s = _fake_snap(1)
        s["killed"] = True
        return s

    monkeypatch.setattr(loop, "run_once", killed_run)
    monkeypatch.setattr(loop, "print_snapshot", lambda s: None)

    n = loop.run_loop(CarryConfig(), interval=999, max_ticks=10)
    assert n == 1   # kill-switch stops the loop after the first tick
