"""Guard tests for the longshot trading whitelist.

The canary once shipped a whitelist containing series names that do not exist on
Kalshi (KXNFLFIRST/KXNFLATD → 404), so NFL silently never traded. These tests make
that class of typo impossible to merge again:

  - offline structural checks (always run): well-formed, unique, non-empty.
  - online existence check (skips cleanly without network): every whitelisted
    series returns 200 from Kalshi's /series/{ticker} endpoint.

Run the online check before any deploy that changes the whitelist:
    python -m pytest tests/test_longshot_whitelist.py -v
"""
import urllib.error
import urllib.request

import pytest

from longshot.config import LongshotConfig
from longshot.kalshi_client import BASE_URL

WHITELIST = list(LongshotConfig().whitelist)


def test_whitelist_nonempty():
    assert WHITELIST, "longshot whitelist must not be empty"


def test_whitelist_well_formed():
    # Kalshi series tickers are upper-case and start with KX.
    for s in WHITELIST:
        assert s == s.strip() and s.isupper() and s.startswith("KX"), f"malformed series: {s!r}"


def test_whitelist_unique():
    assert len(WHITELIST) == len(set(WHITELIST)), "duplicate series in whitelist"


def _series_exists(series: str) -> bool:
    url = f"{BASE_URL}/series/{series}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


@pytest.mark.parametrize("series", WHITELIST)
def test_whitelisted_series_exists_on_kalshi(series):
    """Every whitelisted series must exist on Kalshi (200), else the discover loop
    queries a dead series_ticker and silently trades nothing. Skips if no network."""
    try:
        exists = _series_exists(series)
    except (urllib.error.URLError, OSError) as e:
        pytest.skip(f"Kalshi unreachable ({e}) — run with network to validate whitelist")
    assert exists, (
        f"{series} returns 404 from Kalshi /series — it does not exist. The discover "
        f"loop would trade nothing for it. Fix the name in longshot/config.py."
    )
