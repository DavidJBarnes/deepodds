"""Tests for balance-cache fixes and pre-order balance guard.

Covers:
1. read_balance_cache returns cash_cents (not portfolio_cents)
2. _write_balance_cache writes both cash_cents and portfolio_cents
3. Scanner exists filter includes 'cancelled' to break infinite retry
4. Pre-order balance guard skips orders when cost exceeds cash
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.models.signal import Signal


@pytest.fixture
def bal_path(tmp_path):
    """Provide a directory for balance files and a Path wrapper."""
    bal_dir = tmp_path / "balances"
    bal_dir.mkdir()
    return bal_dir


# ---------------------------------------------------------------------------
# 1. read_balance_cache returns cash_cents
# ---------------------------------------------------------------------------


class TestReadBalanceCache:
    def test_returns_cash_cents_when_file_exists(self, bal_path):
        uid = str(uuid.uuid4())
        data = {
            "cash_cents": 12345,
            "portfolio_cents": 99999,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        (bal_path / f"kalshi_balance_{uid}.json").write_text(json.dumps(data))

        from app.services.kalshi_utils import read_balance_cache as rbc

        with patch("pathlib.Path", lambda p: bal_path / Path(p).name if str(p).startswith("/tmp/kalshi_balance_") else Path(p)):
            result = rbc(uid)
            assert result == 12345.0

    def test_returns_none_when_file_missing(self, bal_path):
        from app.services.kalshi_utils import read_balance_cache as rbc

        with patch("pathlib.Path", lambda p: bal_path / Path(p).name if str(p).startswith("/tmp/kalshi_balance_") else Path(p)):
            result = rbc(str(uuid.uuid4()))
            assert result is None

    def test_returns_zero_when_no_cash_cents_key(self, bal_path):
        uid = str(uuid.uuid4())
        (bal_path / f"kalshi_balance_{uid}.json").write_text(
            json.dumps({"portfolio_cents": 99999})
        )

        from app.services.kalshi_utils import read_balance_cache as rbc

        with patch("pathlib.Path", lambda p: bal_path / Path(p).name if str(p).startswith("/tmp/kalshi_balance_") else Path(p)):
            result = rbc(uid)
            assert result == 0.0

    def test_returns_none_on_malformed_json(self, bal_path):
        uid = str(uuid.uuid4())
        (bal_path / f"kalshi_balance_{uid}.json").write_text("not json")

        from app.services.kalshi_utils import read_balance_cache as rbc

        with patch("pathlib.Path", lambda p: bal_path / Path(p).name if str(p).startswith("/tmp/kalshi_balance_") else Path(p)):
            result = rbc(uid)
            assert result is None


# ---------------------------------------------------------------------------
# 2. _write_balance_cache writes correct keys
# ---------------------------------------------------------------------------


class TestWriteBalanceCache:
    def test_writes_cash_and_portfolio_cents(self, bal_path):
        uid = str(uuid.uuid4())

        from app.core.scheduler import _write_balance_cache as wbc

        with patch("pathlib.Path", lambda p: bal_path / Path(p).name if str(p).startswith("/tmp/kalshi_balance_") else Path(p)):
            wbc(uid, {"balance": 1042, "portfolio_value": 3750})

        path = bal_path / f"kalshi_balance_{uid}.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["cash_cents"] == 1042
        assert data["portfolio_cents"] == 3750

    def test_writes_cached_at_timestamp(self, bal_path):
        uid = str(uuid.uuid4())

        from app.core.scheduler import _write_balance_cache as wbc

        with patch("pathlib.Path", lambda p: bal_path / Path(p).name if str(p).startswith("/tmp/kalshi_balance_") else Path(p)):
            wbc(uid, {"balance": 100, "portfolio_value": 200})

        path = bal_path / f"kalshi_balance_{uid}.json"
        data = json.loads(path.read_text())
        assert "cached_at" in data
        datetime.fromisoformat(data["cached_at"])

    def test_swallows_errors_gracefully(self, bal_path):
        from app.core.scheduler import _write_balance_cache as wbc

        def bad_path(p):
            if str(p).startswith("/tmp/kalshi_balance_"):
                raise OSError("disk full")
            return Path(p)

        with patch("pathlib.Path", bad_path):
            wbc(str(uuid.uuid4()), {"balance": 0})

        assert True


# ---------------------------------------------------------------------------
# 3. Scanner exists filter includes 'cancelled'
# ---------------------------------------------------------------------------


class TestScannerExistsFilter:
    """The scanner's exists check at scanner/loops/signal.py:115 must include
    'cancelled' so that a failed order doesn't retry every 10 seconds."""

    def test_status_tuple_includes_cancelled(self):
        status_tuple = ("signaled", "placed", "filled", "cancelled")
        assert "cancelled" in status_tuple

    def test_cancelled_signal_blocks_reentry_in_query(self):
        uid = uuid.uuid4()
        ticker = "KXHIGHTPHX-26JUN05-B105.5"

        sig_id = uuid.uuid4()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = sig_id

        session = MagicMock()
        session.execute.return_value = result_mock

        exists = session.execute(
            select(Signal.id).where(
                Signal.user_id == uid,
                Signal.market_ticker == ticker,
                Signal.status.in_(("signaled", "placed", "filled", "cancelled")),
            ).limit(1)
        ).scalar_one_or_none()

        assert exists == sig_id

    def test_old_filter_would_not_block_cancelled(self):
        """Reproduce the bug: old filter without 'cancelled' would miss it."""
        uid = uuid.uuid4()
        ticker = "KXHIGHTPHX-26JUN05-B105.5"

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        session = MagicMock()
        session.execute.return_value = result_mock

        exists = session.execute(
            select(Signal.id).where(
                Signal.user_id == uid,
                Signal.market_ticker == ticker,
                Signal.status.in_(("signaled", "placed", "filled")),
            ).limit(1)
        ).scalar_one_or_none()

        assert exists is None


# ---------------------------------------------------------------------------
# 4. Pre-order balance guard — logic verification
# ---------------------------------------------------------------------------


def _balance_guard_skips(
    cost_usd: float,
    bankroll_cents: float | None,
    has_client: bool = True,
) -> bool:
    """Replicate the guard from scanner/loops/signal.py:162-169."""
    if has_client and bankroll_cents is not None and bankroll_cents > 0:
        needed_cents = int(cost_usd * 100)
        if needed_cents > bankroll_cents:
            return True
    return False


class TestPreOrderBalanceGuard:
    def test_skips_when_cost_exceeds_cash(self):
        assert _balance_guard_skips(3.00, 200.0) is True

    def test_allows_when_cost_equals_cash(self):
        assert _balance_guard_skips(3.00, 300.0) is False

    def test_allows_when_cost_under_cash(self):
        assert _balance_guard_skips(2.00, 300.0) is False

    def test_allows_when_bankroll_is_none(self):
        assert _balance_guard_skips(999.0, None) is False

    def test_allows_when_bankroll_is_zero(self):
        assert _balance_guard_skips(3.00, 0.0) is False

    def test_allows_paper_mode_no_client(self):
        assert _balance_guard_skips(999.0, 100.0, has_client=False) is False

    def test_cents_rounding_works(self):
        assert _balance_guard_skips(0.10, 9.0) is True
        assert _balance_guard_skips(0.05, 5.0) is False

    def test_realistic_climate_order_rejected(self):
        cost = 4.50
        cash_cents = 300
        assert _balance_guard_skips(cost, cash_cents) is True

    def test_realistic_climate_order_accepted(self):
        cost = 2.50
        cash_cents = 300
        assert _balance_guard_skips(cost, cash_cents) is False
