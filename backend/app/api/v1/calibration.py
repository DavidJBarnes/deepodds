import os
import shutil
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.history import History
from app.models.model_train_history import ModelTrainHistory
from app.models.signal import Signal
from app.models.user import User
from app.schemas.calibration import CalibrationBin, CalibrationResponse, RetrainResponse
from app.services.climate_probability_model import (
    MODEL_FILE as CLIMATE_MODEL_FILE,
    reload_booster as reload_climate_booster,
)
from app.services.train_climate_model import train_and_save_climate_model

router = APIRouter(tags=["calibration"])

SETTLED_STATUSES = ("settled_win", "settled_loss", "settled_breakeven")
BIN_COUNT = 10

VENUE_CLIMATE = "kalshi_climate"


def _compute_calibration(settled_signals: list[tuple[float, int]]) -> CalibrationResponse:
    bins: list[CalibrationBin] = []
    total = len(settled_signals)

    for i in range(BIN_COUNT):
        lo = i / BIN_COUNT
        hi = (i + 1) / BIN_COUNT
        label = f"{int(lo * 100)}-{int(hi * 100)}%"

        probs = [p for p, w in settled_signals if lo < p <= hi]
        counts = len(probs)
        wins = sum(w for p, w in settled_signals if lo < p <= hi)
        avg_prob = sum(probs) / counts if counts else 0.0
        actual_rate = wins / counts if counts else 0.0

        bins.append(CalibrationBin(
            bin_label=label,
            bin_low=round(lo, 2),
            bin_high=round(hi, 2),
            count=counts,
            wins=wins,
            avg_model_prob=round(avg_prob, 4),
            actual_win_rate=round(actual_rate, 4),
        ))

    brier = 0.0
    for p, w in settled_signals:
        brier += (p - w) ** 2
    brier /= total if total else 1

    reliability_ready = total >= 10

    return CalibrationResponse(
        bins=bins,
        total_samples=total,
        brier_score=round(brier, 4),
        reliability_ready=reliability_ready,
    )


@router.get("/calibration", response_model=CalibrationResponse)
async def get_calibration(
    venue: str = Query("kalshi_climate", pattern="^(kalshi_climate)$"),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Calibration is a property of the model, not the viewer. Pool settled
    # signals across all users so a fresh account doesn't see an empty chart
    # while the model itself has plenty of resolved data. Still gated on
    # get_current_user for auth.
    #
    # Filter to signals that reached a genuine resolution: either the exit
    # price snapped to a binary outcome (0 / 1, indicating settle-at-expiry)
    # or the position was held longer than 2 hours (excludes stop-loss
    # noise where positions exit on bid-ask spread movement).
    rows = await db.execute(
        select(Signal.model_prob, Signal.status)
        .where(
            Signal.venue == venue,
            Signal.status.in_(SETTLED_STATUSES),
            Signal.model_prob.isnot(None),
            or_(
                Signal.exit_price.in_([0.0, 1.0]),
                (Signal.resolved_at - Signal.filled_at) > timedelta(hours=2),
            ),
        )
    )
    settled = [
        (row[0], 1 if row[1] == "settled_win" else 0)
        for row in rows.all()
    ]
    return _compute_calibration(settled)


def _kb(path: str) -> float:
    return os.path.getsize(path) / 1024 if os.path.exists(path) else 0.0


@router.post("/calibration/retrain", response_model=RetrainResponse)
async def trigger_retrain(
    venue: str = Query(
        "kalshi_climate",
        pattern="^(kalshi_climate)$",
        description="Which model to retrain (climate only).",
    ),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrain the climate model, snapshot the new file, and mark that
    snapshot active in model_train_history."""
    started_at = datetime.now(timezone.utc)

    climate_ok, climate_snapshot = await train_and_save_climate_model()
    if climate_ok:
        reload_climate_booster()

    climate_kb = _kb(CLIMATE_MODEL_FILE)
    msg = f"Retrain: {'climate OK' if climate_ok else 'climate FAILED'} ({climate_kb:.0f} KB)."

    if climate_ok and climate_snapshot:
        await db.execute(
            update(ModelTrainHistory)
            .where(ModelTrainHistory.climate_active.is_(True))
            .values(climate_active=False)
        )

    db.add(History(user_id=_user.id, text=msg))
    db.add(
        ModelTrainHistory(
            user_id=_user.id,
            model_type="climate",
            climate_ok=climate_ok,
            climate_size_kb=climate_kb,
            total_size_kb=round(climate_kb, 1),
            climate_model_path=climate_snapshot,
            climate_active=bool(climate_ok and climate_snapshot),
            message=msg,
            trigger="manual",
            started_at=started_at,
        )
    )
    await db.commit()

    return RetrainResponse(
        success=bool(climate_ok),
        message=msg,
        model_file_size_kb=round(climate_kb, 1),
    )


@router.post("/calibration/rollback", response_model=RetrainResponse)
async def rollback_model(
    history_id: UUID = Query(..., description="model_train_history row to restore"),
    venue: str = Query("kalshi_climate", pattern="^(kalshi_climate)$"),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Roll the climate model back to a prior snapshot. Copies the snapshot
    file over the canonical model path, reloads the in-process booster, and
    flips active flags so the target row becomes the active one."""
    row = await db.get(ModelTrainHistory, history_id)
    if row is None:
        raise HTTPException(status_code=404, detail="History row not found")

    snapshot = row.climate_model_path
    canonical = CLIMATE_MODEL_FILE
    active_col = ModelTrainHistory.climate_active
    reload = reload_climate_booster

    if not snapshot or not os.path.exists(snapshot):
        raise HTTPException(
            status_code=400,
            detail=f"Snapshot file missing for that history row ({snapshot or 'no path stored'})",
        )

    shutil.copyfile(snapshot, canonical)
    reload()

    await db.execute(
        update(ModelTrainHistory).where(active_col.is_(True)).values(**{active_col.key: False})
    )
    await db.execute(
        update(ModelTrainHistory)
        .where(ModelTrainHistory.id == history_id)
        .values(**{active_col.key: True})
    )

    kb = _kb(canonical)
    msg = f"Rolled back {venue} to snapshot {os.path.basename(snapshot)} ({kb:.0f} KB)."
    db.add(History(user_id=_user.id, text=msg))
    await db.commit()

    return RetrainResponse(success=True, message=msg, model_file_size_kb=round(kb, 1))
