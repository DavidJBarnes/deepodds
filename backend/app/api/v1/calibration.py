import os
from datetime import timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.history import History
from app.models.signal import Signal
from app.models.user import User
from app.schemas.calibration import CalibrationBin, CalibrationResponse, RetrainResponse
from app.services.climate_probability_model import (
    MODEL_FILE as CLIMATE_MODEL_FILE,
    reload_booster as reload_climate_booster,
)
from app.services.probability_model import MODEL_FILE, reload_booster
from app.services.train_climate_model import train_and_save_climate_model
from app.services.train_model import train_and_save_model

router = APIRouter(tags=["calibration"])

SETTLED_STATUSES = ("settled_win", "settled_loss", "settled_breakeven")
BIN_COUNT = 10


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
    venue: str = Query("kalshi_crypto", pattern="^(kalshi_crypto|kalshi_climate)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Filter to signals that reached a genuine resolution: either the exit
    # price snapped to a binary outcome (0 / 1, indicating settle-at-expiry)
    # or the position was held longer than 2 hours (excludes stop-loss
    # noise where positions exit on bid-ask spread movement). Without this
    # filter, calibration is dominated by exit prices like $0.32 from
    # short-held stop-outs, which doesn't tell us anything about the
    # model's actual predictive accuracy.
    rows = await db.execute(
        select(Signal.model_prob, Signal.status)
        .where(
            Signal.user_id == user.id,
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


@router.post("/calibration/retrain", response_model=RetrainResponse)
async def trigger_retrain(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrain the crypto (Binance) and climate (Open-Meteo) models, then reload both boosters."""
    crypto_ok = await train_and_save_model()
    if crypto_ok:
        reload_booster()

    climate_ok = await train_and_save_climate_model()
    if climate_ok:
        reload_climate_booster()

    crypto_kb = os.path.getsize(MODEL_FILE) / 1024 if os.path.exists(MODEL_FILE) else 0
    climate_kb = os.path.getsize(CLIMATE_MODEL_FILE) / 1024 if os.path.exists(CLIMATE_MODEL_FILE) else 0
    total_kb = round(crypto_kb + climate_kb, 1)

    if crypto_ok and climate_ok:
        msg = f"Crypto + climate models retrained (crypto {crypto_kb:.0f} KB, climate {climate_kb:.0f} KB)."
        db.add(History(user_id=_user.id, text=msg))
        await db.commit()
        return RetrainResponse(success=True, message=msg, model_file_size_kb=total_kb)

    parts = []
    if crypto_ok:
        parts.append(f"crypto OK ({crypto_kb:.0f} KB)")
    else:
        parts.append("crypto FAILED")
    if climate_ok:
        parts.append(f"climate OK ({climate_kb:.0f} KB)")
    else:
        parts.append("climate FAILED")
    msg = "Retrain partial: " + ", ".join(parts) + ". Check backend logs."
    db.add(History(user_id=_user.id, text=msg))
    await db.commit()
    return RetrainResponse(
        success=crypto_ok or climate_ok,
        message=msg,
        model_file_size_kb=total_kb,
    )
