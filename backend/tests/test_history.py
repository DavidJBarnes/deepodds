"""Tests for History model, schemas, and auto-capture hooks."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.schemas.history import HistoryCreate, HistoryListResponse, HistoryResponse


class TestHistorySchema:
    def test_create_valid(self):
        body = HistoryCreate(text="User changed Min Edge from 0.05 to 0.10")
        assert body.text == "User changed Min Edge from 0.05 to 0.10"

    def test_create_empty_text(self):
        body = HistoryCreate(text="")
        assert body.text == ""

    def test_response_fields(self):
        now = datetime.now(timezone.utc)
        resp = HistoryResponse(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            text="test",
            created_at=now,
        )
        assert resp.id == UUID("00000000-0000-0000-0000-000000000001")
        assert resp.user_id == UUID("00000000-0000-0000-0000-000000000002")
        assert resp.text == "test"
        assert resp.created_at == now

    def test_list_response(self):
        now = datetime.now(timezone.utc)
        item = HistoryResponse(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            text="test",
            created_at=now,
        )
        lst = HistoryListResponse(items=[item], total=1)
        assert len(lst.items) == 1
        assert lst.total == 1


class FakeAsyncSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass


class TestLogConfigChanges:
    """Direct unit tests of _log_config_changes in settings.py."""

    def _run(self, old, new, section="Crypto"):
        import anyio
        from app.api.v1.settings import _log_config_changes

        db = FakeAsyncSession()
        anyio.run(_log_config_changes, db, "user-1", section, old, new)
        return db

    def test_single_field_change(self):
        db = self._run({"min_edge": 0.05}, {"min_edge": 0.10})
        assert len(db.added) == 1
        e = db.added[0]
        assert e.user_id == "user-1"
        assert "Min Edge" in e.text and "0.05" in e.text and "0.1" in e.text

    def test_multiple_fields(self):
        db = self._run(
            {"min_edge": 0.05, "stop_loss_pct": 15.0},
            {"min_edge": 0.10, "stop_loss_pct": 10.0},
        )
        assert len(db.added) == 2
        labels = {"Min Edge", "Stop Loss %"}
        assert labels.issubset({_label_of(e.text) for e in db.added})

    def test_unchanged_field_skipped(self):
        db = self._run({"min_edge": 0.05}, {"min_edge": 0.05})
        assert len(db.added) == 0

    def test_none_to_value(self):
        db = self._run({"min_edge": None}, {"min_edge": 0.10})
        assert len(db.added) == 1
        assert "(none)" in db.added[0].text

    def test_value_to_none(self):
        db = self._run({"min_edge": 0.05}, {"min_edge": None})
        assert len(db.added) == 1
        assert "(none)" in db.added[0].text

    def test_all_field_labels_have_readable_names(self):
        from app.api.v1.settings import _FIELD_LABELS

        assert _FIELD_LABELS["min_volume_24h"] == "Min 24h Volume"
        assert _FIELD_LABELS["min_price"] == "Min Price"
        assert _FIELD_LABELS["max_price"] == "Max Price"
        assert _FIELD_LABELS["stop_loss_pct"] == "Stop Loss %"
        assert _FIELD_LABELS["take_profit_pct"] == "Take Profit %"
        assert _FIELD_LABELS["contracts_per_signal"] == "Contracts per Signal"
        assert _FIELD_LABELS["max_cost_per_signal"] == "Max Cost per Signal"
        assert _FIELD_LABELS["max_open_positions"] == "Max Open Positions"
        assert _FIELD_LABELS["daily_loss_limit_usd"] == "Daily Loss Limit ($)"
        assert _FIELD_LABELS["max_signals_per_hour"] == "Max Signals per Hour"
        assert _FIELD_LABELS["min_hold_minutes"] == "Min Hold Minutes"
        assert _FIELD_LABELS["min_hours_to_expiry"] == "Min Hours to Expiry"

    def test_field_labels_cover_all_crypto_config_fields(self):
        from app.api.v1.settings import _FIELD_LABELS
        from app.models.crypto_config import CryptoConfig

        table_cols = {
            c.name for c in CryptoConfig.__table__.columns
            if c.name not in ("id", "user_id", "created_at", "updated_at")
        }
        labeled = set(_FIELD_LABELS)
        missing = table_cols - labeled
        assert not missing, f"Config fields missing labels: {missing}"


def _label_of(text: str) -> str:
    """Extract the label from a history text like
    'User changed Min Edge from 0.05 to 0.10' -> 'Min Edge'."""
    parts = text.split(" changed ")
    return parts[1].split(" from ")[0] if len(parts) > 1 else ""
