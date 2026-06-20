"""
Live paper test for the longshot-short strategy — the KC-7 check the backtest
cannot do: can we actually SELL these longshots into a real standing bid?

This does NOT place orders. It reads the live order book, records a paper SELL
at the current best bid (taker fill — conservative, gives up the spread), holds
to settlement, then resolves against the real outcome.

Two modes:
    uv run python -m kalshi_backtest.paper_test discover   # open paper sells now
    uv run python -m kalshi_backtest.paper_test resolve     # settle matured ones

Ledger: data/paper_ledger.json
"""
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from kalshi_backtest.ingest import KalshiClient, _load_creds
from kalshi_backtest.calibration import kalshi_fee_per_contract as fee

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("paper_test")

LEDGER = Path(__file__).parent / "data" / "paper_ledger.json"

# Validated categories. Temperature cities (year-round) + football in season.
WHITELIST = [f"KXHIGH{c}" for c in
             ("NY", "CHI", "LAX", "MIA", "AUS", "DEN", "PHIL", "HOU",
              "ATL", "BOS", "SEA", "DC", "PHX", "DEN", "MINN", "DET")]
BAND = (0.01, 0.12)        # cheap longshot YES band
MAX_HOURS_TO_CLOSE = 30    # ~1-day horizon
ACCOUNT = 8_000.0          # paper account
TRADE_FRACTION = 0.005     # 0.5% collateral per trade (the low-DD config)
MAX_DEPTH_FRAC = 0.25      # don't take more than 25% of the standing bid size


def _load_ledger():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"positions": []}


def _save_ledger(d):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(d, indent=2))


def discover():
    key_id, pem = _load_creds()
    c = KalshiClient(key_id, pem)
    led = _load_ledger()
    have = {p["ticker"] for p in led["positions"]}
    now = datetime.now(timezone.utc)

    deployed = sum(p["collateral"] for p in led["positions"] if p["status"] == "open")
    opened = 0
    for series in sorted(set(WHITELIST)):
        try:
            r = c.get("/markets", params={"series_ticker": series, "status": "open", "limit": 100})
        except Exception as e:
            logger.debug("%s: %s", series, e)
            continue
        for m in r.get("markets", []):
            tk = m["ticker"]
            if tk in have:
                continue
            ya = m.get("yes_ask_dollars")
            yb = m.get("yes_bid_dollars")
            bs = m.get("yes_bid_size_fp")
            ct = m.get("close_time")
            if ya is None or yb is None or bs is None or ct is None:
                continue
            ya, yb, bs = float(ya), float(yb), float(bs)
            if not (BAND[0] <= ya <= BAND[1]) or yb <= 0:
                continue
            close = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            hrs = (close - now).total_seconds() / 3600
            if hrs <= 0 or hrs > MAX_HOURS_TO_CLOSE:
                continue
            # Size: min(0.5% account / collateral_per, 25% of standing bid)
            collat_per = 1.0 - yb
            target = ACCOUNT * TRADE_FRACTION
            n = int(target / collat_per) if collat_per > 0 else 0
            n = max(1, min(n, int(MAX_DEPTH_FRAC * bs)))
            if n < 1:
                continue
            collat = collat_per * n
            if deployed + collat > ACCOUNT:
                continue
            led["positions"].append({
                "ticker": tk, "series": series,
                "entry_ts": now.isoformat(), "close_time": ct,
                "sell_price": yb, "size": n,
                "fee": round(fee(yb, n), 4),
                "collateral": round(collat, 2),
                "bid_depth_at_entry": bs,
                "status": "open", "result": None, "pnl": None,
            })
            deployed += collat
            have.add(tk)
            opened += 1
            logger.info("PAPER SELL %-34s %d @ %.2f  (bidDepth %.0f, close %s)",
                        tk, n, yb, bs, ct[:16])
    _save_ledger(led)
    print(f"\nOpened {opened} paper shorts. Total open collateral deployed: "
          f"${sum(p['collateral'] for p in led['positions'] if p['status']=='open'):,.2f} / ${ACCOUNT:,.0f}")
    c.close()


def resolve():
    key_id, pem = _load_creds()
    c = KalshiClient(key_id, pem)
    led = _load_ledger()
    now = datetime.now(timezone.utc)
    newly = 0
    for p in led["positions"]:
        if p["status"] != "open":
            continue
        close = datetime.fromisoformat(p["close_time"].replace("Z", "+00:00"))
        if close > now:
            continue
        try:
            m = c.get(f"/markets/{p['ticker']}").get("market", {})
        except Exception as e:
            logger.debug("resolve %s: %s", p["ticker"], e)
            continue
        res = (m.get("result") or "").lower()
        if res not in ("yes", "no"):
            continue  # not settled yet
        n, sp = p["size"], p["sell_price"]
        if res == "no":      # good — keep premium
            pnl = sp * n - p["fee"]
        else:                # bad — pay out
            pnl = -(1 - sp) * n - p["fee"]
        p["status"] = "settled"
        p["result"] = res
        p["pnl"] = round(pnl, 4)
        newly += 1
    _save_ledger(led)

    settled = [p for p in led["positions"] if p["status"] == "settled"]
    openp = [p for p in led["positions"] if p["status"] == "open"]
    tot_pnl = sum(p["pnl"] for p in settled)
    tot_collat = sum(p["collateral"] for p in settled)
    wins = sum(1 for p in settled if p["result"] == "no")
    print(f"\nNewly settled: {newly}")
    print(f"Settled positions: {len(settled)} | open still: {len(openp)}")
    if settled:
        print(f"Hit rate (resolved NO): {wins}/{len(settled)} = {100*wins/len(settled):.1f}%")
        print(f"Realized P&L: ${tot_pnl:+,.2f} on ${tot_collat:,.2f} collateral "
              f"= {100*tot_pnl/tot_collat:+.2f}% on capital at risk")
    c.close()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "discover"
    {"discover": discover, "resolve": resolve}[mode]()
