"""Guard tests for the SPORTS GATE on the LIVE longshot arm (2026-08-25).

Live trades TEMP ONLY until the 2026-10-26 review. The reason is in config.py and
docker-compose.prod.yml: the sports series' only edge evidence is
VERDICT_EDGE_BY_CATEGORY.md, which reads `s3_markets_low` — the cheap-selected
ingest invalidated by VERDICT_BACKTEST_BIAS.md for deleting YES-bound brackets.
Sports had never fired live (0 non-temp positions in 62 days) and NCAAF week 1
closing 08-29 would have put live money into that class at full sizing.

The gate is one env line in compose, so the failure mode is silent divergence:
the code reads as "temp + sports", the container trades something else. That is
the same class as the KXNFLFIRST/KXNFLATD 404s (NFL never fired for months) and
the dead KXHIGHHOU (whitelist read as 8 cities, traded 7). These tests make the
compose file and longshot/config.py fail loudly instead.

To LIFT the gate: delete the LONGSHOT_WHITELIST line from the longshot-live
service and delete this module's gate assertions (or the module).
"""
from pathlib import Path

import pytest
import yaml

from longshot.config import (
    SPORTS_SERIES,
    TEMP_CITIES,
    TEMP_ONLY_WHITELIST,
    _DEFAULT_WHITELIST,
    LongshotConfig,
)

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.prod.yml"

LIVE_SERVICE = "longshot-live"
PAPER_SERVICE = "longshot"
CRYPTO_SERVICE = "longshot-paper-crypto"


def _services() -> dict:
    with COMPOSE.open() as fh:
        return yaml.safe_load(fh)["services"]


def _env(service: str) -> dict:
    """`environment:` of one compose service as a dict (list-of-KEY=VALUE form)."""
    entries = _services()[service].get("environment") or []
    out = {}
    for item in entries:
        key, _, value = str(item).partition("=")
        # strip the trailing `# comment` compose leaves on the value
        out[key.strip()] = value.split("#")[0].strip()
    return out


def _parsed(service: str) -> tuple:
    raw = _env(service).get("LONGSHOT_WHITELIST", "")
    return tuple(s.strip().upper() for s in raw.split(",") if s.strip())


# --- the constant itself -----------------------------------------------------


def test_temp_only_is_exactly_the_temp_cities():
    assert TEMP_ONLY_WHITELIST == tuple(f"KXHIGH{c}" for c in TEMP_CITIES)


def test_temp_only_is_a_subset_of_the_default():
    """Gating may only NARROW the validated set. If this fails, the gate has
    introduced a series that never passed the default whitelist's guards."""
    assert set(TEMP_ONLY_WHITELIST) <= set(_DEFAULT_WHITELIST)


def test_temp_only_carries_no_sports():
    assert not set(TEMP_ONLY_WHITELIST) & set(SPORTS_SERIES)


# --- live arm: the gate is on and matches the code ---------------------------


def test_live_sets_an_explicit_whitelist():
    """Absent env => LongshotConfig falls back to the default (temp + sports),
    so a missing line silently un-gates live. It must be present."""
    assert "LONGSHOT_WHITELIST" in _env(LIVE_SERVICE), (
        f"{LIVE_SERVICE} has no LONGSHOT_WHITELIST — live would fall back to the "
        f"default whitelist and start trading unvalidated sports series."
    )


def test_live_whitelist_matches_temp_only_constant():
    """Drift guard: edit TEMP_CITIES without editing compose and this fails."""
    assert _parsed(LIVE_SERVICE) == TEMP_ONLY_WHITELIST


@pytest.mark.parametrize("series", SPORTS_SERIES)
def test_live_whitelist_excludes_each_sports_series(series):
    """Stated independently of the equality check so the failure names the series
    that leaked into live."""
    assert series not in _parsed(LIVE_SERVICE)


def test_live_whitelist_is_well_formed():
    live = _parsed(LIVE_SERVICE)
    assert live, "live whitelist parsed empty — LongshotConfig would fall back to the default"
    for s in live:
        assert s == s.strip() and s.isupper() and s.startswith("KX"), f"malformed series: {s!r}"
    assert len(live) == len(set(live)), "duplicate series in the live whitelist"


def test_live_env_applies_cleanly_through_config(monkeypatch):
    """Round-trip the literal compose value through the real config loader."""
    monkeypatch.setenv("LONGSHOT_WHITELIST", _env(LIVE_SERVICE)["LONGSHOT_WHITELIST"])
    assert LongshotConfig().whitelist == TEMP_ONLY_WHITELIST


def test_gate_did_not_clobber_the_live_risk_controls():
    """The gate is an insertion into a hand-tuned env block. Values are free to be
    retuned; the KEYS disappearing would silently drop a cap or unset the arming
    flag, so assert presence only."""
    env = _env(LIVE_SERVICE)
    for key in (
        "LONGSHOT_MODE",
        "LONGSHOT_DRY_RUN",
        "LONGSHOT_KILL_FILE",
        "LONGSHOT_MAX_DEPLOYED",
        "LONGSHOT_MAX_PER_TRADE",
        "LONGSHOT_MAX_OPEN",
        "LONGSHOT_MAX_DAILY_LOSS",
        "LONGSHOT_TRADE_FRACTION",
    ):
        assert key in env, f"{key} missing from {LIVE_SERVICE} — a risk control was dropped"


# --- paper arm: the control must KEEP sports ---------------------------------


def test_paper_arm_is_not_gated():
    """The whole point of gating live is that paper trades the football season as
    the forward sports sample. Gating paper too would leave the question
    unanswerable at the 10-26 review."""
    assert "LONGSHOT_WHITELIST" not in _env(PAPER_SERVICE), (
        f"{PAPER_SERVICE} must keep the DEFAULT whitelist (sports included) — it is "
        f"the control arm that generates the unbiased sports sample."
    )


def test_default_whitelist_still_carries_sports():
    """Guards the other way to gate live: deleting SPORTS_SERIES from the code
    would gate live AND paper at once."""
    assert set(SPORTS_SERIES) <= set(_DEFAULT_WHITELIST)


# --- other arms untouched ----------------------------------------------------


def test_crypto_arm_whitelist_untouched():
    assert _parsed(CRYPTO_SERVICE) == ("KXBTCD", "KXETHD")


# --- the invariant that makes the gate safe to apply mid-flight --------------
#
# Narrowing the whitelist must never strand an already-open position. The
# whitelist is read in exactly one place (live_run.py:89, the discovery loop);
# settlement walks state["positions"] with no series filter. These tests pin that
# separation, because the gate ships while the live book holds open positions.


def test_settlement_ignores_the_whitelist():
    """A position in a series the whitelist no longer covers still settles."""
    from longshot import reconcile

    state = {
        "positions": [
            {"ticker": "KXNFLSPREAD-26AUG28TBJAC-TB8", "series": "KXNFLSPREAD",
             "status": "open", "sell_price": 0.06, "size": 10, "filled_size": 10, "fee": 0.04},
            {"ticker": "KXHIGHAUS-26AUG28-B99.5", "series": "KXHIGHAUS",
             "status": "open", "sell_price": 0.05, "size": 10, "filled_size": 10, "fee": 0.04},
        ]
    }
    n = reconcile.apply_settlements(state, [
        {"ticker": "KXNFLSPREAD-26AUG28TBJAC-TB8", "market_result": "no"},
        {"ticker": "KXHIGHAUS-26AUG28-B99.5", "market_result": "no"},
    ])
    assert n == 2
    gated = state["positions"][0]
    assert gated["status"] == "settled" and gated["result"] == "no"
    assert gated["pnl"] == reconcile.net_pnl(0.06, 10, 0.04, "no")


def test_whitelist_is_only_consulted_by_discovery():
    """Structural guard: if a future edit filters settlement/reconciliation by
    cfg.whitelist, narrowing it could orphan open positions. Keep the read in the
    discovery loop only."""
    from pathlib import Path

    live_src = (Path(__file__).resolve().parents[1] / "longshot" / "live_run.py").read_text()
    uses = [ln.strip() for ln in live_src.splitlines() if "cfg.whitelist" in ln]
    assert uses == ["for series in sorted(set(cfg.whitelist)):"], (
        f"cfg.whitelist is read in an unexpected place in live_run.py: {uses}. It must "
        f"gate DISCOVERY only — filtering settlement by it would strand open positions "
        f"whenever the whitelist narrows."
    )
